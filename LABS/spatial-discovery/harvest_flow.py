#!/usr/bin/env python3
"""Lab-only NavCom -> local Starforge harvest -> cached search. No ship dependency."""
import argparse, contextlib, fcntl, hashlib, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path
sys.dont_write_bytecode=True
SF=Path.home()/'dev/starforge/src';sys.path.insert(0,str(SF))
from starforge.catalog import Catalog
from starforge.analyzer import ProjectAnalyzer
from starforge.gem_finder import GemFinder
from starforge.harvester import Harvester
from starforge.concept_search import concept_search
from starforge.utils import SKIP_DIRS
BASE=Path(__file__).resolve().parent
DEFAULT=BASE/'private/local-harvest'
EXT={'.py','.js','.ts','.tsx','.jsx','.sh','.lua','.rb','.go','.rs','.md','.toml'}
SKIP=set(SKIP_DIRS)|{'LABS','history','diary','evidence','.starship'}

def digest(data):return hashlib.sha256(data).hexdigest()
def read(path):return json.loads(path.read_text())
def write(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.publish-')
 try:
  with os.fdopen(fd,'w') as f:json.dump(data,f,indent=2);f.flush();os.fsync(f.fileno())
  os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def progress(message):print('harvest lab ▸ '+message,file=sys.stderr,flush=True)

def discover(root,includes):
 root=Path(root).expanduser().resolve();matches=[];offset=0
 while True:
  out=subprocess.run(['navcom','atlas','list','projects','--limit','200','--offset',str(offset),'--json'],capture_output=True,text=True,timeout=30,check=True)
  result=json.loads(out.stdout)
  for node in result['nodes']:
   p=Path(node['label']).expanduser()
   if p.is_absolute() and p.resolve()==root:matches.append(node)
  if not result['more']:break
  offset+=200
 if len(matches)!=1:raise ValueError('Select one exact indexed project root; found '+str(len(matches)))
 n=matches[0]
 return dict(id=digest(str(root).encode())[:16],root=str(root),label=root.name,include=includes,conversation_collection=n['collection'],conversations=n['count'])

def source_bytes(source):
 root=Path(source['root'])
 if not root.is_dir():raise ValueError('Source unavailable: '+str(root))
 paths=set();excluded=[]
 for item in source['include']:
  rel=Path(item)
  if rel.is_absolute() or '..' in rel.parts:raise ValueError('Scope must stay inside its source')
  target=root/rel
  if not target.exists():raise ValueError('Selected scope missing: '+str(target))
  if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):raise ValueError('Scope escapes source')
  if target.is_file():paths.add(target)
  else:
   for folder,dirs,names in os.walk(target,followlinks=False):
    parent=Path(folder)
    for d in dirs:
     if d in SKIP or d.startswith('.') or (parent/d).is_symlink():excluded.append(str((parent/d).relative_to(root)))
    dirs[:]=sorted(d for d in dirs if d not in SKIP and not d.startswith('.') and not (parent/d).is_symlink())
    paths.update(parent/name for name in names)
 payload={};total=0
 for path in sorted(paths):
  rel=str(path.relative_to(root))
  if path.is_symlink():excluded.append(rel);continue
  if path.name.startswith('.') or (path.suffix not in EXT and path.name not in {'package.json','requirements.txt','Makefile','Dockerfile'}):excluded.append(rel);continue
  if path.stat().st_size>250000:raise ValueError('Oversize selected file: '+rel)
  data=path.read_bytes();total+=len(data)
  if len(payload)>=250 or total>4*1024*1024:raise ValueError('Explicit lab scan budget exceeded; narrow the scope')
  payload[rel]=data
 if not payload:raise ValueError('No supported files in selected scope')
 signature=digest(json.dumps([(p,digest(b)) for p,b in payload.items()]).encode())
 return payload,signature,dict(files=len(payload),bytes=total,include=source['include'],excluded=sorted(excluded),supported_extensions=sorted(EXT),full_repository=False)

def extractor_signature():
 files=sorted((SF/'starforge').glob('*.py'))+[Path(__file__)]
 return digest(b''.join(str(p).encode()+p.read_bytes() for p in files))

@contextlib.contextmanager
def writer(cache):
 cache.mkdir(parents=True,exist_ok=True,mode=0o700)
 with (cache/'writer.lock').open('a') as handle:
  try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise RuntimeError('Another lab harvest is running; cached search remains available')
  try:yield
  finally:fcntl.flock(handle,fcntl.LOCK_UN)

