"""Reuse metadata without sharing a request's scope or SQLite generation."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

import pytest

import navcom_atlas
from navcom_atlas import Atlas, identity
import navcom_navigation as navigation
from test_atlas import add


@pytest.fixture(autouse=True)
def isolated_pool(monkeypatch, tmp_path):
    monkeypatch.setenv('NAVCOM_STARSHIP_ROOT',str(tmp_path/'absent-starship'))
    with navigation._ATLAS_POOL_LOCK:
        navigation._ATLAS_POOL.clear()
    yield
    with navigation._ATLAS_POOL_LOCK:
        navigation._ATLAS_POOL.clear()


def chart(tmp_path, navcom, projects):
    nodes=[dict(id='galaxy:owner',kind='galaxy',label='Owner',parent_id=None,
                conversation_collections=[],source_scopes=[],source_ids=[])]
    for i,project in enumerate(projects):
        nodes.append(dict(id=f'planet:{i}',kind='planet',label=project,parent_id='galaxy:owner',
                          conversation_collections=['projects:'+identity(navcom.pretty_project(project))],
                          source_scopes=[],source_ids=[]))
    for node in nodes:
        node.update(locations=[],evidence=[],examples=[],position=dict(x=0,y=0))
    path=tmp_path/'space.json'
    path.write_text(json.dumps(dict(schema_version=1,published=123,entities=nodes,edges=[],coverage={})))
    return path


def search(navcom, conn, cache, place='galaxy:owner', query='amber'):
    return navigation.evidence(navcom,conn,cache,cache.parent/'sources',place,query)


def test_repeated_requests_reuse_catalog_without_reusing_their_scope(navcom,tmp_path,monkeypatch):
    db=tmp_path/'index.sqlite';conn=navcom.open_index(db)
    projects=['/work/Orchard','/work/Harbor']
    keys=[add(navcom,conn,tmp_path/f'{i}.jsonl','Amber project','amber',p) for i,p in enumerate(projects)]
    conn.close();conn=navigation.conversation_connection(db)
    cache=chart(tmp_path,navcom,projects)
    native=navcom._session_parent;calls=[]
    def observed(*args):
        calls.append(args[1]);return native(*args)
    monkeypatch.setattr(navcom,'_session_parent',observed)
    first=search(navcom,conn,cache,'planet:0')
    built=len(calls)
    other=navigation.conversation_connection(db)
    try:
        second=search(navcom,other,cache,'planet:1')
        assert {r['key'] for r in first['conversations']}=={keys[0]}
        assert {r['key'] for r in second['conversations']}=={keys[1]}
        assert len(calls)==built==2
        assert not conn.in_transaction and not other.in_transaction
        assert len(navigation._ATLAS_POOL)==1
    finally:other.close();conn.close()


def test_same_count_metadata_and_annotations_invalidate_across_connections(navcom,tmp_path):
    db=tmp_path/'index.sqlite';conn=navcom.open_index(db)
    key=add(navcom,conn,tmp_path/'one.jsonl','Amber title','amber','/work/Orchard')
    conn.close();conn=navigation.conversation_connection(db)
    cache=chart(tmp_path,navcom,['/work/Orchard','/work/Harbor'])
    first=search(navcom,conn,cache,'planet:0')
    atlas=next(iter(navigation._ATLAS_POOL.values()))[0]
    original=atlas.signature
    writer=navigation.conversation_connection(db)
    writer.execute('UPDATE file_meta SET project=?,title=? WHERE file=?',('/work/Harbor','Amber new title',key));writer.commit()
    second=search(navcom,writer,cache,'planet:1')
    assert first['conversations'][0]['label']=='Amber title'
    assert second['conversations'][0]['label']=='Amber new title'
    assert atlas.signature!=original
    navcom._ui_write(writer,'annotations',{key:dict(name='Amber annotated',favorite=True)})
    third=search(navcom,conn,cache,'planet:1')
    assert third['conversations'][0]['label']=='Amber annotated'
    assert atlas.records[key]['favorite']
    writer.close();conn.close()


def test_parallel_requests_keep_entire_discovery_on_one_epoch(navcom,tmp_path,monkeypatch):
    db=tmp_path/'index.sqlite';setup=navcom.open_index(db)
    key=add(navcom,setup,tmp_path/'one.jsonl','Amber old title','amber','/work/Orchard')
    cache=chart(tmp_path,navcom,['/work/Orchard'])
    setup.close()
    entered=threading.Event();release=threading.Event();second_started=threading.Event()
    native=Atlas.search;seen=[]
    def delayed(self,conn,records,query):
        old_signature=self.signature
        if query=='amber':
            entered.set()
            assert release.wait(5)
            assert self.signature==old_signature
            assert records[key]['title']=='Amber old title'
        seen.append((query,self.signature,records[key]['title']))
        return native(self,conn,records,query)
    monkeypatch.setattr(Atlas,'search',delayed)
    def request(query):
        conn=navigation.conversation_connection(db)
        try:
            if query=='cobalt':second_started.set()
            return search(navcom,conn,cache,query=query)
        finally:conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(request,'amber')
        assert entered.wait(5)
        writer=sqlite3.connect(db)
        writer.execute('UPDATE file_meta SET title=? WHERE file=?',('Cobalt new title',key))
        writer.execute('UPDATE session_fts SET text=? WHERE file=?',('cobalt',key));writer.commit();writer.close()
        second=pool.submit(request,'cobalt')
        assert second_started.wait(5)
        release.set()
        old=first.result(timeout=8);new=second.result(timeout=8)
    assert not old['errors'] and not new['errors']
    assert old['conversations'][0]['label']=='Amber old title'
    assert old['conversations'][0]['excerpt']=='Amber old title amber'
    assert new['conversations'][0]['label']=='Cobalt new title'
    assert new['conversations'][0]['excerpt']=='cobalt'
    assert len({row[1] for row in seen})==2


def test_connection_local_state_never_enters_shared_pool(navcom,tmp_path):
    memory=navcom._initialize_index(sqlite3.connect(':memory:'))
    assert navigation._atlas_entry(navcom,memory)[0] is not navigation._atlas_entry(navcom,memory)[0]
    conn=navcom.open_index(tmp_path/'index.sqlite')
    conn.execute('BEGIN')
    assert navigation._atlas_entry(navcom,conn)[0] is not navigation._atlas_entry(navcom,conn)[0]
    conn.rollback()
    conn.execute('CREATE TEMP TABLE private_view(value)')
    assert navigation._atlas_entry(navcom,conn)[0] is not navigation._atlas_entry(navcom,conn)[0]
    assert not navigation._ATLAS_POOL
    memory.close();conn.close()


def test_pool_is_bounded_and_replaced_index_does_not_reuse_old_metadata(navcom,tmp_path):
    db=tmp_path/'index.sqlite';conn=navcom.open_index(db)
    conn.execute('PRAGMA journal_mode=DELETE');conn.close()
    conn=navigation.conversation_connection(db)
    previous=navigation._atlas_entry(navcom,conn)[0]
    conn.close()
    replacement=tmp_path/'replacement.sqlite';fresh=navcom.open_index(replacement)
    fresh.execute('PRAGMA journal_mode=DELETE');fresh.close()
    os.replace(replacement,db)
    conn=navigation.conversation_connection(db)
    assert navigation._atlas_entry(navcom,conn)[0] is not previous
    conn.close()
    for i in range(6):
        conn=navcom.open_index(tmp_path/f'{i}.sqlite')
        conn.close();conn=navigation.conversation_connection(tmp_path/f'{i}.sqlite')
        navigation._atlas_entry(navcom,conn);conn.close()
    assert len(navigation._ATLAS_POOL)==navigation._ATLAS_POOL_LIMIT==4


@pytest.mark.parametrize('known_open',[False,True])
def test_web_old_handle_after_replacement_cannot_seed_new_database_catalog(navcom,tmp_path,monkeypatch,known_open):
    from navcom_web import WebApp
    db=tmp_path/'index.sqlite';setup=navcom.open_index(db)
    key=add(navcom,setup,tmp_path/'one.jsonl','Old amber','original','/work/Orchard')
    setup.execute('UPDATE file_meta SET title=NULL');setup.commit()
    setup.execute('PRAGMA journal_mode=DELETE');setup.close()
    cache=chart(tmp_path,navcom,['/work/Orchard'])
    monkeypatch.setenv('NAVCOM_SPACE_CACHE',str(cache))
    monkeypatch.setenv('NAVCOM_SOURCES_CACHE',str(tmp_path/'sources'))
    app=WebApp(navcom,db)
    old=app.connect() if known_open else sqlite3.connect(db)
    replacement=tmp_path/'replacement.sqlite';changed=sqlite3.connect(replacement)
    old.backup(changed)
    changed.execute('UPDATE session_fts SET text=?',('New cobalt replacement',));changed.commit();changed.close()
    os.replace(replacement,db)
    try:
        first=app.get(old,'/api/navigate',{'q':['find amber'],'local':['0']})
        assert first['evidence']['conversations'][0]['label']=='Old amber original'
        assert not navigation._ATLAS_POOL
        new=app.connect()
        try:
            second=app.get(new,'/api/navigate',{'q':['find cobalt'],'local':['0']})
            assert not second['evidence']['errors']
            assert second['evidence']['conversations'][0]['label']=='New cobalt replacement'
            assert next(iter(navigation._ATLAS_POOL.values()))[0].records[key]['title']=='New cobalt replacement'
        finally:new.close()
    finally:old.close()


def test_fleet_input_and_expiry_refresh_existing_catalog(navcom,tmp_path,monkeypatch):
    root=tmp_path/'starship';(root/'bridge').mkdir(parents=True)
    path=root/'bridge/data.json'
    path.write_text(json.dumps(dict(generated='old',ships=[])))
    monkeypatch.setenv('NAVCOM_STARSHIP_ROOT',str(root))
    conn=navcom.open_index(tmp_path/'index.sqlite')
    key=add(navcom,conn,tmp_path/'a.jsonl','Amber','amber','/work/Orchard')
    atlas=Atlas(navcom);first=atlas.catalog(conn)
    path.write_text(json.dumps(dict(generated='new',ships=[dict(name='Orchard vessel',sources=['/work/Orchard'])])))
    second=atlas.catalog(conn)
    assert second is not first and second[key]['fleet']=='Orchard vessel' and atlas.fleet_date=='new'
    assert atlas.catalog(conn) is second
    atlas.built-=121
    assert atlas.catalog(conn) is not second
    conn.close()


@pytest.mark.parametrize('zone',['UTC','America/New_York','Pacific/Kiritimati'])
def test_month_labels_preserve_local_boundaries_and_undated(zone,monkeypatch):
    old=os.environ.get('TZ')
    try:
        monkeypatch.setenv('TZ',zone);time.tzset()
        for stamp in [None,0,1709251199,1709251200,1730611800,1730615400,-1]:
            expected=time.strftime('%Y-%m',time.localtime(stamp)) if stamp else 'Undated'
            assert navcom_atlas._month(stamp)==expected
    finally:
        if old is None:os.environ.pop('TZ',None)
        else:os.environ['TZ']=old
        time.tzset()
