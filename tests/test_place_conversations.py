"""A place reads all its saved conversation memberships through existing Discovery."""
import json
from datetime import datetime
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

import navcom_navigation as navigation
import navcom_space
from navcom_atlas import identity
from test_atlas import add


@pytest.fixture
def place_history(navcom, tmp_path, monkeypatch):
    monkeypatch.setattr(navcom, 'INDEX_READ_ONLY', False)
    index=tmp_path/'index.sqlite'
    conn=navcom.open_index(index)
    projects=['/work/clients/Orion/one','/work/clients/Orion/two','/work/clients/Lumen/other']
    parent_id='01a126c8-331b-7aa2-8783-d9ff30c38f32'
    parent=add(navcom,conn,tmp_path/(parent_id+'.jsonl'),'Orchard overview','amber planting',projects[0],stamp=1700000000)
    child=add(navcom,conn,tmp_path/'child.jsonl','Work item','solve2 matrix evidence',projects[1],stamp=1700000010,parent=parent_id)
    separate=add(navcom,conn,tmp_path/'separate.jsonl','Second orchard','solve2 matrix evidence',projects[1],stamp=1700000120)
    outside=add(navcom,conn,tmp_path/'outside.jsonl','Other client','solve2 matrix evidence',projects[2],stamp=1700000030)
    collections=['projects:'+identity(p) for p in projects]
    def node(id,kind,parent,cols,**extra):
        return dict(id=id,kind=kind,parent_id=parent,label=id.split(':')[-1],
                    conversation_collections=cols,source_scopes=[],source_ids=[],
                    position=dict(x=1,y=2),locations=[],evidence=[],**extra)
    nodes=[node('galaxy:owner','galaxy',None,collections),
           node('system:orchard','system','galaxy:owner',collections[:2]),
           node('planet:one','planet','system:orchard',[collections[0]]),
           node('moon:two','moon','system:orchard',[collections[1]]),
           node('district:one','district','planet:one',[collections[0]],suggested_query='amber',
                conversation_basis=dict(type='project_query_context',query='amber',relationship='unproven')),
           node('system:other','system','galaxy:owner',[collections[2]])]
    space=tmp_path/'space.json'
    space.write_text(json.dumps(dict(schema_version=1,published=123,entities=nodes,edges=[],coverage={})))
    monkeypatch.setenv('NAVCOM_SPACE_CACHE',str(space))
    monkeypatch.setenv('NAVCOM_STARSHIP_ROOT',str(tmp_path/'absent-fleet'))
    monkeypatch.setattr(navcom,'list_logs',lambda *a,**kw:pytest.fail('Conversation browse scanned raw logs'))
    yield dict(api=navcom,conn=conn,index=index,space=space,collections=collections,
               parent=parent,child=child,separate=separate,outside=outside)
    conn.close()


def read(f, **kwargs):
    return navigation.conversations(f['api'],f['conn'],space_cache=f['space'],within='system:orchard',**kwargs)


def test_place_union_paginates_all_collections_before_ancestry_grouping(place_history):
    f=place_history;before=f['space'].read_bytes();changes=f['conn'].total_changes
    first=read(f,limit=1);second=read(f,limit=1,offset=1)
    assert first['total']==second['total']==2 and first['more'] and not second['more']
    assert {n['key'] for n in first['nodes']+second['nodes']}=={f['parent'],f['separate']}
    assert first['conversation_scope']['indexed_conversations']==3
    assert first['conversation_scope']['collection_count']==2
    assert first['conversation_scope']['complete']
    assert f['space'].read_bytes()==before and f['conn'].total_changes==changes
    assert '--offset 1' in first['continue_command']


def test_query_returns_exact_child_evidence_and_recorded_parent(place_history):
    f=place_history;result=read(f,query='solve2',action='search')
    assert result['matches']==2 and result['total']==2
    parent=next(n for n in result['nodes'] if n['key']==f['parent'])
    assert parent['open_key']==f['child'] and parent['evidence_key']==f['child']
    assert parent['start']==1 and 'solve2' in parent['excerpt']
    assert parent['matching_children'][0]['key']==f['child']
    assert '--open child:1' in parent['open_command']
    assert f['outside'] not in {n['open_key'] for n in result['nodes']}
    expanded=read(f,query='solve2',action='search',children=True)
    assert {n['key'] for n in expanded['nodes']}=={f['child'],f['separate']}
    child=next(n for n in expanded['nodes'] if n['key']==f['child'])
    assert child['parent_key']==f['parent']


def test_expanded_rows_are_not_reported_as_family_count(place_history):
    grouped=read(place_history,limit=1)
    expanded=read(place_history,limit=1,children=True)
    assert grouped['matches']==expanded['matches']==3
    assert grouped['conversation_scope']['result_grouping']=='families'
    assert grouped['conversation_scope']['result_count']==grouped['conversation_scope']['matching_families']==2
    assert expanded['conversation_scope']['result_grouping']=='conversations'
    assert expanded['conversation_scope']['result_count']==3
    assert expanded['conversation_scope']['matching_families'] is None
    assert len(grouped['nodes'])==len(expanded['nodes'])==1 and expanded['more']