def refresh(sources,cache=DEFAULT):
 start=time.perf_counter();progress('starting — checking selected sources')
 with writer(cache):
  if not sources:raise ValueError('Select at least one source for this lab')
  if len({s['id'] for s in sources})!=len(sources):raise ValueError('Duplicate source identity')
  old=read(cache/'current.json') if (cache/'current.json').exists() else {'sources':[]}
  oldmap={s['id']:s for s in old['sources']};extractor=extractor_signature();receipts=[];changed=0
  for i,s in enumerate(sources,1):
   progress(f'[{i}/{len(sources)}] checking {s["label"]}')
   payload,signature,coverage=source_bytes(s)
   key=digest(json.dumps([s,signature,extractor],sort_keys=True).encode());artifact=cache/'artifacts'/key
   if not (artifact/'receipt.json').exists():
    progress(f'[{i}/{len(sources)}] analyzing {s["label"]} — {len(payload)} files')
    stage=Path(tempfile.mkdtemp(prefix='.work-',dir=cache))
    try:
     snapshot=stage/'source';snapshot.mkdir()
     for rel,data in payload.items():p=snapshot/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
     catalog=Catalog(stage/'catalog.json')
     h=Harvester(catalog,None,ProjectAnalyzer(dispatcher=False),GemFinder(),llm_delay=0)
     result=h._analyze_and_store(snapshot,s['id'],'navcom-local-lab')
     # Harvester catches gem extraction exceptions. Independently verify expected output.
     expected=GemFinder().scan(snapshot,s['id'],'navcom-local-lab')
     if result['gems_found']!=len(expected):raise RuntimeError('Incomplete gem harvest')
     data=read(stage/'catalog.json')
     # Snapshot moves once at publication; retain valid immutable artifact paths.
     raw=json.dumps(data).replace(str(stage),str(artifact));(stage/'catalog.json').write_text(raw)
     if source_bytes(s)[1]!=signature:raise RuntimeError('Source changed during harvest; retry')
     write(stage/'receipt.json',dict(source=s,signature=signature,extractor=extractor,coverage=coverage,gems=result['gems_found']))
     artifact.parent.mkdir(parents=True,exist_ok=True);os.replace(stage,artifact);changed+=1
    finally:
     if stage.exists():shutil.rmtree(stage)
   else:progress(f'[{i}/{len(sources)}] cached {s["label"]}')
   receipts.append(dict(s,artifact=str(artifact),signature=signature,extractor=extractor,coverage=coverage))
  identical=old['sources']==receipts
  if not identical:
   gen=Path(tempfile.mkdtemp(prefix='generation-',dir=cache));catalog=Catalog(gen/'catalog.json')
   for s in receipts:
    raw=read(Path(s['artifact'])/'catalog.json')
    for p in raw.get('projects',{}).values():
     catalog.add_project(p['name'],p['path'],summary=p['summary'],tech_stack=p['tech_stack'],tags=p['tags'],galaxy=p.get('galaxy',''))
    for g in raw.get('gems',{}).values():
     rel=str(Path(g['file_path']).relative_to(Path(s['artifact'])/'source'))
     # The search implementation keys by gem name; make it unique across sources/files.
     name=s['label']+':'+s['id']+':'+rel
     catalog.add_gem(name,g['file_path'],s['id'],description=g['description'],importance_score=g['importance_score'],signals=g['signals'],language=g['language'],mtime=g.get('mtime',0))
   write(cache/'current.json',dict(sources=receipts,catalog=str(gen/'catalog.json'),published=time.time()))
  result=dict(analyzed_sources=changed,cached_sources=len(sources)-changed,published=not identical,seconds=round(time.perf_counter()-start,3),sources=len(sources))
  progress('complete — '+str(changed)+' sources analyzed');return result

class ScopedCatalog:
 def __init__(self,catalog,allowed):self.catalog=catalog;self.allowed=allowed
 def list_gems(self,limit=50000):return [g for g in self.catalog.list_gems(limit=50000) if g['source_repo'] in self.allowed][:limit]
 def list_projects(self,limit=50000):return [p for p in self.catalog.list_projects(limit=50000) if p['name'] in self.allowed][:limit]
 def search_gems(self,q,limit=30):return [g for g in self.catalog.search_gems(q,limit=50000) if g['source_repo'] in self.allowed][:limit]
 def search_projects(self,q,limit=20):return [p for p in self.catalog.search_projects(q,limit=50000) if p['name'] in self.allowed][:limit]

def search(query,cache=DEFAULT,within=None):
 start=time.perf_counter();state=read(cache/'current.json');sources={s['id']:s for s in state['sources']}
 if within:
  matches=[s for s in sources.values() if within in (s['id'],s['label'],s['root'])]
  if len(matches)!=1:raise ValueError('Scope must identify exactly one source')
  allowed={matches[0]['id']}
 else:allowed=set(sources)
 catalog=ScopedCatalog(Catalog(Path(state['catalog'])),allowed)
 hits=concept_search(query,catalog,cache/'no-harvest-tree',limit=8)
 for hit in hits:
  s=sources[hit['repo']];rel=Path(hit['file_path']).relative_to(Path(s['artifact'])/'source')
  hit.update(source_path=str(Path(s['root'])/rel),source=s['label'],conversation_collection=s.get('conversation_collection'),conversation_command=['navcom','atlas','search',query,'--within',s['conversation_collection']] if s.get('conversation_collection') else None)
 return dict(query=query,within=within,hits=hits,seconds=round(time.perf_counter()-start,3),published=state['published'],freshness='last complete explicit harvest; search does not rescan sources',harvest_invocations=0)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache',type=Path,default=DEFAULT);sp=p.add_subparsers(dest='action',required=True)
 d=sp.add_parser('discover');d.add_argument('root');d.add_argument('--include',action='append',required=True)
 r=sp.add_parser('refresh');r.add_argument('selection',type=Path)
 q=sp.add_parser('search');q.add_argument('query');q.add_argument('--within')
 args=p.parse_args()
 try:
  if args.action=='discover':result=discover(args.root,args.include)
  elif args.action=='refresh':result=refresh(read(args.selection),args.cache)
  else:result=search(args.query,args.cache,args.within)
  print(json.dumps(result,indent=2))
 except (ValueError,RuntimeError,OSError,subprocess.SubprocessError) as e:
  print('harvest lab: '+str(e),file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
