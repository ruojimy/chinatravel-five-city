"""Public reference reads must remain separate from certified source access."""
import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.collection_workflow import AgentMemory

class ReferenceAccessTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.m=AgentMemory(Path(self.tmp.name)/'agent.sqlite3')
  self.m.merge_source({'family':'example.org','status':'unknown','live_fetch_authorized':False,'min_interval_seconds':0})
  self.m.begin_run('R',{'web_action':3,'api_http':0})
 def tearDown(self):self.m.close();self.tmp.cleanup()
 def test_explicit_pending_reference_fetch_preserves_strict_gate_and_status(self):
  url='https://example.org/hours'
  self.assertFalse(self.m.source_check(url,'opentime')['allowed'])
  self.m.reserve('R','fetch',url,'web_action',field='opentime',reference_only=True,context={'tool':'web.open'})
  self.m.finish('fetch','success',evidence_file='raw.txt')
  payload=json.loads(self.m.db.execute("select payload from requests where id='fetch'").fetchone()[0])
  self.assertTrue(payload['reference_only']);self.assertFalse(payload['claim_acceptance_granted'])
  self.assertEqual(self.m.export_sources()[0]['status'],'unknown')
  self.assertFalse(self.m.source_check(url,'opentime')['allowed'])
 def test_search_binds_real_query_and_tool(self):
  for context in ({'tool':'web.open'},{'tool':'web.search_query','query':''}):
   with self.assertRaises(ValueError):
    self.m.reserve('R','bad','https://example.org/','web_action',action='search',reference_only=True,context=context)
  self.m.reserve('R','search','https://example.org/','web_action',action='search',reference_only=True,
    context={'tool':'web.search_query','query':'site:example.org opening hours'})
 def test_pause_applies_to_fetch_and_search_and_all_family_hosts(self):
  self.m.merge_source({'family':'example.org','status':'paused','pause_evidence':['actual-denial.txt']})
  for action,context in [('fetch',{'tool':'web.open'}),('search',{'tool':'web.search_query','query':'hours'})]:
   with self.assertRaisesRegex(ValueError,'inherited_family_pause'):
    self.m.reserve('R',action,'https://other.example.org/','web_action',field='opentime',action=action,reference_only=True,context=context)
 def test_api_missing_purpose_and_bad_urls_still_denied(self):
  for url,field,action,channel in [('https://example.org/',None,'fetch','web_action'),
    ('http://example.org/','opentime','fetch','web_action'),
    ('https://example.org/','opentime','api','api_http')]:
   with self.assertRaises(ValueError):
    self.m.reserve('R','bad',url,channel,field=field,action=action,reference_only=True,context={'tool':'web.open'})
 def test_real_denial_after_reference_read_pauses_family(self):
  self.m.reserve('R','fetch','https://example.org/hours','web_action',field='opentime',reference_only=True,context={'tool':'web.open'})
  self.m.finish('fetch','denied',evidence_file='actual403.txt')
  gate=self.m.reference_access_check('https://example.org/','opentime',context={'tool':'web.open'})
  self.assertFalse(gate['allowed']);self.assertEqual(gate['reason'],'inherited_family_pause')
 def test_reference_reads_use_same_global_budget(self):
  self.m.begin_run('small',{'web_action':1,'api_http':0})
  self.m.reserve('small','first','https://example.org/hours','web_action',field='opentime',reference_only=True,context={'tool':'web.open'})
  self.m.finish('first','success')
  with self.assertRaisesRegex(ValueError,'budget'):
   self.m.reserve('small','second','https://example.org/hours','web_action',field='opentime',reference_only=True,context={'tool':'web.open'})

if __name__=='__main__':unittest.main()
