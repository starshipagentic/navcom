"""Shared scopes, portable CLI output and evidence-based discovery."""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from navcom_discovery import Discovery, refresh
from navcom_web import WebApp
from test_atlas import add

ROOT=Path(__file__).resolve().parent.parent


def fixture(navcom,tmp_path,monkeypatch):
    monkeypatch.setattr(navcom,'INDEX_READ_ONLY',False)
    c=navcom.open_index(tmp_path/'index.sqlite')
    parent=add(navcom,c,tmp_path/'main.jsonl','Main experiment','model benchmark v4 listener','/dev/new-research')
    child=add(navcom,c,tmp_path/'child.jsonl','Child task','uniqueword zebracorn','/dev/new-research/worktree',parent='main')
    other=add(navcom,c,tmp_path/'other.jsonl','Other work','model benchmark v9 zebracorn','/dev/another-lab')
    return c,parent,child,other,Discovery(navcom)


def test_suggestions_refresh_incrementally(navcom,tmp_path,monkeypatch):
    c,parent,child,other,d=fixture(navcom,tmp_path,monkeypatch)
    before=d.view(c,{'grouping':['research']});assert not before['nodes'] and not before['freshness']['fresh']
    assert refresh(c)['changed']==3
    assert refresh(c)['changed']==0
    result=d.view(c,{'grouping':['research']});assert len(result['nodes'])==2
    family=next(n for n in result['nodes'] if '/dev/new-research' in n['project_names'])
    assert 'Suggested' in family['reason'] and family['excerpt']
    branches=d.view(c,{'within':[family['collection']],'action':['explore']})
    v4=next(n for n in branches['nodes'] if n['label']=='v4')
    assert v4['reason']=='Version mention' and 'v4' in v4['excerpt']
    assert d.view(c,{'within':[v4['collection']],'action':['explore']})['nodes'][0]['key']==parent
    assert not c.in_transaction
    c.close()


def test_scoped_search_parent_context_and_api_parity(navcom,tmp_path,monkeypatch):
    c,parent,child,other,d=fixture(navcom,tmp_path,monkeypatch)
    groups=d.view(c,{'grouping':['projects']})
    scope=next(n['collection'] for n in groups['nodes'] if n['label']=='/dev/new-research/worktree')
    params={'action':['search'],'within':[scope],'q':['zebracorn']}
    r=d.view(c,params)
    assert r['matches']==1 and r['nodes'][0]['key']==parent
    assert r['nodes'][0]['open_key']==child
    assert r['nodes'][0]['matching_children'][0]['ref']=='child'
    assert r['nodes'][0]['matching_children'][0]['key']==child
    assert r['nodes'][0]['matching_children'][0]['start']==1
    web=WebApp(navcom,tmp_path/'index.sqlite').get(c,'/api/atlas',params)
    assert r==web
    expanded=d.view(c,dict(params,children=['1']))
    assert expanded['nodes'][0]['key']==child
    assert expanded['nodes'][0]['parent_key']==parent
    # Regrouping stays scoped instead of returning unrelated projects.
    regroup=d.view(c,dict(params,action=['list'],grouping=['districts']))
    assert len(regroup['nodes'])==1 and regroup['nodes'][0]['count']==1
    tree=d.view(c,{'action':['tree'],'ref':['child']})
    assert [(n['key'],n['depth']) for n in tree['nodes']]==[(parent,0),(child,1)]
    c.close()


def test_matching_children_open_actual_matched_turns_in_stable_order(navcom,tmp_path,monkeypatch):
    c,parent,child,other,d=fixture(navcom,tmp_path,monkeypatch)
    second=add(navcom,c,tmp_path/'second.jsonl','Second task','unrelated opening','/dev/new-research',parent='main')
    with open(second,'a') as handle:
        handle.write(json.dumps(dict(type='response_item',payload=dict(type='message',role='assistant',
            content=[dict(type='output_text',text='zebracorn located in the second turn')])) )+'\n')
    navcom.index_logs(c,[(second,1700000001,Path(second).stat().st_size,'codex')],force=True,progress=False)
    params={'action':['search'],'q':['zebracorn']}
    node=next(n for n in d.view(c,params)['nodes'] if n['key']==parent)
    children={n['key']:n for n in node['matching_children']}
    assert children[child]['start']==1 and children[second]['start']==2
    assert next(n for n in node['matching_children'] if n['key']==node['open_key'])==node['matching_children'][0]
    assert node['matching_children']==next(n for n in d.view(c,params)['nodes'] if n['key']==parent)['matching_children']
    c.close()