def test_place_filters_and_district_suggested_query_stay_exact(place_history):
    f=place_history
    f['api']._ui_write(f['conn'],'annotations',{f['separate']:{'favorite':True}})
    assert [n['key'] for n in read(f,favorites=True)['nodes']]==[f['separate']]
    assert read(f,provider='claude')['total']==0
    since=datetime.fromtimestamp(1700000060).strftime('%Y-%m-%d %H:%M')
    assert [n['key'] for n in read(f,since=since)['nodes']]==[f['separate']]
    assert read(f,until='2020-01-01')['total']==0
    local=navigation.conversations(f['api'],f['conn'],space_cache=f['space'],within='planet:one',query='solve2')
    assert local['total']==0
    district=navigation.conversations(f['api'],f['conn'],space_cache=f['space'],within='district:one')
    assert district['query']=='amber' and district['requested_query']==''
    assert district['conversation_basis']['type']=='project_query_context'
    assert [n['key'] for n in district['nodes']]==[f['parent']]
    assert district['conversation_scope']['indexed_conversations']==1


def test_missing_collection_is_disclosed_without_global_fallback(place_history):
    f=place_history;data=json.loads(f['space'].read_text())
    data['entities']=[n for n in data['entities'] if n['id'] not in ('planet:one','moon:two','district:one')]
    data['entities'][1]['conversation_collections']=['projects:missing']
    f['space'].write_text(json.dumps(data))
    result=read(f,query='solve2')
    assert result['nodes']==[]
    assert result['conversation_scope']['missing_collection_ids']==['projects:missing']
    assert result['conversation_scope']['indexed_conversations']==0
    assert not result['conversation_scope']['complete'] and result['errors']


def test_browse_uses_one_catalog_publication_and_no_source_or_model(place_history,monkeypatch):
    f=place_history;original=navcom_space.load_catalog;calls=[]
    def replace(path):
        result=original(path);calls.append(path)
        data=json.loads(f['space'].read_text());data['published']=456
        data['entities'][1]['conversation_collections']=[f['collections'][2]]
        f['space'].write_text(json.dumps(data));return result
    monkeypatch.setattr(navcom_space,'load_catalog',replace)
    monkeypatch.setattr(navigation.subprocess,'run',lambda *a,**k:pytest.fail('Source worker/model invoked'))
    result=read(f,query='solve2')
    assert len(calls)==1 and result['published']==123
    assert set(result['conversation_scope']['collection_ids'])==set(f['collections'][:2])
    assert f['outside'] not in {n['open_key'] for n in result['nodes']}


def test_public_cli_api_and_returned_commands_share_whole_place(place_history):
    from navcom_web import WebApp
    f=place_history;app=WebApp(f['api'],f['index'])
    web=app.get(f['conn'],'/api/space',dict(action=['search'],within=['system:orchard'],q=['solve2'],
                conversations=['1'],limit=['1'],children=['1']))
    command=shlex.split(web['cli_command'])
    command[:1]=[sys.executable,str(Path(__file__).resolve().parents[1]/'navcom.py')]
    proc=subprocess.run(command+['--json'],capture_output=True,text=True,check=True)
    cli=json.loads(proc.stdout)
    assert cli==web
    assert cli['more'] and cli['conversation_scope']['indexed_conversations']==3
    plain=subprocess.run(command,capture_output=True,text=True,check=True).stdout
    assert '3 indexed conversations across 2 saved collections' in plain
    shown=navigation.view(f['api'],f['conn'],space_cache=f['space'],source_cache=f['space'].parent/'sources',
                          action='show',within='system:orchard')
    commands=shown['center']['commands']
    assert len(commands['conversation_search'])==1
    assert commands['conversation_search'][0][commands['conversation_search'][0].index('--within')+1]=='system:orchard'
    for field in ('conversation_explore','conversation_search'):
        argv=commands[field][0] if field=='conversation_search' else commands[field]
        assert '--conversations' in argv and '--space-cache' in argv and '--index' in argv
    browse=commands['conversation_explore']
    out=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'navcom.py'),*browse[1:],'--json'],capture_output=True,text=True,check=True)
    assert json.loads(out.stdout)['matches']==3


def test_navigator_evidence_reuses_identical_place_memberships(place_history,monkeypatch):
    f=place_history;calls=[];original=navigation.conversations
    def traced(*args,**kwargs):
        calls.append(kwargs);return original(*args,**kwargs)
    monkeypatch.setattr(navigation,'conversations',traced)
    proof=navigation.evidence(f['api'],f['conn'],f['space'],f['space'].parent/'sources','system:orchard','solve2')
    assert len(calls)==1
    standalone=read(f,query='solve2',action='search')
    assert [(n['key'],n['open_key'],n['start']) for n in proof['conversations']]==[
        (n['key'],n['open_key'],n['start']) for n in standalone['nodes']]
    assert proof['coverage']['searched_collections']==2


@pytest.mark.parametrize('args',[dict(limit=0),dict(limit=201),dict(offset=-1),dict(action='list')])
def test_invalid_pagination_or_action_rejected(place_history,args):
    with pytest.raises(ValueError):read(place_history,**args)
