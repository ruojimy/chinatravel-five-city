"""Time-only session regressions; account quota data must never stop work."""
import hashlib,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.collection_session import SessionLedger
POLICY={'control_mode':'time_only','stop_starting_work_after_minutes':50,'checkpoint_deadline_minutes':60}

class SessionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();p=Path(self.tmp.name)/'memory.sqlite3'
  self.a=SessionLedger(p,POLICY.copy());self.b=SessionLedger(p,POLICY.copy())
 def tearDown(self):self.a.close();self.b.close();self.tmp.cleanup()
 def test_missing_usage_does_not_block_start_or_work(self):
  self.assertTrue(self.a.begin('A',now=0)['allowed'])
  self.assertTrue(self.a.checkpoint('A',now=600)['allowed_to_start_more_work'])
 def test_retired_policy_keys_cannot_reactivate_quota_gates(self):
  self.a.policy.update(minimum_primary_remaining_percent=30,minimum_weekly_remaining_percent=20,target_primary_usage_points_per_run=1,weekly_automation_usage_points_cap=1)
  self.a.begin('A',{'ordinaryUsageAllowed':False},now=0)
  self.assertTrue(self.a.checkpoint('A',{'rateLimits':None},now=600)['allowed_to_start_more_work'])
 def test_jumps_resets_and_malformed_quota_inputs_are_ignored(self):
  self.a.begin('A',{},now=0)
  for i,value in enumerate([{'usedPercent':100},{'resetsAt':1},None,'not a quota snapshot']):
   self.assertTrue(self.a.checkpoint('A',value,now=60*(i+1))['allowed_to_start_more_work'])
 def test_active_or_stale_session_still_prevents_overlap(self):
  self.a.begin('A',now=0)
  with self.assertRaisesRegex(ValueError,'Existing session'):self.b.begin('B',now=100000)
 def test_fifty_minute_work_and_sixty_minute_close_boundaries(self):
  self.a.begin('A',now=0)
  self.assertTrue(self.a.checkpoint('A',now=2999)['allowed_to_start_more_work'])
  self.assertIn('time_to_checkpoint',self.a.checkpoint('A',now=3000)['reasons'])
  self.assertIn('checkpoint_deadline_reached',self.a.checkpoint('A',now=3600)['reasons'])
 def test_microtask_and_old_quota_exit_reasons_are_rejected(self):
  self.a.begin('A',now=0)
  for reason in ['first_pilot_checkpoint','usage_budget_reached','time_budget_reached']:
   with self.assertRaises(ValueError):self.a.end('A',reason,workers_stopped=True,now=150)
 def test_complete_milestone_still_requires_evidence_and_empty_ready_queue(self):
  self.a.begin('A',now=0);p=Path(self.tmp.name)/'proof.json';p.write_text('fixture',encoding='utf-8')
  report={'pending_actionable_items':1,'milestone_complete':True,'milestone_id':'strict_adapter_integrated','artifact_path':str(p),'artifact_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
  with self.assertRaises(ValueError):self.a.end('A','batch_goal_complete',workers_stopped=True,stop_report=report,now=150)
  report['pending_actionable_items']=0
  self.assertTrue(self.a.end('A','batch_goal_complete',workers_stopped=True,stop_report=report,now=150)['ended'])
 def test_worker_release_confirmation_is_still_required(self):
  self.a.begin('A',now=0)
  with self.assertRaises(ValueError):self.a.end('A','time_budget_reached',now=3000)
  self.assertTrue(self.a.end('A','time_budget_reached',workers_stopped=True,now=3000)['ended'])
if __name__=='__main__':unittest.main(verbosity=2)
