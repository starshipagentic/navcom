import contextlib,io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import harvest_flow as flow

def code(word):
 return '\n'.join(['"""'+word+' workflow for local orchestration."""','def execute(value):']+['    step_'+str(i)+' = value + '+str(i) for i in range(22)]+['    return step_21',''])

class HarvestJourney(unittest.TestCase):
 def test_incremental_atomic_scoped_journey(self):
  with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stderr(io.StringIO()):
   base=Path(tmp);root=base/'source';root.mkdir();other=base/'other';other.mkdir();cache=base/'cache'
   (root/'README.md').write_text('# Harvest control')
   (root/'worker.py').write_text(code('marmot'))
   (other/'worker.py').write_text(code('marmot'))
   sources=[dict(id='a',root=str(root),label='alpha',include=['.'],conversation_collection='projects:fixture-a'),dict(id='b',root=str(other),label='beta',include=['.'],conversation_collection='projects:fixture-b')]
   first=flow.refresh(sources,cache);self.assertEqual(first['analyzed_sources'],2)
   first_pointer=(cache/'current.json').read_bytes()
   with patch.object(flow.Harvester,'_analyze_and_store',side_effect=AssertionError('Unexpected reharvest')):
    second=flow.refresh(sources,cache);self.assertEqual(second['analyzed_sources'],0)
    self.assertEqual(first_pointer,(cache/'current.json').read_bytes())
    for _ in range(2):
     result=flow.search('marmot',cache,within='alpha')
     self.assertTrue(result['hits']);self.assertTrue(all(h['source']=='alpha' for h in result['hits']))
   worker=root/'worker.py';oldstat=worker.stat();worker.write_text(code('otters'));os.utime(worker,ns=(oldstat.st_atime_ns,oldstat.st_mtime_ns))
   changed=flow.refresh(sources,cache);self.assertEqual(changed['analyzed_sources'],1)
   self.assertTrue(flow.search('otters',cache,'alpha')['hits'])
   worker.unlink();deleted=flow.refresh(sources,cache);self.assertEqual(deleted['analyzed_sources'],1)
   self.assertFalse(flow.search('otters',cache,'alpha')['hits'])
   pointer=(cache/'current.json').read_bytes()
   (root/'worker.py').write_text(code('gazelle'))
   with patch.object(flow.Harvester,'_analyze_and_store',side_effect=RuntimeError('Injected analyzer failure')):
    with self.assertRaises(RuntimeError):flow.refresh(sources,cache)
   self.assertEqual(pointer,(cache/'current.json').read_bytes())
   worker.unlink()
   with patch.object(flow,'extractor_signature',return_value='changed-extractor'):
    self.assertEqual(flow.refresh(sources,cache)['analyzed_sources'],2)
   pointer=(cache/'current.json').read_bytes()
   bad=[dict(sources[0],root=str(base/'missing')),sources[1]]
   with self.assertRaises(ValueError):flow.refresh(bad,cache)
   self.assertEqual(pointer,(cache/'current.json').read_bytes())
   with flow.writer(cache):
    with self.assertRaises(RuntimeError):flow.refresh(sources,cache)
    self.assertTrue(flow.search('marmot',cache,'beta')['hits'])
   with self.assertRaises(ValueError):flow.search('marmot',cache,'nonexistent')
   flow.refresh([sources[0]],cache)
   self.assertFalse(flow.search('marmot',cache)['hits'])

 def test_scope_budget_and_private_files(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'worker.py').write_text(code('marmot'));(root/'.env').write_text('SECRET=not-for-index')
   (root/'outside.py').symlink_to('/etc/hosts')
   src=dict(root=str(root),include=['.'])
   data,_,coverage=flow.source_bytes(src)
   self.assertEqual(set(data),{'worker.py'});self.assertIn('.env',coverage['excluded']);self.assertIn('outside.py',coverage['excluded'])
   with self.assertRaises(ValueError):flow.source_bytes(dict(src,include=['../']))
   (root/'huge.py').write_bytes(b'x'*250001)
   with self.assertRaises(ValueError):flow.source_bytes(src)

if __name__=='__main__':unittest.main()
