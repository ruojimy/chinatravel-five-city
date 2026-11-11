"""Offline integrity audit and timestamped evidence/question materialization."""
from pathlib import Path
import json,sys,sqlite3
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.freshness import POLICIES,utcnow,uncertainty_question,canonical,sha,reconcile
from shorttrip.travel_catalog import TravelCatalog,digest_file

def load(path):return json.loads(path.read_text(encoding='utf-8'))
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    out=ROOT/'results/p11_freshness_skill';catalog_dir=ROOT/'data/catalog_v1_1_20261022'
    manifest=load(catalog_dir/'manifest.json');registry=load(ROOT/'data/travel_source_registry.json')
    unchanged=all(digest_file(ROOT/f['file'])==f['sha256'] for f in manifest['source_files'])
    catalog=TravelCatalog(catalog_dir/'catalog.sqlite3');total=0;tags=0;bad=0
    try:
        for r in catalog.db.execute('SELECT payload FROM records'):
            record=json.loads(r[0]);total+=1;tags+=len(record['tags'])
            good=(record['observed_at'] is None and record['source_updated_at'] is None and record['valid_until'] is None and
                record['trust_status']=='benchmark_only' and record['catalogued_at'] and record['field_policies'] and
                all(v in POLICIES for v in record['field_policies'].values()) and
                all(t.get('policy_id') in POLICIES and t.get('source_time_ref') for t in record['tags']))
            if not good:bad+=1
        smoke=load(out/'live_api_smoke.json')
        for claim in smoke['claims']:catalog.add_claim(claim)
        check=catalog.db.execute('PRAGMA integrity_check').fetchone()[0]
    finally:catalog.close()
    assert total==manifest['records']==67612 and bad==0 and unchanged and check=='ok'
    questions=[];capture_replay=[]
    for c in smoke['claims']:
        evaluation=reconcile([c],c['field'],registry,now=smoke['recorded_at'],context=c['context'],entity_id=c['entity_id'])
        capture_replay.append({'claim_id':c['claim_id'],'field':c['field'],**evaluation})
        q=uncertainty_question(c['entity_id'],c['field'],evaluation)
        if q:
            q['source_observed_at']=c['observed_at'];q['source_retrieved_at']=c['retrieved_at']
            q['impact']='If making a current outdoor plan, weather cannot be presented as verified current conditions.'
            questions.append(q)
    write(out/'capture_gate_replay_v11.json',{'as_of':smoke['recorded_at'],'replayed_at':utcnow(),
      'not_a_current_revalidation':True,'evaluations':capture_replay})
    write(out/'pending_user_questions.example.json',{'created_at':utcnow(),'domain':'research smoke, not an actual user itinerary',
       'questions':questions,'shown_to_user_as_travel_decision':False,
       'note':'Demonstrates the question contract; do not demand a weather decision for a research-only request.'})
    result={'verified_at':utcnow(),'catalog':str(catalog_dir.relative_to(ROOT)),'source_files':len(manifest['source_files']),
      'records_checked':total,'tag_records':tags,'malformed_metadata_records':bad,'all_source_hashes_unchanged':unchanged,
      'sqlite_integrity':check,'real_api_calls':smoke['api_calls'],'real_api_claims':len(smoke['claims']),
      'weather_stale_rejected_at_capture':any(e['field']=='weather_now' and e['status']=='unverified' for e in smoke['evaluations']),
      'api_provider_stage_only':True,'real_world_accuracies':None,'registry_matches_snapshot':sha(registry)==manifest['source_registry_sha256'],
      'notes':['67612 includes Chinese/English language views, not 67612 independent places.',
               'One route example and one weather observation do not validate all cities or future availability.',
               'Static sidecar is a recall/provenance layer, not 67612 verified real-time facts.']}
    write(out/'catalog_integrity.json',result);print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
