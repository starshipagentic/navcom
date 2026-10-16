"""Run the existing harvest analysis stage on the bounded local lab mirror.
No GitHub scanner, network harvest, model calls or original-catalog writes.
"""
import json,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path.home()/'dev/starforge/src'))
from starforge.catalog import Catalog
from starforge.analyzer import ProjectAnalyzer
from starforge.gem_finder import GemFinder
from starforge.harvester import Harvester
from starforge.concept_search import concept_search
base=Path(__file__).resolve().parent/'private/starforge-survey'
home=base/'harvest-stage';home.mkdir(exist_ok=True)
catalog=Catalog(home/'catalog.json')
harvester=Harvester(catalog,None,ProjectAnalyzer(dispatcher=False),GemFinder(),llm_delay=0)
t=time.perf_counter()
result=harvester._analyze_and_store(base/'source-sample','exp32-bounded-sample','local-lab')
seconds=time.perf_counter()-t
hits=concept_search('reader',catalog,home,limit=5)
receipt={'stage':'Harvester._analyze_and_store','source':'99-file bounded EXP32 Python mirror; not a full repository harvest','seconds':round(seconds,3),'projects':catalog.project_count(),'gems':catalog.gem_count(),'summary':result['summary'],'tech_stack':result['tech_stack'],'hits':hits,'llm':False,'github_clone_or_update':False}
(home/'receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt,indent=2))