def test_help_does_not_touch_index_and_json_is_clean(tmp_path):
    index=tmp_path/'missing.sqlite'
    for args in [['--help'],['help','atlas'],['atlas','help','districts'],['atlas','search','--help']]:
        p=subprocess.run([sys.executable,str(ROOT/'navcom.py'),*args],env={'NAVCOM_INDEX':str(index),'HOME':str(tmp_path),'PATH':'/usr/bin:/bin'},capture_output=True,text=True)
        assert p.returncode==0,p.stderr
        assert 'navcom' in p.stdout
        assert not index.exists()


def test_cli_json_and_no_database_writer(navcom,tmp_path,monkeypatch):
    c,parent,child,other,d=fixture(navcom,tmp_path,monkeypatch)
    writer=sqlite3.connect(tmp_path/'index.sqlite');writer.execute('BEGIN IMMEDIATE')
    try:
        p=subprocess.run([sys.executable,str(ROOT/'navcom.py'),'atlas','search','zebracorn','--json','--index',str(tmp_path/'index.sqlite')],capture_output=True,text=True)
        assert p.returncode==0,p.stderr
        r=json.loads(p.stdout);assert r['schema_version']==1 and r['matches']==2
        assert 'stale' in p.stderr
    finally:writer.rollback();writer.close();c.close()


def test_scope_intersections_filters_pages_and_copied_commands(navcom,tmp_path,monkeypatch):
    import shlex
    c,parent,child,other,d=fixture(navcom,tmp_path,monkeypatch)
    refresh(c)
    projects=d.view(c,{'grouping':['projects']})
    scope=next(n['collection'] for n in projects['nodes'] if n['label']=='/dev/new-research')
    regroup=d.view(c,{'action':['list'],'grouping':['topics'],'within':[scope]})
    nested=regroup['nodes'][0]['collection']
    assert '+' in nested
    narrowed=d.view(c,{'action':['search'],'within':[nested],'q':['model']})
    assert [n['key'] for n in narrowed['nodes']]==[parent]
    empty=d.view(c,{'action':['search'],'within':[scope],'q':['zebracorn']})
    assert empty['nodes']==[]
    filtered=d.view(c,{'action':['list'],'grouping':['projects'],'since':['2030-01-01']})
    assert not filtered['nodes']
    data=d.view(c,{'action':['list'],'grouping':['projects'],'limit':['1'],'offset':['1']})
    args=shlex.split(data['cli_command'])[1:]+['--json']
    p=subprocess.run([sys.executable,str(ROOT/'navcom.py'),*args],capture_output=True,text=True)
    assert p.returncode==0,p.stderr
    replay=json.loads(p.stdout)
    assert replay['nodes']==data['nodes'] and replay['effective_scope']==data['effective_scope']
    c.close()


def test_help_and_command_errors_are_explanatory(tmp_path):
    commands=[['atlas','help',g] for g in ['topics','research','projects','districts','time','starships','ancestry']]
    commands += [['atlas',g,'--help'] for g in ['list','explore','search','show','tree','refresh']]
    commands += [['help',g] for g in ['search','read','resume','atlas','maintenance','all']]
    for args in commands:
        p=subprocess.run([sys.executable,str(ROOT/'navcom.py'),*args],capture_output=True,text=True)
        assert p.returncode==0 and p.stdout.strip(),(args,p.stderr)
    p=subprocess.run([sys.executable,str(ROOT/'navcom.py'),'atlas','unknown'],capture_output=True,text=True)
    assert p.returncode==2 and 'invalid choice' in p.stderr


def test_missing_parent_and_changed_cache(navcom,tmp_path,monkeypatch):
    c,parent,child,other,d=fixture(navcom,tmp_path,monkeypatch)
    orphan=add(navcom,c,tmp_path/'orphan.jsonl','Orphan','orphanword','/dev/missing',parent='unindexed')
    refresh(c)
    r=d.view(c,{'action':['search'],'q':['orphanword']})
    assert r['nodes'][0]['key']==orphan and 'parent not indexed' in r['nodes'][0]['reason']
    c.execute('UPDATE file_state SET size=size+1 WHERE file=?',(parent,));c.commit()
    assert not d.view(c,{})['freshness']['fresh']
    assert refresh(c)['changed']==1
    assert d.view(c,{})['freshness']['fresh']
    c.close()


