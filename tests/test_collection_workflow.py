"""Adversarial control-plane checks; all fixtures are synthetic and offline."""
import copy,json,sys,tempfile,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.collection_workflow import AgentMemory,aggregate,classify,decide,digest
from shorttrip.collection_task_schema import validate_cohort

def task(uid='T1'):
 return {'uid':uid,'level':'easy','city':'合成城','required_kinds':['accommodation'],
  'plan_present':True,'required_checks_complete':True,'hard_checks':[{'id':'budget','state':'pass'}],
  'gaps':[],'planner':{'supported':True,'search_complete':False}}
def gap():return {'gap_id':'G1','entity_id':'synthetic-hotel','field':'price','context':{'room':'twin'},
 'reason':'scope_mismatch','blocker_class':'data','required':True,'blocking':True,'repairable':True}
CFG={'stable_rounds':2,'global_block_rate':.1,'stratum_block_rate':.2,'min_block_rate_gain':.01,'max_repair_rounds':4}

class DiagnosisTests(unittest.TestCase):
 def test_hard_failure_does_not_create_collection_work(self):
  t=task();t['hard_checks'][0]['state']='fail';d=classify(t)
  self.assertEqual(d['outcome'],'candidate_constraint_fail');self.assertEqual(d['repair_queue'],[])
 def test_data_block_and_hard_failure_both_survive(self):
  t=task();t['gaps']=[gap()];t['hard_checks'][0]['state']='fail';d=classify(t)
  self.assertEqual(d['outcome'],'data_block');self.assertEqual(len(d['hard_failures']),1);self.assertEqual(len(d['repair_queue']),1)
 def test_dynamic_refresh_and_parser_limits_do_not_become_static_jobs(self):
  t=task();g=gap();g['lifecycle']='runtime';t['gaps']=[g]
  self.assertEqual(classify(t)['repair_queue'],[])
  g['blocker_class']='adapter';self.assertEqual(classify(t)['outcome'],'adapter_block')
 def test_reported_proof_cannot_self_certify(self):
  t=task();t['planner'].update(search_complete=True,infeasibility_proof={'validated':True,'scope':'frozen_candidate_universe','artifact_path':'fake','artifact_sha256':'fake'})
  d=classify(t);self.assertFalse(d['proof_verified_by_controller']);self.assertTrue(d['infeasibility_certificate_pending'])
  self.assertNotEqual(d['outcome'],'infeasible_proven')
 def test_shared_gap_is_one_job_with_two_affected_tasks(self):
  a,b=task('A'),task('B');a['gaps']=[gap()];b['gaps']=[gap()]
  m=aggregate([a,b],freeze_id='fixture',policy_id='fixture')
  self.assertEqual(m['unique_repair_jobs'],1);self.assertEqual(m['data_blocked'],2)
  self.assertIn('合成城|kind:accommodation',m['strata'])
 def test_same_field_different_reasons_merge_without_double_counting(self):
  t=task();a,b=gap(),gap();b.update(gap_id='G2',reason='missing_evidence');t['gaps']=[a,b]
  m=aggregate([t],freeze_id='fixture',policy_id='fixture')
  self.assertEqual(m['unique_repair_jobs'],1);self.assertEqual(len(m['repair_jobs'][0]['affected_tasks']),1)
  self.assertEqual(set(m['repair_jobs'][0]['reasons']),{'scope_mismatch','missing_evidence'})
 def test_empty_or_duplicate_batch_rejected(self):
  for ts in ([],[task(),task()]):
   with self.assertRaises(ValueError):aggregate(ts,freeze_id='fixture',policy_id='fixture')
 def test_infeasibility_certificate_never_makes_a_false_complete(self):
  t=task();t['hard_checks'][0]['state']='fail';t['planner']['search_complete']=True
  self.assertEqual(classify(t)['outcome'],'candidate_constraint_fail')
 def test_threshold_needs_stability_and_per_stratum_coverage(self):
  m=aggregate([task()],freeze_id='fixture',policy_id='fixture',coverage_floor_met=True)
  self.assertEqual(decide([m,m],CFG)['action'],'rotate_batch_threshold')
  bad=copy.deepcopy(m);bad['strata']['合成城|kind:accommodation']['data_block_rate']=.5
  self.assertNotEqual(decide([bad,bad],CFG)['action'],'rotate_batch_threshold')
 def test_denominator_and_policy_cannot_drift(self):
  m=aggregate([task()],freeze_id='fixture',policy_id='fixture');n=copy.deepcopy(m);n['task_keys_sha256']='changed'
  with self.assertRaises(ValueError):decide([m,n],CFG)
 def test_task_body_change_changes_digest_even_with_same_uid(self):
  a={'uid':'A','budget':100};b={**a,'budget':200};self.assertNotEqual(digest(a),digest(b))
 def test_pipeline_failure_blocks_rotation(self):
  t=task();t['planner']['error']='malformed saved JSON';m=aggregate([t],freeze_id='f',policy_id='p')
  self.assertEqual(decide([m],CFG)['action'],'repair_pipeline')
 def test_claimed_complete_without_checks_is_not_complete(self):
  t=task();t['status']='complete';t['hard_checks']=[]
  self.assertEqual(classify(t)['outcome'],'solver_incomplete')

