"""Bounded CLI reuse trials against a private copy of the existing catalog."""
import concurrent.futures,hashlib,json,os,subprocess,time
from pathlib import Path
BASE=Path(__file__).resolve().parent/'private/starforge-survey'
env=dict(os.environ,STARFORGE_GLOBAL_DIR=str(BASE/'home'),COLUMNS='160',NO_COLOR='1')
TRIALS=[
 ['catalog-health'],['export','projects','--compact'],['lineage','--repos','-n','12'],
 ['lineage','-n','12'],['scaffolding'],['concept','chatbot listener protocol mental health','-n','8'],
 ['explore','exp32','-n','8'],['timeline','listener'],['why','syrab2bdev'],['profile','syrab2bdev'],
 ['captainslog-context'],['captainslog-search','syra'],['entry-points','--repo','syrab2bdev'],
 ['apis','syrab2bdev','-n','8'],['token-groups','starforge','-n','5'],['groups','starforge','-n','5'],['groups','starforge','--semantic','-n','5']]
def run(item):
 name='-'.join(item).replace('/','_').replace(' ','_');t=time.perf_counter()
 try:
  p=subprocess.run(['starforge',*item],env=env,capture_output=True,text=True,timeout=25)
  result=dict(command=['starforge',*item],seconds=round(time.perf_counter()-t,3),exit=p.returncode,timeout=False)
  output=p.stdout+'\n'+p.stderr
 except subprocess.TimeoutExpired as e:
  result=dict(command=['starforge',*item],seconds=round(time.perf_counter()-t,3),exit=None,timeout=True)
  output=(e.stdout or b'').decode(errors='replace') if isinstance(e.stdout,bytes) else (e.stdout or '')
 (BASE/(name+'.txt')).write_text(output);result['output']=name+'.txt';result['chars']=len(output)
 print(json.dumps(result),flush=True);return result
if __name__=='__main__':
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(run,TRIALS))
 (BASE/'cli-results.json').write_text(json.dumps(results,indent=2))