def test_show_exact_turn_and_invalid_scopes(navcom,tmp_path,monkeypatch):
    import pytest,shlex
    c,parent,child,other,d=fixture(navcom,tmp_path,monkeypatch)
    result=d.view(c,{'action':['show'],'ref':['main'],'start':['1']})
    assert result['nodes'][0]['start']==1 and 'benchmark' in result['nodes'][0]['excerpt']
    args=shlex.split(result['cli_command'])[1:]+['--json']
    p=subprocess.run([sys.executable,str(ROOT/'navcom.py'),*args],capture_output=True,text=True)
    assert p.returncode==0,p.stderr
    assert json.loads(p.stdout)['nodes'][0]['key']==parent
    with pytest.raises(ValueError,match='Unknown collection'):d.view(c,{'within':['research:not-present']})
    with pytest.raises(ValueError,match='Unknown atlas lens'):d.view(c,{'lens':['invalid']})
    with pytest.raises(ValueError,match='between'):d.view(c,{'limit':['0']})
    c.close()


def test_named_lab_ranks_ahead_of_other_labs_discussing_it(navcom,tmp_path,monkeypatch):
    c,parent,child,other,d=fixture(navcom,tmp_path,monkeypatch)
    named=add(navcom,c,tmp_path/'exp30-main.jsonl','Training data','listener model blend','/dev/exp30-cbt-mlx')
    add(navcom,c,tmp_path/'exp29-main.jsonl','exp30 listener trained small model','exp30 listener trained small model','/dev/exp29-cbt')
    params={'action':['search'],'lens':['project'],'q':['that exp 30 listener with the trained small model']}
    r=d.view(c,params)
    assert r['nodes'][0]['key']==named
    research=d.view(c,dict(params,action=['list'],lens=['research'],research=['0']))
    assert [n['collection'] for n in research['nodes']]==['research:exp30']
    c.close()


def test_untitled_matrix_results_use_evidence_labels(navcom,tmp_path,monkeypatch):
    monkeypatch.setattr(navcom,'INDEX_READ_ONLY',False)
    c=navcom.open_index(tmp_path/'index.sqlite')
    a=add(navcom,c,tmp_path/'rotation.jsonl','Untitled conversation',
          'Completed matrix [rotation-02/GRID.md](/private/long/path/GRID.md). Frozen 36 cases.',
          '/dev/exp32-hybrid-jev-cbt')
    b=add(navcom,c,tmp_path/'expansion.jsonl','Unknown conversation',
          'Saved matrix expansion-03 everyday and idiom rows.', '/dev/exp32-hybrid-jev-cbt')
    d=Discovery(navcom)
    r=d.view(c,{'action':['search'],'within':['research:exp32'],'q':['matrix']})
    assert len(r['nodes'])==2
    labels={n['label'] for n in r['nodes']}
    assert len(labels)==2
    assert all('matrix' in label and 'conversation' not in label for label in labels)
    assert any('rotation-02/GRID.md' in label for label in labels)
    assert all('/private/' not in label for label in labels)
    assert all(n['label_basis']=='Indexed passage' for n in r['nodes'])
    assert {n['open_key'] for n in r['nodes']}=={a,b}
    assert WebApp(navcom,tmp_path/'index.sqlite').get(c,'/api/atlas',
        {'action':['search'],'within':['research:exp32'],'q':['matrix']})['nodes']==r['nodes']
    c.close()


def test_equal_child_matches_keep_order_across_fresh_cli_processes(navcom,tmp_path,monkeypatch):
    import os
    c,parent,child,other,d=fixture(navcom,tmp_path,monkeypatch)
    left=add(navcom,c,tmp_path/'left.jsonl','Same task','quartzneedle identical text','/dev/new-research',parent='main')
    right=add(navcom,c,tmp_path/'right.jsonl','Same task','quartzneedle identical text','/dev/new-research',parent='main')
    c.close()
    orders=[]
    for seed in ('1','2','5'):
        result=subprocess.run([sys.executable,str(ROOT/'navcom.py'),'atlas','search','quartzneedle','--json',
            '--index',str(tmp_path/'index.sqlite')],env=dict(os.environ,PYTHONHASHSEED=seed),capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        node=json.loads(result.stdout)['nodes'][0]
        orders.append((node['open_key'],[ch['key'] for ch in node['matching_children']]))
    assert orders==[(right,[right,left])]*3
