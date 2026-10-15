import json
import sqlite3
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from navcom_atlas import Atlas, classify


def add(navcom,conn,path,title,text,project,stamp=1700000000,parent=None):
    payload={'id':path.stem,'cwd':project}
    if parent:payload['parent_thread_id']=parent
    path.write_text(json.dumps({'type':'session_meta','payload':payload})+'\n'+json.dumps({'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':title+' '+text}]}})+'\n')
    navcom.index_logs(conn,[(str(path),stamp,path.stat().st_size,'codex')],progress=False)
    conn.execute('INSERT OR REPLACE INTO file_meta VALUES (?,?,?,?)',(str(path),'codex',project,title));conn.commit()
    return str(path)


def test_all_indexed_not_only_recent_and_no_writes(navcom,tmp_path,monkeypatch):
    monkeypatch.setattr(navcom,'INDEX_READ_ONLY',False)
    db=tmp_path/'index.sqlite';c=navcom.open_index(db)
    old=add(navcom,c,tmp_path/'old.jsonl','Voice recovery','microphone latency','/dev/audio')
    new=add(navcom,c,tmp_path/'new.jsonl','Database work','zebracorn rollback','/dev/store')
    Path(old).unlink()  # archived/offline conversations still belong in the atlas
    writer=sqlite3.connect(db);writer.execute('BEGIN IMMEDIATE')
    try:
        a=Atlas(navcom);result=a.view(c,{})
        assert result['indexed']==2
        assert not c.in_transaction
        topics={n['label'] for n in result['nodes']}
        assert 'Voice & media' in topics
        query=a.view(c,{'q':['show me where we discussed zebracorn']})
        assert query['matches']==1
        projects=a.view(c,{'q':['zebracorn'],'lens':['project']})
        assert projects['nodes'][0]['label']=='/dev/store'
        sessions=a.view(c,{'q':['zebracorn'],'lens':['project'],'group':['/dev/store']})
        assert sessions['nodes'][0]['key']==new
        assert sessions['nodes'][0]['start']==1
        assert 'indexed transcript' in sessions['nodes'][0]['reason'].lower()
    finally:writer.rollback();writer.close();c.close()


def test_atlas_pages_every_conversation_and_updates_annotations(navcom,tmp_path,monkeypatch):
    monkeypatch.setattr(navcom,'INDEX_READ_ONLY',False)
    c=navcom.open_index(tmp_path/'index.sqlite')
    keys=[add(navcom,c,tmp_path/f'{i}.jsonl',f'Voice feature {i}','speech synthesis','/dev/audio') for i in range(24)]
    a=Atlas(navcom);params={'lens':['project'],'group':['/dev/audio']}
    first=a.view(c,params);second=a.view(c,dict(params,offset=['12']))
    assert first['more'] and not second['more']
    assert {n['key'] for n in first['nodes']+second['nodes']}==set(keys)
    navcom._ui_write(c,'annotations',{keys[0]:{'favorite':True,'name':'My spaceship'}})
    favorite=a.view(c,dict(params,favorites=['1']))
    assert len(favorite['nodes'])==1 and favorite['nodes'][0]['label']=='My spaceship'
    assert not c.in_transaction
    c.close()


def test_actual_child_and_parent_connections(navcom,tmp_path,monkeypatch):
    monkeypatch.setattr(navcom,'INDEX_READ_ONLY',False)
    c=navcom.open_index(tmp_path/'index.sqlite')
    sid='01a126c8-331b-7aa2-8783-d9ff30c38f32'
    parent=add(navcom,c,tmp_path/f'{sid}.jsonl','Build a terminal','parent','/dev/navcom')
    child=add(navcom,c,tmp_path/'01a1320b-bf55-73f1-adb1-c82ca8f1ab69.jsonl','Child task','child','/dev/other-worktree',parent=sid)
    a=Atlas(navcom)
    p=a.view(c,{'key':[parent]});ch=a.view(c,{'key':[child]})
    assert p['nodes'][0]['reason']=='Child conversation'
    assert ch['nodes'][0]['reason']=='Parent conversation'
    c.close()


def test_optional_starship_mapping(navcom,tmp_path,monkeypatch):
    monkeypatch.setattr(navcom,'INDEX_READ_ONLY',False)
    root=tmp_path/'starship';(root/'bridge').mkdir(parents=True)
    (root/'bridge/data.json').write_text(json.dumps({'generated':'2026-10-12','ships':[{'name':'Media voyage','sources':['/dev/media']}]}))
    monkeypatch.setenv('NAVCOM_STARSHIP_ROOT',str(root))
    c=navcom.open_index(tmp_path/'index.sqlite')
    add(navcom,c,tmp_path/'a.jsonl','Video rendering','','/dev/media/worker')
    add(navcom,c,tmp_path/'b.jsonl','Other','','/dev/mediator')
    a=Atlas(navcom);result=a.view(c,{'lens':['fleet']})
    assert {n['label'] for n in result['nodes']}=={'Media voyage','Unlinked projects'}
    assert result['fleet_snapshot']=='2026-10-12'
    c.close()


def test_concept_search_prefers_all_query_terms(navcom,tmp_path,monkeypatch):
    monkeypatch.setattr(navcom,'INDEX_READ_ONLY',False)
    c=navcom.open_index(tmp_path/'index.sqlite')
    exact=add(navcom,c,tmp_path/'exact.jsonl','Investigate responsiveness','The voice latency problem is fixed','/dev/media')
    add(navcom,c,tmp_path/'loose.jsonl','Voice audio speech','Voice generation settings','/dev/media',stamp=1800000000)
    a=Atlas(navcom)
    r=a.view(c,{'q':['where were we fixing voice latency'],'lens':['project'],'group':['/dev/media']})
    assert r['nodes'][0]['key']==exact
    assert 'All search terms' in r['nodes'][0]['reason']
    c.close()
