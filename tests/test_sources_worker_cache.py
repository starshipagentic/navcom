"""Native Starforge staging IO and failure completeness, without replacement algorithms."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which("starforge"), reason="Optional installed Starforge required")


def native(script, tmp_path, *args):
    from navcom_sources import runtime
    result = subprocess.run([runtime(), "-I", "-B", "-c",
        "import sys; sys.path.insert(0,sys.argv[1]); " + script,
        str(ROOT), str(tmp_path), *args], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_search_and_harvest_fingerprints_invalidate_only_their_own_work(tmp_path):
    result = native('''
import json
from pathlib import Path
import navcom_sources_worker as worker
base=Path(sys.argv[2]); root=base/'source'; root.mkdir(); cache=base/'cache'
(root/'README.md').write_text('# Marmot protocol\\nA retained document.\\n')
source=dict(id='fixture',root=str(root),label='sensor',include=['.'])
module=base/'worker-copy.py'; module.write_text(Path(worker.__file__).read_text())
worker.__file__=str(module)
request=dict(query='Marmot',within='fixture',mode='both')
first=worker.refresh([source],cache)
harvest_key=worker.extractor_signature(); query_key=worker.query_signature()
assert worker.combined_search(request,cache,extractor='fixed-caller-namespace')['text_hits']
assert worker.combined_search(request,cache,extractor='fixed-caller-namespace')['query_cache_hit']
pointer=(cache/'current.json').read_bytes()

# A real retrieval/DTO edit changes its query memo, not source analysis.
before=module.read_text()
after=before.replace('Search hit has an invalid source line','Search hit line is invalid')
assert after!=before; module.write_text(after)
assert worker.extractor_signature()==harvest_key
assert worker.query_signature()!=query_key
unchanged=worker.refresh([source],cache)
assert unchanged['analyzed_sources']==0 and unchanged['cached_sources']==1
assert (cache/'current.json').read_bytes()==pointer
assert not worker.combined_search(request,cache,extractor='fixed-caller-namespace')['query_cache_hit']
assert worker.combined_search(request,cache,extractor='fixed-caller-namespace')['query_cache_hit']

# An ingestion budget/default change is part of harvest identity, even when
# this small fixture does not hit the limit; it must reanalyze on refresh.
query_key=worker.query_signature()
before=module.read_text(); after=before.replace('source.get("max_files", 10000)','source.get("max_files", 10001)')
assert after!=before; module.write_text(after)
assert worker.extractor_signature()!=harvest_key
assert worker.query_signature()==query_key
changed=worker.refresh([source],cache)
assert changed['analyzed_sources']==1
assert worker.refresh([source],cache)['analyzed_sources']==0

# Installed native dependency changes invalidate both paths conservatively.
native=base/'native'/'starforge'; native.mkdir(parents=True)
(native/'dependency.py').write_text('VERSION = 1\\n'); worker.SF=native.parent
keys=(worker.extractor_signature(),worker.query_signature())
(native/'dependency.py').write_text('VERSION = 2\\n')
assert keys[0]!=worker.extractor_signature() and keys[1]!=worker.query_signature()
print(json.dumps(dict(first=first,search_only=unchanged,harvest_change=changed)))
''', tmp_path)
    assert result['first']['analyzed_sources'] == 1
    assert result['search_only']['analyzed_sources'] == 0
    assert result['harvest_change']['analyzed_sources'] == 1


def test_cached_hit_pins_use_one_search_generation_and_reject_wrong_identity(tmp_path):
    result = native('''
import copy,json
from pathlib import Path
import navcom_sources_worker as worker
base=Path(sys.argv[2]); root=base/'source'; root.mkdir(); cache=base/'cache'
(root/'README.md').write_text('# Marmot protocol\\nExact retained evidence.\\n')
source=dict(id='fixture',root=str(root),label='sensor',include=['.'])
worker.refresh([source],cache)
state=worker.read(cache/'current.json')
request=dict(query='Marmot',within='fixture',mode='both')
first=worker.combined_search(request,cache,state=state)
ref=first['text_hits'][0]['source_ref']
assert ref==dict(source_id='fixture',relative_path='README.md',line=1,
                snapshot=Path(state['sources'][0]['artifact']).name,published=state['published'])
memo=next((cache/'queries').glob('*.json'))
legacy=worker.read(memo)
for hit in legacy['text_hits']:hit.pop('source_ref')
worker.write(memo,legacy)
# A concurrent publication does not change a search's already loaded generation.
worker.write(cache/'current.json',dict(state,published=state['published']+10))
cached=worker.combined_search(request,cache,state=state)
assert cached['query_cache_hit'] and cached['text_hits'][0]['source_ref']==ref
errors=[]
for changes in ({'source_id':'missing'}, {'relative_path':'../escape'},
                {'relative_path':'other.md'}, {'line':0},
                {'source_ref':dict(ref,snapshot='f'*64)}):
    bad=copy.deepcopy(legacy);bad['text_hits'][0].update(changes)
    worker.write(memo,bad)
    try:worker.combined_search(request,cache,state=state)
    except ValueError as error:errors.append(str(error))
    else:raise AssertionError('invalid cached source identity was guessed')
print(json.dumps(dict(reference=ref,rejected=len(errors))))
''', tmp_path)
    assert result['reference']['relative_path'] == 'README.md'
    assert result['rejected'] == 5


def test_legacy_fingerprint_rolls_forward_only_on_selected_refresh(tmp_path):
    result = native('''
import json
from pathlib import Path
import navcom_sources_worker as worker
from navcom_source_reader import read_source
base=Path(sys.argv[2]); root=base/'source'; root.mkdir(); cache=base/'cache'
(root/'README.md').write_text('# Marmot protocol\\nRetained before migration.\\n')
source=dict(id='fixture',root=str(root),label='sensor',include=['.'])
current_signature=worker.extractor_signature
legacy_files=sorted((worker.SF/'starforge').glob('*.py'))+[Path(worker.__file__)]
legacy=worker.digest(b''.join(str(path).encode()+path.read_bytes() for path in legacy_files))
worker.extractor_signature=lambda:legacy
worker.refresh([source],cache)
before=worker.read(cache/'current.json'); pointer=(cache/'current.json').read_bytes()
worker.extractor_signature=current_signature
assert current_signature()!=legacy
found=worker.combined_search(dict(query='Marmot',mode='text'),cache)
ref=found['text_hits'][0]['source_ref']
assert read_source('fixture','README.md',snapshot=ref['snapshot'],cache_path=cache)['lines']
assert (cache/'current.json').read_bytes()==pointer
rolled=worker.refresh([source],cache)
assert rolled['analyzed_sources']==1
assert Path(before['sources'][0]['artifact']).is_dir()
assert worker.refresh([source],cache)['analyzed_sources']==0
print(json.dumps(dict(legacy_read_without_refresh=True,analyzed_on_transition=rolled['analyzed_sources'])))
''', tmp_path)
    assert result == dict(legacy_read_without_refresh=True, analyzed_on_transition=1)


def test_native_catalog_is_buffered_and_fully_flushed_before_read(tmp_path):
    result = native('''
import json
from pathlib import Path
import navcom_sources_worker as worker
from tinydb.storages import JSONStorage
path = Path(sys.argv[2]) / 'catalog.json'
calls=[]
original=JSONStorage.write
def tracked(self,data):
    calls.append(1)
    return original(self,data)
JSONStorage.write=tracked
with worker.staged_catalog(path) as catalog:
    catalog.add_project('sensor','/fixture/sensor')
    for i in range(8):
        catalog.add_gem('module'+str(i),'/fixture/sensor/'+str(i)+'.py','sensor',description='native declaration')
    assert catalog.project_count()==1 and len(catalog.list_gems(limit=20))==8
    assert not calls
data=json.loads(path.read_text())
print(json.dumps(dict(writes=len(calls),projects=len(data['projects']),gems=len(data['gems']),
                     descriptions=sorted({g['description'] for g in data['gems'].values()}))))
''', tmp_path)
    assert result == dict(writes=1, projects=1, gems=8, descriptions=["native declaration"])


def test_native_application_candidates_need_runnable_manifest_and_are_bounded(tmp_path):
    result = native('''
import json
from pathlib import Path
import navcom_sources_worker as worker
root=Path(sys.argv[2])/'snapshot'; root.mkdir()
records={'apps/cedar': {'name':'Cedar','description':'Instrument viewing','scripts':{'start':'touch NEVER_EXECUTED'}},
         'apps/opal': {'name':'Opal','scripts':{'dev':'arbitrary --secret=HIDDEN_COMMAND'}},
         'packages/helper': {'name':'Helper','scripts':{'build':'tsc','test':'pytest'}},
         'examples/demo': {'name':'Demo'}}
for relative,record in records.items():
    folder=root/relative; folder.mkdir(parents=True)
    (folder/'package.json').write_text(json.dumps(record))
folder=root/'workers/spectrum'; folder.mkdir(parents=True)
(folder/'pyproject.toml').write_text('[project]\\nname="Spectrum"\\n[project.scripts]\\nspectrum="spectrum.main:main"\\n')
files=list(root.rglob('*')); files=[path for path in files if path.is_file()]
candidates,coverage=worker.source_applications(root,files)
assert not (root/'NEVER_EXECUTED').exists()
print(json.dumps(dict(candidates=candidates,coverage=coverage)))
''', tmp_path)
    assert {candidate["root"] for candidate in result["candidates"]} == {"apps/cedar", "apps/opal", "workers/spectrum"}
    assert all(candidate["status"] == "candidate" and candidate["entry_points"] for candidate in result["candidates"])
    assert "HIDDEN_COMMAND" not in json.dumps(result) and "touch NEVER_EXECUTED" not in json.dumps(result)
    assert result["coverage"]["complete"] and len(result["coverage"]["inspected"]) == 5


def test_native_manifest_root_budget_is_disclosed(tmp_path):
    result = native('''
import json
from pathlib import Path
import navcom_sources_worker as worker
root=Path(sys.argv[2])/'snapshot'; root.mkdir()
for number in range(66):
    folder=root/('app'+str(number).zfill(3)); folder.mkdir()
    (folder/'package.json').write_text(json.dumps({'name':folder.name,'scripts':{'start':'never-run'}}))
candidates,coverage=worker.source_applications(root,list(root.rglob('package.json')))
print(json.dumps(dict(count=len(candidates),coverage=coverage)))
''', tmp_path)
    assert result["count"] == 64 and not result["coverage"]["complete"]
    assert result["coverage"]["omitted"] == [
        dict(root="app064", reason="manifest-root limit"), dict(root="app065", reason="manifest-root limit")]


@pytest.mark.parametrize("failure", ["scan", "partial_store", "flush"])
def test_native_harvest_checks_single_scan_and_keeps_previous_snapshot_on_failure(tmp_path, failure):
    result = native('''
import json
from pathlib import Path
import navcom_sources_worker as worker
from tinydb.storages import JSONStorage
base=Path(sys.argv[2]); root=base/'source'; root.mkdir(); cache=base/'cache'
code='\\n'.join(['"""Marmot optical instrumentation calibration."""','def calibrate(value):']+
    ['    step_'+str(i)+' = value + '+str(i) for i in range(24)]+['    return step_23',''])
for name in ('first.py','second.py'):(root/name).write_text(code)
source=dict(id='fixture',root=str(root),label='sensor',include=['.'])
calls=[]; original_scan=worker.GemFinder.scan
def counted(self,*args,**kwargs):
    calls.append(1)
    return original_scan(self,*args,**kwargs)
worker.GemFinder.scan=counted
first=worker.refresh([source],cache)
assert first['analyzed_sources']==1 and len(calls)==1
state=json.loads((cache/'current.json').read_text())
stored=json.loads((Path(state['sources'][0]['artifact'])/'catalog.json').read_text())
assert len(stored['gems'])==2
unchanged=worker.refresh([source],cache)
assert unchanged['cached_sources']==1 and not unchanged['published'] and len(calls)==1
pointer=(cache/'current.json').read_bytes()
(root/'first.py').write_text(code+'# Changed source input\\n')
failure=sys.argv[3]
if failure=='scan':
    def fail(*args,**kwargs):raise RuntimeError('fixture native scan failure')
    worker.GemFinder.scan=fail
elif failure=='partial_store':
    add=worker.Catalog.add_gem
    def partial(self,*args,**kwargs):
        if str(kwargs.get('file_path',args[1] if len(args)>1 else '')).endswith('first.py'):return 0
        return add(self,*args,**kwargs)
    worker.Catalog.add_gem=partial
else:
    def flush_fail(*args,**kwargs):raise OSError('fixture flush failure')
    JSONStorage.write=flush_fail
try:
    worker.refresh([source],cache)
except (RuntimeError,OSError) as exc:
    error=str(exc)
else:raise AssertionError('incomplete native harvest was published')
assert (cache/'current.json').read_bytes()==pointer
print(json.dumps(dict(error=error,previous_snapshot_preserved=True,native_gems=len(stored['gems']))))
''', tmp_path, failure)
    assert result["previous_snapshot_preserved"] and result["native_gems"] == 2
    assert ("Incomplete gem harvest" if failure != "flush" else "fixture flush failure") in result["error"]
