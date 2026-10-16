"""Read-only use of Starship's existing bounded inspector; no commissioning."""
import json,sys,time,importlib.util
from pathlib import Path
sys.dont_write_bytecode=True
scripts=Path.home()/'.codex/skills/ship-commission/scripts';sys.path.insert(0,str(scripts))
import readiness
root=Path.home()/'clients/syra/syrab2bdev'
t=time.perf_counter();report=readiness.inspect_source(root,max_files=200,max_bytes=4*1024*1024,seconds=3)
out=Path(__file__).resolve().parent/'private/starforge-survey/starship-inspection.json';out.write_text(json.dumps(report,indent=2))
print(json.dumps({'seconds':round(time.perf_counter()-t,3),'tools_used':report['tools_used'],'coverage':report['coverage'],'build_system_count':len(report['build_systems']),'environment_reference_names':len(report['environment_references']),'ready':report['ready']},indent=2))
