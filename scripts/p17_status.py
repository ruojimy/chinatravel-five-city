"""Current formal coverage and retained collector checkpoints; no network calls."""
import collections,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.freshness import utcnow
from shorttrip.process_status import observe_pid
def main():
 pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'));db=sqlite3.connect((ROOT/pointer['catalog']).resolve().as_uri()+'?mode=ro',uri=True)
 counters=collections.defaultdict(collections.Counter);assertions=0;properties=set();selected=[]
 for payload, in db.execute('SELECT payload FROM records'):
  r=json.loads(payload);c=counters[r['kind']];c['records']+=1
  for k in ('price','cuisine','numbed','opentime','endtime','recommendmintime','recommendmaxtime'):c['native_nonnull:'+k]+=r['data'].get(k) is not None
  fields={a['field'] for a in r.get('operator_assertions',[])}
  for field in fields:c['scoped_reference:'+field]+=1
  assertions+=len(r.get('operator_assertions',[]));c['excluded_reported_closed']+=bool(r.get('exclude_from_static_planning'))
  for a in r.get('operator_assertions',[]):properties.add(a['source_url'])
  if r.get('selected_room_configuration_assertion_id'):selected.append(r['record_id'])
 collectors={}
 for file in ('attractions/ctrip_status.json','attractions/ingest_status.json','hotels/trip_expand_status.json','hotels/langham_observed_001/status.json','restaurants/feinfood_progress.json','restaurants/hongchumao_progress.json','restaurants/http_transport_progress.json','restaurants/operator_frontier_progress.json'):
  p=ROOT/'results/p17_continuous'/file
  if p.exists():collectors[file]=json.loads(p.read_text(encoding='utf-8'))
 process_checks={file:{'checkpoint_at':value.get('at'),**observe_pid(value.get('pid'))} for file,value in collectors.items() if type(value.get('pid')) is int}
 browser_file=ROOT/'results/p17_continuous/browser/access_20261023_0710.json'
 browser_checkpoint=json.loads(browser_file.read_text(encoding='utf-8')) if browser_file.exists() else None
 result={'checked_at':utcnow(),'formal_catalog':pointer,'coverage':{k:dict(v) for k,v in counters.items()},'operator_assertions':assertions,
  'source_urls_with_assertions':len(properties),'selected_named_room_configurations':len(selected),'stored_room_offers':db.execute('SELECT count(*) FROM room_offers').fetchone()[0],
  'planning_ready':db.execute('SELECT count(*) FROM records WHERE planning_ready=1').fetchone()[0],
  'collector_checkpoints_not_live_process_proof':collectors,'process_observations':process_checks,
  'runtime_note':'Read-only PID observation does not verify command identity or prove outbound collection; checkpoints retain their own timestamps.',
  'browser_access_checkpoint_not_live_check':browser_checkpoint,
  'full_completion':False,'network_requests':0}
 evaluation_file=ROOT/'results/p20_deepseek_dynamic_sandbox/current_evaluation.json'
 if not evaluation_file.exists():evaluation_file=ROOT/'results/p19_query_to_plan/current_evaluation.json'
 if not evaluation_file.exists():evaluation_file=ROOT/'results/p18_dynamic_eval/current_evaluation.json'
 if evaluation_file.exists():
  result['evaluation_checkpoint']=json.loads(evaluation_file.read_text(encoding='utf-8'))
  result['broad_static_collection_paused_by_user_pivot']=result['evaluation_checkpoint'].get('broad_static_collection_paused',False)
 out=ROOT/'results/p17_continuous/current_status.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');db.close()
 print(json.dumps({k:v for k,v in result.items() if k!='collector_checkpoints_not_live_process_proof'},ensure_ascii=False))
if __name__=='__main__':main()
