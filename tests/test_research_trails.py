"""Discover real research lines from project identity and indexed evidence."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from navcom_atlas import Atlas
from navcom_research import family, intent, normalize_query
from test_atlas import add


def test_human_aliases_and_typos():
    assert intent('my chat bot experiemnts')==['exp29','exp30','exp32','observatory']
    assert intent('that epx32 jev attempt')==['exp32']
    assert intent('exp 29 version 34')==['exp29']
    assert intent('sematic observtory')==['observatory']
    assert family('/dev/exp291-new')==''
    assert family('/dev/capcom')==''


def setup(navcom,tmp_path,monkeypatch):
    monkeypatch.setattr(navcom,'INDEX_READ_ONLY',False)
    c=navcom.open_index(tmp_path/'index.sqlite')
    keys={}
    for lab,project,title,body in [
        ('exp29','/dev/exp29-llm-cbt','read the mission','Why does v34 combine listener signals with heads and deterministic protocol decisions? v13 was earlier.'),
        ('exp30','/dev/exp30-cbt-mlx','training data','V2 and V2.1 listener engine blends trained Ministral and MLX with ML heads.'),
        ('exp32','/dev/exp32-hybrid-jev-cbt','read readme','Compare JEV hybrid reader replacement and strength clarity arcs. Semantic Observatory begins here.'),
        ('observatory','/dev/semanticobservatory','read handoff','SSDB benchmark strength clarity and Hermes research worker.'),
        ('unrelated','/dev/capcom','migration review','copy exp29 v34 and exp32 archives')]:
        keys[lab]=add(navcom,c,tmp_path/(lab+'.jsonl'),title,body,project)
    return c,keys,Atlas(navcom)


def test_broad_search_names_four_distinct_lines(navcom,tmp_path,monkeypatch):
    c,keys,a=setup(navcom,tmp_path,monkeypatch)
    r=a.view(c,{'q':['my chatbot experiemnts']})
    assert r['lens']=='research' and r['corrected']
    assert {n['family'] for n in r['nodes']}=={'exp29','exp30','exp32','observatory'}
    assert all(n['question'] and n['approach'] and n['distinction'] for n in r['nodes'])
    assert sum(n['count'] for n in r['nodes'])==4  # CapCom only mentions them
    c.close()


def test_version_is_evidenced_and_opens_matching_turn(navcom,tmp_path,monkeypatch):
    c,keys,a=setup(navcom,tmp_path,monkeypatch)
    r=a.view(c,{'lens':['research'],'group':['exp29'],'q':['version 34']})
    assert r['nodes'][0]['branch']=='v34'
    assert {n['branch'] for n in r['nodes']}=={'all','v13','v34'}
    assert 'v33' not in {n['branch'] for n in r['nodes']}
    sessions=a.view(c,{'lens':['research'],'group':['exp29'],'branch':['v34']})
    n=sessions['nodes'][0]
    assert n['key']==keys['exp29'] and n['version']=='v34' and n['start']==1
    assert 'listener signals' in n['excerpt']
    assert 'not EXP30' in n['distinction']
    assert not c.in_transaction
    c.close()


def test_exp30_versions_and_observatory_origin_stay_separate(navcom,tmp_path,monkeypatch):
    c,keys,a=setup(navcom,tmp_path,monkeypatch)
    v=a.view(c,{'lens':['research'],'group':['exp30']})
    assert 'v2' in {n['branch'] for n in v['nodes']}
    assert 'v34' not in {n['branch'] for n in v['nodes']}
    origin=a.view(c,{'lens':['research'],'group':['exp32'],'branch':['observatory']})
    assert origin['nodes'][0]['key']==keys['exp32']
    observatory=a.view(c,{'lens':['research'],'group':['observatory']})
    assert any(n['family']=='exp32' and 'Originating' in n['reason'] for n in observatory['related'])
    # A normal unrelated search must not keep returning all four trails.
    empty=a.view(c,{'lens':['research'],'q':['unfindableplatypus']})
    assert not empty['nodes']
    c.close()


def test_filtered_counts_and_generic_escape(navcom,tmp_path,monkeypatch):
    c,keys,a=setup(navcom,tmp_path,monkeypatch)
    r=a.view(c,{'q':['exp32 jev']})
    assert r['scope']==r['matches']==1
    assert r['nodes'][0]['main_count']==1
    generic=a.view(c,{'q':['chatbot'],'research':['0']})
    assert generic['lens']=='topics' and not generic.get('research')
    c.close()
