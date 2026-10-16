"""Exercise unchanged Starforge code-search against all 40 omitted snapshot files.
The capture adapter records its Rich table cells; it does not implement search.
"""
import collections,hashlib,json,os,re,shutil,subprocess,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path.home()/'dev/starforge/src'))
import typer
from rich.table import Table
from starforge.cli_reporting import register
BASE=Path(__file__).resolve().parent
HOME=BASE/'private/broader-search';HOME.mkdir(exist_ok=True)
proof=json.loads((BASE/'private/local-harvest-proof/receipt.json').read_text())
state=json.loads((Path(proof['cache'])/'current.json').read_text())
skips=json.loads((BASE/'private/local-harvest-proof/skip-audit.json').read_text())
# Existing immutable snapshot sources, exposed in Starforge's expected layout.
for s in state['sources']:
 link=HOME/'harvest-cache/local-lab'/s['label'];link.parent.mkdir(parents=True,exist_ok=True)
 target=Path(s['artifact'])/'source'
 if link.is_symlink() and link.resolve()!=target.resolve():raise RuntimeError('Different source snapshot already linked')
 if not link.exists():link.symlink_to(target,target_is_directory=True)
shutil.copyfile(state['catalog'],HOME/'catalog.json')
os.environ['STARFORGE_GLOBAL_DIR']=str(HOME)
os.chdir(HOME)  # Deliberately select only this lab's harvest-cache.
class Capture:
 def __init__(self):self.rows=[];self.messages=[]
 def print(self,obj,*args,**kwargs):
  if isinstance(obj,Table):self.rows.extend([list(row) for row in zip(*(c._cells for c in obj.columns))])
  else:self.messages.append(str(obj))
capture=Capture();app=typer.Typer();register(app,capture)
search=next(c.callback for c in app.registered_commands if c.name=='code-search')
def trial(pattern,repo='',ext='',expected=None,limit=1000):
 capture.rows=[];capture.messages=[];t=time.perf_counter()
 search(pattern=pattern,repo=repo,ext=ext,limit=limit,context=0)
 rows=capture.rows[:];paths={r[1] for r in rows}
 return dict(pattern=pattern,repo=repo,ext=ext,expected=expected,found=expected in paths if expected else None,seconds=round(time.perf_counter()-t,4),rows=rows,messages=capture.messages[:])
coverage=[]
for group in skips:
 for item in group['skipped']:
  rel='local-lab/'+group['source']+'/'+item['path'];p=HOME/'harvest-cache'/rel
  lines=p.read_text().splitlines()
  candidates=[line.strip() for line in lines if len(line.strip())>=20]
  if not candidates:raise RuntimeError('No suitable coverage probe: '+rel)
  # Known-string retrieval tests reachability, not semantic relevance.
  snippet=max(candidates,key=lambda s:len(set(s)))[:160]
  coverage.append(trial(re.escape(snippet),group['source'],p.suffix,rel))
human=[
 ('class Discovery','navcom','.py','navcom_discovery.py'),
 ('isHumanMembershipRole','syrab2bdev','.ts','src/lib/auth/role-grant-policy.ts'),
 ('Hotflywheel consumes explicit evidence events','exp32-hybrid-jev-cbt','.py','signal_lab/flywheel_adapter.py'),
 ('Signal proposals and protocol goals','exp32-hybrid-jev-cbt','.md','signal_lab/CONTROLLER-CONTRACT.md'),
 ('MODELS|model|inference','exp32-hybrid-jev-cbt','.md','signal_lab/MODEL-MODES.md'),
]
meaningful=[trial(q,r,e,'local-lab/'+r+'/'+p) for q,r,e,p in human]
negative=trial('NAVCOM_UNIQUE_ABSENT_79bcfd')
scope=trial('isHumanMembershipRole','navcom','.ts')
extension=trial('Signal proposals and protocol goals','exp32-hybrid-jev-cbt','.py')
cli=[]
for args in [ ['code-search','class Discovery','--repo','navcom','--ext','.py'],['code-search','Signal proposals and protocol goals','--repo','exp32-hybrid-jev-cbt','--ext','.md'],['search','Signal proposals and protocol goals'],['concept','Signal proposals and protocol goals','-n','5'] ]:
 t=time.perf_counter();p=subprocess.run(['starforge',*args],cwd=HOME,env=dict(os.environ,COLUMNS='180',NO_COLOR='1'),capture_output=True,text=True,timeout=30)
 name='cli-'+str(len(cli))+'.txt';(HOME/name).write_text(p.stdout+p.stderr)
 cli.append(dict(command=['starforge',*args],exit=p.returncode,seconds=round(time.perf_counter()-t,3),output=name))
source=Path.home()/'dev/starforge/src/starforge/cli_reporting.py'
receipt=dict(source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),coverage=coverage,meaningful=meaningful,negative=negative,scope_negative=scope,extension_negative=extension,cli=cli)
(HOME/'receipt.json').write_text(json.dumps(receipt,indent=2))
summary=dict(omitted_files=len(coverage),retrieved=sum(r['found'] for r in coverage),by_extension=dict(collections.Counter(Path(r['expected']).suffix for r in coverage)),meaningful_hits=[r['found'] for r in meaningful],negative_rows=[len(negative['rows']),len(scope['rows']),len(extension['rows'])],scan_seconds=round(sum(r['seconds'] for r in coverage),3),cli=cli)
print(json.dumps(summary,indent=2))
assert all(r['found'] for r in coverage+meaningful)
assert not negative['rows'] and not scope['rows'] and not extension['rows']
assert all(c['exit']==0 for c in cli)
