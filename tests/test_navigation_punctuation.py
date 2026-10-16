"""Speech punctuation is command syntax without rewriting literal content."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from navcom_navigation_intent import interpret
from test_navigation_aliases import chart,add_district_clue


@pytest.mark.parametrize('text',[
    'Fly to experiment 47, then find matrix.',
    'Take me to experiment 47, and search for matrix!',
    'Open experiment 47,then search matrix?',
    'Fly to experiment 47 , then find matrix .',
    'Fly to experiment 47 then find matrix.',
])
def test_spoken_clause_punctuation_is_syntax(text):
    result=interpret(text,'system:orchard')
    assert result['scope_query']=='experiment 47'
    assert result['query']=='matrix' and result['navigate_first']
    assert result['within']=='system:orchard' and result['action']=='search'


@pytest.mark.parametrize('text,action,query',[
    ('Back.','back',''),('Go back!','back',''),('Home?','home',''),
    ('Fly to Orchard.','navigate','Orchard'),('Open exp47-sensors!','navigate','exp47-sensors'),
    ('Find matrix.','search','matrix'),('Search for login policy?','search','login policy'),
])
def test_terminal_punctuation_on_plain_commands(text,action,query):
    result=interpret(text,'')
    assert result['action']==action and result['query']==query


@pytest.mark.parametrize('phrase',[
    '"matrix."',"'matrix!'",'`record.value`.',
    'src/matrix.py.','./matrix.','https://example.test/path?x=1.',
    'record.value.','VALUE_NAME.','a += 1.','matrix...','matrix.*',
    'matrix, policy.','matrix; policy.',
])
def test_explicit_literal_code_paths_and_non_sentence_punctuation_stay_exact(phrase):
    result=interpret('find '+phrase,'planet:one')
    assert result['query']==phrase and 'scope_query' not in result
    assert result['retrieval_style']=='literal'


def test_question_and_interior_clause_punctuation_are_not_rewritten():
    question='Where is the matrix?'
    assert interpret(question,'')['query']==question
    scoped=interpret('find matrix. in experiment 47.','')
    assert scoped['scope_query']=='experiment 47' and scoped['query']=='matrix.'
    travel=interpret('fly to Smith, Jones then find matrix.','')
    assert travel['scope_query']=='Smith, Jones' and travel['query']=='matrix'
    quoted=interpret('find "matrix in experiment 47."','')
    assert 'scope_query' not in quoted and quoted['query']=='"matrix in experiment 47."'


@pytest.mark.parametrize('ambiguous',[False,True])
def test_public_cli_spoken_compound_punctuation_resolves_or_preserves_choices(tmp_path,ambiguous):
    cache=chart(tmp_path,ambiguous=ambiguous)
    add_district_clue(cache)
    command=[sys.executable,str(Path(__file__).resolve().parents[1]/'navcom.py'),
             'atlas','navigate','Fly to experiment 47, then find matrix.',
             '--space-cache',str(cache),'--source-cache',str(tmp_path/'sources'),
             '--index',str(tmp_path/'absent.sqlite'),'--json']
    completed=subprocess.run(command,capture_output=True,text=True,timeout=20)
    assert completed.returncode==0,completed.stderr
    result=json.loads(completed.stdout)
    assert result['intent']['scope_query']=='experiment 47' and result['intent']['query']=='matrix'
    if ambiguous:
        assert result['scope_status']=='choose' and result['destination'] is None
        assert {node['id'] for node in result['scope_candidates']}=={'planet:experiment','planet:second-experiment'}
        assert 'evidence' not in result
    else:
        assert result['scope_status']=='resolved' and result['destination']=='planet:experiment'
        assert result['scope_target']['kind']=='moon' and result['intent']['within']=='planet:experiment'
        assert result['intent']['navigate_first'] and result['query']=='matrix'
        assert not result['evidence']['errors']
