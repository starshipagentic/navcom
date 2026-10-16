"""Question terms use native regex word boundaries without changing literal search."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which("starforge"), reason="Optional installed Starforge required")


def test_native_question_terms_exclude_substrings_and_keep_scope_and_cache(tmp_path):
    from navcom_sources import runtime
    script = r'''
import json
from pathlib import Path
import navcom_sources_worker as worker

base=Path(sys.argv[2]); root=base/'source'; scope=root/'auth'; scope.mkdir(parents=True)
(scope/'README.md').write_text('workers: 1\nnetwork adapter\nrework scheduled\nAuthentication uses passkeys.\nWork follows approval.\n')
(root/'outside.md').write_text('Authentication outside the selected scope.\n')
cache=base/'cache';source=dict(id='fixture',root=str(root),label='Aurora',include=['.'])
worker.refresh([source],cache)
pointer=(cache/'current.json').read_bytes()
request=dict(query='How does authentication work?',within='fixture',paths=['auth'],mode='both',text_mode='question_terms',limit=20)
first=worker.combined_search(request,cache)
assert first['query']==request['query']
assert first['text_terms']==['authentication','work']
assert [h['line'] for h in first['text_hits']]==[4,5]
assert all(h['relative_path']=='auth/README.md' for h in first['text_hits'])
assert all(h['source_ref']['relative_path']=='auth/README.md' for h in first['text_hits'])
assert first['harvest_invocations']==0 and not first['query_cache_hit']
again=worker.combined_search(request,cache)
assert again['query_cache_hit'] and again['text_hits']==first['text_hits']
assert (cache/'current.json').read_bytes()==pointer

# An ordinary keyword remains a substring query; an explicit regex still has
# exactly the caller's semantics. Neither opts into question decomposition.
literal=worker.combined_search(dict(request,query='work',text_mode='literal'),cache)
assert [h['line'] for h in literal['text_hits']]==[1,2,3,5]
explicit=worker.combined_search(dict(request,query='workers: [0-9]',text_mode='literal',regex=True),cache)
assert [h['line'] for h in explicit['text_hits']]==[1]
assert not literal['text_terms'] and not explicit['text_terms']

# Native decomposition preserves identifiers/hyphenated terms. Punctuation
# marks word edges, and longer words must not masquerade as those keywords.
(scope/'README.md').write_text('marmot_policy extra-check\nmarmot_policy_extra extra-checking\nMARMOT_POLICY (extra-check)\n')
worker.refresh([source],cache)
compound=worker.combined_search(dict(request,query='How do marmot_policy and extra-check work?'),cache)
assert [h['line'] for h in compound['text_hits']]==[1,3]
print(json.dumps(dict(question_lines=[h['line'] for h in first['text_hits']],literal_lines=[h['line'] for h in literal['text_hits']],compound_lines=[h['line'] for h in compound['text_hits']],cached=again['query_cache_hit'])))
'''
    result = subprocess.run([runtime(), "-I", "-B", "-c",
        "import sys;sys.path.insert(0,sys.argv[1]);" + script,
        str(ROOT), str(tmp_path)], capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == dict(question_lines=[4, 5], literal_lines=[1, 2, 3, 5],
                                            compound_lines=[1, 3], cached=True)
