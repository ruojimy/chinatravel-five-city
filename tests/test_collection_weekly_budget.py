"""Weekly budget only: immutable baseline, one campaign, no time deadline."""
import hashlib,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.collection_weekly_budget import WeeklyBudgetCampaign,weekly_snapshot
from shorttrip.collection_session import SessionLedger

def usage(used,primary=True,reset=20000):
 week={'usedPercent':used,'windowDurationMins':10080,'resetsAt':reset}
 return {'rateLimitsByLimitId':{'codex':{'primary':week if primary else {'usedPercent':99,'windowDurationMins':300,'resetsAt':10000},'secondary':None if primary else week}}}
class WeeklyTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'m.sqlite3';self.c=WeeklyBudgetCampaign(self.path)
 def tearDown(self):self.c.close();self.tmp.cleanup()
 def test_weekly_window_can_be_primary_or_secondary(self):
  for primary in (True,False):self.assertEqual(weekly_snapshot(usage(9,primary))['used'],9)
 def test_baseline_is_not_reset_on_resume(self):
  self.c.initialize('C',usage(9));self.c.check('C',usage(15))
  with self.assertRaises(ValueError):self.c.initialize('C',usage(15))
  self.assertEqual(self.c.status('C')['target_used_percent'],29)
 def test_nineteen_point_growth_continues_twenty_stops(self):
  self.c.initialize('C',usage(9));self.assertTrue(self.c.check('C',usage(28))['allowed_to_start_more_work'])
  r=self.c.check('C',usage(29));self.assertFalse(r['allowed_to_start_more_work']);self.assertEqual(r['spent_points'],20)
 def test_no_time_or_five_hour_gate(self):
  self.c.initialize('C',usage(9));s=SessionLedger(self.path,{'control_mode':'weekly_budget','weekly_campaign_id':'C'})
  try:
   self.assertIsNone(s.begin('R',usage(9),now=0)['deadline_epoch'])
   self.assertTrue(s.checkpoint('R',usage(15,False),now=100000)['allowed_to_start_more_work'])
   with self.assertRaises(ValueError):s.end('R','time_budget_reached',workers_stopped=True,now=100000)
   s.checkpoint('R',usage(29),now=100001);self.assertTrue(s.end('R','weekly_budget_reached',workers_stopped=True,now=100001)['ended'])
  finally:s.close()
 def test_one_second_reset_jitter_does_not_stop(self):
  self.c.initialize('C',usage(9));self.assertTrue(self.c.check('C',usage(10,reset=20001))['allowed_to_start_more_work'])
 def test_real_week_change_does_not_allocate_another_budget(self):
  self.c.initialize('C',usage(9));r=self.c.check('C',usage(0,reset=700000))
  self.assertEqual(r['status'],'weekly_window_changed');self.assertFalse(r['allowed_to_start_more_work'])
 def test_unknown_usage_cannot_be_fabricated(self):
  with self.assertRaises(ValueError):self.c.initialize('C',{})
 def test_small_batch_cannot_end_the_active_campaign(self):
  self.c.initialize('C',usage(9));s=SessionLedger(self.path,{'control_mode':'weekly_budget','weekly_campaign_id':'C'})
  try:
   s.begin('R',usage(9),now=0)
   with self.assertRaisesRegex(ValueError,'checkpoint'):s.end('R','batch_goal_complete',workers_stopped=True,now=100)
  finally:s.close()
 def test_explicit_user_stop_keeps_campaign_and_requires_checkpoint(self):
  self.c.initialize('C',usage(9));s=SessionLedger(self.path,{'control_mode':'weekly_budget','weekly_campaign_id':'C'})
  try:
   s.begin('R',usage(9),now=0)
   with self.assertRaisesRegex(ValueError,'artifact'):s.end('R','user_requested',workers_stopped=True,now=1)
   artifact=Path(self.tmp.name)/'checkpoint.json';artifact.write_text('{}',encoding='utf-8')
   report={'artifact_path':str(artifact),'artifact_sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()}
   self.assertTrue(s.end('R','user_requested',workers_stopped=True,stop_report=report,now=2)['ended'])
   self.assertEqual(self.c.status('C')['status'],'active')
  finally:s.close()
if __name__=='__main__':unittest.main(verbosity=2)
