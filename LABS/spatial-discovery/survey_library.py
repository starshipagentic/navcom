"""Test unchanged Starforge implementations on bounded local source and controls."""
import collections, hashlib, importlib.util, json, os, subprocess, sys, time
from pathlib import Path
sys.dont_write_bytecode=True
SF=Path.home()/'dev/starforge/src';sys.path.insert(0,str(SF))
from starforge.similarity import find_token_groups
from starforge.lineage import LineageDetector
from starforge.import_graph import analyze_repo
from starforge.ancestry import find_ancestors
from starforge.paradigm import detect_paradigm
from starforge.api_endpoints import extract_endpoints
from starforge.entry_points import detect_entry_points
BASE=Path(__file__).resolve().parent/'private/starforge-survey';BASE.mkdir(exist_ok=True)
results={}
def run(name,fn):
 t=time.perf_counter()
 try: value=fn(); result={'seconds':round(time.perf_counter()-t,3),'result':value}
 except Exception as e: result={'seconds':round(time.perf_counter()-t,3),'error':str(e)}
 results[name]=result; print(name,result['seconds'],'error' if 'error' in result else 'done',flush=True)
 (BASE/'library-results.json').write_text(json.dumps(results,default=str,indent=2))
 return result.get('result')

def tracked(root):
 paths=subprocess.check_output(['git','-C',str(root),'ls-files','-z']).decode().split('\0')
 return [root/p for p in paths if p and (root/p).is_file() and not (root/p).is_symlink() and (root/p).stat().st_size<250000 and not any(s in Path(p).parts for s in ('node_modules','vendor','dist','build','archives','evidence'))]
root=Path.home()/'clients/syra/syrab2bdev'
files=[f for f in tracked(root) if f.suffix in {'.ts','.tsx','.js','.jsx','.py','.php'}][:1500]
def token_trial():
 groups=find_token_groups(files)
 return dict(files=len(files),groups=groups,largest=max((g['size'] for g in groups),default=0),grouped=sum(g['size'] for g in groups))
run('real_syra_token_groups_default',token_trial)
run('real_syra_endpoints',lambda:[dict(file=str(f.relative_to(root)),endpoints=found) for f in files if (found:=extract_endpoints(f.read_text(errors='replace'),str(f.relative_to(root))))])
# A bounded mirror preserves paths; it is private lab input, not a working copy.
mirror=BASE/'source-sample';mirror.mkdir(exist_ok=True)
exp=Path.home()/'dev/exp32-hybrid-jev-cbt'
pyfiles=[f for f in tracked(exp) if f.suffix=='.py' and str(f.relative_to(exp)).startswith('signal_lab/')][:120]
for f in pyfiles:
 dest=mirror/f.relative_to(exp);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(f.read_bytes())
run('real_exp32_import_groups',lambda:analyze_repo(mirror))
run('real_exp32_semantic_groups',lambda:analyze_repo(mirror,semantic=True))
run('real_exp32_paradigms',lambda:dict(collections.Counter(detect_paradigm(f.read_text(errors='replace'),f.name)['primary'] for f in pyfiles)))
run('real_exp32_entry_points',lambda:detect_entry_points(mirror))
class Catalog:
 def __init__(self,projects):self.projects=projects
 def list_projects(self,limit=500):return self.projects[:limit]
snapshot=json.loads((BASE.parent/'snapshot.json').read_text())
projects=[dict(name=Path(r['root']).name,path=r['root']) for r in {r['root']:r for r in snapshot['records']}.values()]
run('real_navcom_repo_lineages',lambda:LineageDetector(Catalog(projects)).detect_repo_lineages())
fixture=[dict(name=n) for n in ['quartz-v1','quartz-v2','quartz-v3','exp91-bot','exp92-bot','lab71-agent','lab72-agent','main','main-copy']]
run('controlled_repo_lineages',lambda:LineageDetector(Catalog(fixture)).detect_repo_lineages())
# Two separate products with shared support intentionally challenge component grouping.
mono=BASE/'monorepo-control';mono.mkdir(exist_ok=True)
for name,body in {'billing.py':'from common import validate\ndef invoice(value):\n    return validate(value) * 2\n','scheduling.py':'from common import validate\ndef booking(value):\n    return validate(value) + 1\n','common.py':'def validate(value):\n    return max(0, value)\n'}.items():(mono/name).write_text(body)
run('controlled_monorepo_import_groups',lambda:analyze_repo(mono,semantic=True))
ancestor=BASE/'ancestry-control';ancestor.mkdir(exist_ok=True)
body='def estimate_invoice(items):\n    subtotal = sum(items)\n    return subtotal * 1.07\n'
(ancestor/'billing.py').write_text(body)
(ancestor/'unrelated.py').write_text('def create_booking(day):\n    return {"day": day, "confirmed": True}\n')
run('controlled_ancestry',lambda:find_ancestors(body.replace('1.07','1.08'),'estimate_invoice',[ancestor]))
# Compare the actual shipped borrowed modules; byte identity is stronger than recollection.
borrowed=Path.home()/'.codex/skills/ship-commission/scripts/borrowed'
comparison=[]
for name in ['env_vars','build_systems','config_files','portability','utils','file_dupes']:
 a=borrowed/(name+'.py') if name not in ['utils','file_dupes'] else borrowed/'intake_starforge'/(name+'.py')
 b=SF/'starforge'/(name+'.py')
 comparison.append(dict(module=name,borrowed=str(a),upstream=str(b),same_bytes=a.read_bytes()==b.read_bytes(),borrowed_sha256=hashlib.sha256(a.read_bytes()).hexdigest(),upstream_sha256=hashlib.sha256(b.read_bytes()).hexdigest()))
results['starship_borrowed_comparison']=comparison
(BASE/'library-results.json').write_text(json.dumps(results,default=str,indent=2))
