"""District display clues never alter native group identity or file scope."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import navcom_space as space


ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize('words,paths,label,basis', [
    (['(runtime/rules.py,', '(h2', '__getattr__', '_enqueue'],
     ['versions/v1/radiometry/spectrum.py', 'versions/v2/radiometry/spectrum.py'],
     'radiometry / spectrum', 'common_grouped_path'),
    (['@/data/schema', '../storage/helper', '_err'],
     ['src/recovery-options.ts', 'src/identify-triage.ts'],
     'recovery options · identify triage', 'grouped_filenames'),
    (['__getattr__', 'config'], ['transit/src/config.py', 'habitat/src/config.py'],
     'transit / src / config · habitat / src / config (2 files)', 'grouped_file_paths'),
    (['read', 'write'], ['auth/client.py', 'storage/client.py'],
     'auth / client · storage / client (2 files)', 'grouped_file_paths'),
    (['grant', 'policy', 'role'], ['src/lib/auth/role-grant-policy.ts', 'src/lib/auth/role-grant-policy.test.ts'],
     'auth / role grant policy', 'common_grouped_path'),
    (['authorization', 'policy'], ['auth/login.ts', 'auth/policy.ts'],
     'policy · authorization', 'native_shared_tokens'),
])
def test_labels_use_literal_native_paths_or_clean_evidence(words,paths,label,basis):
    original_words=list(words);original_paths=list(paths)
    actual,actual_basis,_=space._district_label(words,paths)
    assert (actual,actual_basis)==(label,basis)
    assert words==original_words and paths==original_paths


def test_public_cli_relabels_same_district_without_moving_or_regrouping(tmp_path,monkeypatch):
    project=tmp_path/'clients'/'Vela'/'observing-suite';project.mkdir(parents=True)
    subprocess.run(['git','init','-q',str(project)],check=True)
    paths=['versions/v1/radiometry/spectrum.py','versions/v2/radiometry/spectrum.py']
    words=['(runtime/rules.py,','(h2','__getattr__','_enqueue']
    group=dict(paths=paths,shared_tokens=words,cohesion=.8,size=2)
    sources=tmp_path/'sources';artifact=sources/'artifacts'/'published';artifact.mkdir(parents=True)
    (artifact/'structure.json').write_text(json.dumps(dict(token_groups=[group])))
    (sources/'current.json').write_text(json.dumps(dict(published=1234,sources=[dict(
        id='native-source',root=str(project),artifact=str(artifact),include=['.'])])))
    cache=tmp_path/'space.json'
    monkeypatch.setenv('NAVCOM_STARSHIP_ROOT',str(tmp_path/'no-fleet'))
    monkeypatch.setenv('HERMES_HOME',str(tmp_path/'no-profiles'))
    monkeypatch.delenv('NAVCOM_FLEET_CONFIG',raising=False)
    monkeypatch.delenv('NAVCOM_FLEET_SNAPSHOT',raising=False)
    # Simulate a previously published heading while keeping the real native
    # group identity, membership and normal refresh pipeline unchanged.
    original=space._district_label
    monkeypatch.setattr(space,'_district_label',lambda *_:('(h2 · __getattr__','native_shared_tokens',['__getattr__']))
    before=space.refresh(object(),None,cache,source_cache=sources)
    monkeypatch.setattr(space,'_district_label',original)
    previous=next(n for n in before['entities'] if n['kind']=='district')
    def cli(*args):
        result=subprocess.run([sys.executable,str(ROOT/'navcom.py'),'atlas',*args,
            '--index',str(tmp_path/'no-index.sqlite'),'--space-cache',str(cache),
            '--source-cache',str(sources),'--json'],capture_output=True,text=True,env=dict(os.environ),check=True)
        return json.loads(result.stdout)
    refreshed=cli('refresh','--space')
    current=next(n for n in refreshed['entities'] if n['id']==previous['id'])
    assert current['label']=='radiometry / spectrum'
    assert current['label_basis']=='common_grouped_path'
    for key in ('id','parent_id','position','source_scopes','source_ids','evidence'):
        assert current[key]==previous[key]
    shown=cli('show',current['id'])['center']
    assert shown['evidence'][0]['paths']==paths
    assert shown['evidence'][0]['shared_tokens']==words
    assert paths[0] in shown['description']
    matches=cli('search','__getattr__','--space','--within',current['parent_id'])
    assert current['id'] in {n['id'] for n in matches['nodes']}
    assert cli('list','cities','--within',current['parent_id'])['nodes'][0]['label']=='radiometry / spectrum'
