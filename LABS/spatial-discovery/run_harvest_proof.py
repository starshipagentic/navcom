"""Reproduce the bounded real-data journey. Selection is test data, not classifier rules."""
import hashlib,json,subprocess,sys,time
from pathlib import Path
import harvest_flow as flow
base=flow.BASE/'private/local-harvest-proof';base.mkdir(exist_ok=True)
selections=[
 (Path.home()/'dev/navcom',['README.md','navcom_atlas.py','navcom_discovery.py']),
 (Path.home()/'dev/exp32-hybrid-jev-cbt',['README.md','signal_lab']),
 (Path.home()/'clients/syra/syrab2bdev',['README.md','src/lib/auth']),
]
sources=[]
for root,includes in selections:
 flow.progress('discovering '+str(root));sources.append(flow.discover(root,includes))
flow.write(base/'selection.json',sources)
# Refuse accidental reuse when asserting a cold run; keep prior proof intact.
cache=Path(__import__('tempfile').mkdtemp(prefix='run-',dir=base))
first=flow.refresh(sources,cache)
second=flow.refresh(sources,cache)
pointer_before=(cache/'current.json').read_bytes()
queries=[]
for q,scope in [('reader','exp32-hybrid-jev-cbt'),('cerbos','syrab2bdev'),('discovery','navcom'),('atlas','navcom')]:
 r=flow.search(q,cache,scope);queries.append(r)
 # Preserve the discovered selective-gem gap; do not call it a passing retrieval.
 if q!='discovery':assert r['hits'],(q,'no hits')
 assert all(h['source']==scope for h in r['hits'])
 assert all(Path(h['source_path']).is_file() for h in r['hits'])
assert first['analyzed_sources']==3
assert second['analyzed_sources']==0
assert (cache/'current.json').read_bytes()==pointer_before
# Actually execute one returned conversation-scope command, read-only.
cmd=queries[0]['hits'][0]['conversation_command']+['--json','--limit','3']
p=subprocess.run(cmd,capture_output=True,text=True,check=True,timeout=30);conversation=json.loads(p.stdout)
assert conversation['effective_scope']['collection']==sources[1]['conversation_collection']
receipt=dict(first=first,unchanged=second,queries=queries,conversation_handoff=dict(command=cmd,scope=conversation['effective_scope'],returned=len(conversation['nodes']),freshness=conversation['freshness']),cache=str(cache))
flow.write(base/'receipt.json',receipt)
print(json.dumps(dict(first=first,unchanged=second,searches=[dict(query=r['query'],source=r['within'],hits=len(r['hits']),seconds=r['seconds']) for r in queries],conversation_handoff=receipt['conversation_handoff'],cache=str(cache)),indent=2))
