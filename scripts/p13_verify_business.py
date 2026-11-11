"""Serial offline regression + real snapshot audit, all outputs retained."""
from pathlib import Path
import collections,gzip,hashlib,json,os,re,sqlite3,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_completion import validate_room_offer,complete_native,validate_operator_field,details
from shorttrip.expansion_contract import validate_record,validate_evidence
from shorttrip.freshness import utcnow
from shorttrip.travel_catalog import digest_file
OUT=ROOT/'results/p13_business_completion';DATA=ROOT/'data/business_catalog_v1_2_20261022'
def main():
    env=os.environ|{'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8','BAIDU_REQUEST_BUDGET':'0','BAIDU_OFFLINE':'1'}
    runs=[]
    for name in ('business_archives','business_crawler','business_completion','expansion_contract',
                 'expansion_store','legacy_load_gates','freshness_live'):
        r=subprocess.run([sys.executable,'tests/test_'+name+'.py'],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8')
        log=r.stdout+'\n'+r.stderr;(OUT/('test_'+name+'.log')).write_text(log,encoding='utf-8')
        n=re.search(r'Ran (\d+) tests?',log);runs.append({'test':name,'exit_code':r.returncode,'count':int(n[1]) if n else None})
    db=sqlite3.connect((DATA/'catalog.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
    bad=[];counts=collections.Counter();api=collections.Counter();completeness=collections.Counter()
    for rid,payload in db.execute('SELECT id,payload FROM records'):
        record=json.loads(payload);gate=validate_record(record);counts['records']+=1
        counts['planning_ready']+=gate['planning_ready']
        if not gate['discovery_ok']:bad.append({'id':rid,'errors':gate['errors']})
        if complete_native(record):completeness[record['kind']]+=1
        if rid.startswith('amap:'):
            api['records']+=1
            for key in ('price','cuisine','opentime','endtime'):
                if record['data'].get(key) is not None:api[key]+=1
            for key in ('opentime_today','opentime_week'):
                if record.get('business_rules',{}).get(key):api['raw_'+key]+=1
    evidence_ids=set()
    for eid,payload in db.execute('SELECT id,payload FROM evidence'):
        gate=validate_evidence(json.loads(payload));evidence_ids.add(eid)
        if not gate['ok']:bad.append({'evidence_id':eid,'errors':gate['errors']})
    for rid,payload in db.execute('SELECT id,payload FROM records'):
        record=json.loads(payload)
        for key,p in record['field_provenance'].items():
            if p.get('evidence_id') and p['evidence_id'] not in evidence_ids:bad.append({'id':rid,'field':key,'unresolved_evidence':p['evidence_id']})
    offers=[];screenshot_count=0
    for payload, in db.execute('SELECT payload FROM room_offers'):
        offer=json.loads(payload);gate=validate_room_offer(offer,now=utcnow())
        if not gate['ok']:bad.append({'offer':offer['offer_id'],'errors':gate['errors']})
        for item in offer['screenshot_evidence']:
            screenshot_count+=1
            if digest_file(OUT/item['path'])!=item['sha256']:bad.append({'screenshot':item['path']})
        offers.append({'hotel':offer['hotel_name'],'price':offer['price_breakdown']['displayed_stay_total'],
            'bed_count':offer['bed_count'],'current_gate':gate})
    for payload, in db.execute('SELECT payload FROM official_operator_fields'):
        gate=validate_operator_field(json.loads(payload))
        if not gate['ok']:bad.append(gate)
    integrity=db.execute('PRAGMA integrity_check').fetchone()[0];db.close()
    p12_manifest=json.loads((ROOT/'data/expansion_catalog_v1_1_20261022/manifest.json').read_text(encoding='utf-8'))
    originals=json.loads((ROOT/'data/catalog_v1_1_20261022/manifest.json').read_text(encoding='utf-8'))
    unchanged=all(digest_file(ROOT/x['file'])==x['sha256'] for x in originals['source_files'])
    before=json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))['original_p12_sha256']
    packet=ROOT/'results/p12_expansion/blind_packet';frozen=json.loads((packet/'manifest.json').read_text(encoding='utf-8'))
    blind_unchanged=all(digest_file(packet/name)==h for name,h in frozen['files'].items())
    result={'verified_at':utcnow(),'test_runs':runs,'total_tests':sum(r['count'] or 0 for r in runs),
      'unit_tests_pass':all(r['exit_code']==0 for r in runs),'counts':dict(counts),'concrete_api_fields':dict(api),
      'native_operational_complete':dict(completeness),'evidence_count':len(evidence_ids),
      'schema_and_reference_errors':bad,'sqlite_integrity':integrity,'all_264_original_files_unchanged':unchanged,
      'p12_database_unchanged':digest_file(ROOT/'data/expansion_catalog_v1_1_20261022/catalog.sqlite3')==before,
      'p12_blind_packet_unchanged':blind_unchanged,'room_offers':offers,'screenshot_references_checked':screenshot_count,
      'offline_network_calls':0,'model_calls':0,'new_human_labels':0,'real_world_accuracy':None,
      'business_doubling_completed':False,'online_calls_saved':None}
    result['all_checked_pass']=result['unit_tests_pass'] and not bad and integrity=='ok' and unchanged and result['p12_database_unchanged'] and blind_unchanged
    (OUT/'final_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('total_tests','all_checked_pass','counts','concrete_api_fields','native_operational_complete','all_264_original_files_unchanged')},ensure_ascii=False))
    if not result['all_checked_pass']:raise SystemExit(1)
if __name__=='__main__':main()
