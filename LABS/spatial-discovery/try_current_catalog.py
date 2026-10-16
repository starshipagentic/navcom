"""Feed bounded current metadata to the unchanged Starforge catalog/search APIs.
README documents are adapter records, not claims that code gem discovery ran.
"""
import json,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path.home()/'dev/starforge/src'))
from starforge.catalog import Catalog
from starforge.concept_search import concept_search
base=Path(__file__).resolve().parent/'private/starforge-survey/current-catalog';base.mkdir(exist_ok=True)
catalog=Catalog(base/'catalog.json')
snapshot=json.loads((base.parents[1]/'snapshot.json').read_text())
roots={r['root']:r for r in snapshot['records']};count=0
for path,r in roots.items():
 if not r['text']:continue
 name=Path(path).name
 # Stable unique file identity avoids duplicate basename collisions in concept_search.
 catalog.add_project(name,path,summary=r['text'][:24000])
 catalog.add_gem(path,path+'/README.md',name,description=r['text'][:24000])
 count+=1
results={}
for query in ['chatbot listener protocol mental health','exp32 matrix','cognito authorization']:
 t=time.perf_counter();hits=concept_search(query,catalog,base,limit=8)
 results[query]={'seconds':round(time.perf_counter()-t,3),'hits':hits}
 print(query,[(h['repo'],h['score']) for h in hits])
(base.parent/'current-catalog-results.json').write_text(json.dumps({'adapter_records':count,'queries':results},indent=2))