class QuerySchemaTests(unittest.TestCase):
 def setUp(self):self.examples=json.loads((ROOT/'collector_agent/examples/query_templates.json').read_text(encoding='utf-8'))
 def test_paper_tiers_do_not_accept_an_overloaded_easy(self):
  t=copy.deepcopy(self.examples[0]);t['additional_constraints']*=2
  with self.assertRaises(ValueError):validate_cohort([t])
  self.assertTrue(validate_cohort(self.examples)['schema_ok'])
 def test_model_human_style_cannot_claim_human_authored_without_source(self):
  t=copy.deepcopy(self.examples[2]);t['task_origin']='human_authored'
  with self.assertRaises(ValueError):validate_cohort([t])

class MemoryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();p=Path(self.tmp.name)/'agent.sqlite3';self.a=AgentMemory(p);self.b=AgentMemory(p)
  self.a.merge_source({'family':'trip_group','domains':['you.ctrip.com','m.trip.com'],'status':'accessible','live_fetch_authorized':True,'supports':['identity'],'min_interval_seconds':0})
  self.a.merge_source({'family':'example.org','domains':['example.org'],'status':'accessible','live_fetch_authorized':True,'supports':['identity'],'min_interval_seconds':0})
  self.a.begin_run('R',{'web_action':1,'api_http':0})
 def tearDown(self):self.a.close();self.b.close();self.tmp.cleanup()
 def test_pause_is_shared_and_survives_new_success_profile(self):
  self.a.reserve('R','q1','https://you.ctrip.com/a','web_action',field='identity');self.a.finish('q1','challenge',evidence_file='synthetic-challenge.txt')
  self.b.merge_source({'family':'trip_group','status':'accessible','supports':['identity']})
  self.assertFalse(self.b.source_check('https://m.trip.com/a','identity')['allowed'])
 def test_connection_error_pauses_whole_family(self):
  self.a.reserve('R','q1','https://you.ctrip.com/a','web_action',field='identity')
  self.a.finish('q1','connection_error',error='synthetic connection failure')
  self.assertFalse(self.b.source_check('https://m.trip.com/a','identity')['allowed'])
 def test_family_members_require_explicit_host_and_strict_url(self):
  for url in ('https://ctrip.com/a','https://trip.com/a','http://you.ctrip.com/a',
              'https://you.ctrip.com:8443/a','https://you.ctrip.com../a',
              'https://you.ctrip.com/a\nb'):
   with self.subTest(url=url):self.assertFalse(self.a.source_check(url,'identity')['allowed'])
  self.assertFalse(self.a.source_check('https://you.ctrip.com/a','identity',action='export')['allowed'])
  self.assertTrue(self.a.source_check('https://you.ctrip.com/a','identity')['allowed'])
  self.a.merge_source({'family':'trip_group','live_fetch_authorized':False})
  self.assertFalse(self.a.source_check('https://you.ctrip.com/a','identity')['allowed'])
 def test_tls_handshake_failure_pauses_family(self):
  self.a.reserve('R','q1','https://you.ctrip.com/a','web_action',field='identity')
  self.a.finish('q1','failed',error='TLS handshake aborted')
  self.assertFalse(self.b.source_check('https://m.trip.com/a','identity')['allowed'])
 def test_legacy_failed_with_transport_detail_is_upgraded_to_connection_error(self):
  self.a.reserve('R','q1','https://you.ctrip.com/a','web_action',field='identity')
  self.a.finish('q1','failed',error='ConnectionResetError(10054): connection forcibly closed by remote host')
  status=self.a.db.execute('select status from requests where id=?',('q1',)).fetchone()[0]
  self.assertEqual(status,'connection_error')
  self.assertFalse(self.b.source_check('https://m.trip.com/a','identity')['allowed'])
 def test_generic_parser_failure_remains_generic_and_does_not_pause_source(self):
  self.a.reserve('R','q1','https://example.org/a','web_action',field='identity')
  self.a.finish('q1','failed',error='parser failed to extract price')
  status=self.a.db.execute('select status from requests where id=?',('q1',)).fetchone()[0]
  self.assertEqual(status,'failed')
  self.assertTrue(self.b.source_check('https://example.org/a','identity')['allowed'])
 def test_historical_pause_survives_reopen_and_accessible_merge(self):
  self.a.merge_source({'family':'historic.example','status':'paused','pause_evidence':['legacy-ledger:403']})
  self.a.close();self.b.close()
  self.a=AgentMemory(self.tmp.name+'/agent.sqlite3');self.b=AgentMemory(self.tmp.name+'/agent.sqlite3')
  self.b.merge_source({'family':'historic.example','status':'accessible','supports':['identity']})
  self.assertFalse(self.a.source_check('https://www.historic.example/item','identity')['allowed'])
 def test_source_merge_preserves_caller_transaction(self):
  self.a.db.execute('begin immediate');self.a.merge_source({'family':'example.org','status':'paused'})
  self.assertTrue(self.a.db.in_transaction);self.a.db.execute('rollback')
  self.assertTrue(self.b.source_check('https://example.org/a','identity')['allowed'])
 def test_family_lease_stops_second_worker_before_dispatch(self):
  self.a.begin_run('R2',{'web_action':2});self.a.reserve('R','q1','https://you.ctrip.com/a','web_action',field='identity')
  with self.assertRaisesRegex(ValueError,'leased'):self.b.reserve('R2','q2','https://m.trip.com/b','web_action',field='identity')
 def test_shared_budget_reservation_is_atomic_across_connections(self):
  self.a.merge_source({'family':'other.example','domains':['other.example'],'status':'accessible','live_fetch_authorized':True,'supports':['identity'],'min_interval_seconds':0})
  db_path=self.tmp.name+'/agent.sqlite3'
  def attempt(args):
   url,request_id=args;memory=AgentMemory(db_path)
   try:return memory.reserve('R',request_id,url,'web_action',field='identity')['allowed']
   except ValueError:return False
   finally:memory.close()
  with ThreadPoolExecutor(max_workers=2) as pool:
   results=list(pool.map(attempt,[('https://example.org/a','q1'),('https://other.example/b','q2')]))
  self.assertEqual(results.count(True),1)
  self.assertEqual(self.a.db.execute("select count(*) from requests where status='reserved'").fetchone()[0],1)
 def test_global_budget_and_failed_calls_stay_spent(self):
  self.a.reserve('R','q1','https://you.ctrip.com/a','web_action',field='identity');self.a.finish('q1','failed')
  with self.assertRaisesRegex(ValueError,'budget'):self.b.reserve('R','q2','https://example.org/b','web_action',field='identity')
 def test_field_capability_cannot_be_bypassed(self):
  self.assertFalse(self.a.source_check('https://example.org/a','inventory')['allowed'])
  self.assertFalse(self.a.source_check('https://example.org/a')['allowed'])
 def test_finish_once_and_api_budget_zero(self):
  self.a.reserve('R','q1','https://example.org/a','web_action',field='identity');self.a.finish('q1','success')
  with self.assertRaises(ValueError):self.a.finish('q1','success')
  with self.assertRaisesRegex(ValueError,'budget'):self.a.reserve('R','q2','https://example.org/a','api_http',field='identity')
 def test_lessons_require_evidence_and_recall_is_literal(self):
  with self.assertRaises(ValueError):self.a.add_lesson({'id':'bad'})
  self.a.add_lesson({'id':'good','topic':'scope','rule':'keep twin room scope','evidence_paths':['fixture']})
  self.assertEqual(len(self.a.recall('twin')),1);self.assertEqual(self.a.recall("' OR 1=1 --"),[])

if __name__=='__main__':unittest.main(verbosity=2)
