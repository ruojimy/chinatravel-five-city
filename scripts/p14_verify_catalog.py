"""Offline full-record + auxiliary graph and immutable-input audit."""
import collections,json,re,sqlite3,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.expansion_contract import validate_record,validate_evidence,validate_tag
from shorttrip.business_completion import validate_room_offer,complete_native,details
from shorttrip.scoped_business import validate_hours
from shorttrip.travel_catalog import digest_file
from shorttrip.freshness import utcnow
RES=ROOT/'results/p14_targeted_completion';DATA=ROOT/'data/business_catalog_v1_4_20261022'
def main():
    tests=json.loads((RES/'test_runs.json').read_text())
    r=subprocess.run([sys.executable,str(ROOT/'tests/test_expansion_store.py')],capture_output=True,text=True,encoding='utf-8')
    log=r.stdout+'\n'+r.stderr;(RES/'test_expansion_store.log').write_text(log,encoding='utf-8');n=re.search(r'Ran (\d+) tests?',log)
    tests=[x if x['test']!='expansion_store' else {'test':'expansion_store','exit_code':r.returncode,'count':int(n[1])} for x in tests]
    db=sqlite3.connect((DATA/'catalog.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
    bad=[];counts=collections.Counter();coverage=collections.Counter();complete=collections.Counter();evs={}
    for eid,payload in db.execute('SELECT id,payload FROM evidence'):
        e=json.loads(payload);evs[eid]=e
        if not validate_evidence(e)['ok']:bad.append({'evidence':eid})
    for rid,payload in db.execute('SELECT id,payload FROM records'):
        x=json.loads(payload);g=validate_record(x);counts['records']+=1;counts['planning_ready']+=g['planning_ready']
        if not g['discovery_ok']:bad.append({'record':rid,'errors':g['errors']})
        complete[x['kind']]+=complete_native(x)
        for key in ('price','cuisine','opentime','endtime','recommendmintime','recommendmaxtime','numbed'):
            if key in x['data']:coverage[x['kind']+':'+key]+=x['data'][key] is not None
        for p in x['field_provenance'].values():
            if p.get('evidence_id'):
                e=evs.get(p['evidence_id'])
                if not e or any(p.get(k)!=e.get(k) for k in ('source_id','source_url','observed_at')):bad.append({'field_graph':rid})
        for tag in x['tags']:
            if not validate_tag(tag)['ok'] or tag.get('evidence_id') and tag['evidence_id'] not in evs:bad.append({'tag_graph':rid})
        if 'today_hours_structured' in x:
            h=x['today_hours_structured'];counts['structured_hours']+=1;e=evs.get(h.get('evidence_id'))
            if not validate_hours(h,require_provenance=True)['ok'] or not e or any(h.get(k)!=e.get(k) for k in ('source_id','source_url','observed_at','retrieved_at','source_updated_at')):bad.append({'hours_graph':rid})
    offers=[];screenshots=set()
    for payload, in db.execute('SELECT payload FROM room_offers'):
        offer=json.loads(payload);g=validate_room_offer(offer,now=utcnow())
        if not g['ok']:bad.append({'offer':offer['offer_id'],'errors':g['errors']})
        for shot in offer['screenshot_evidence']:
            p=ROOT/shot['path']
            if not p.exists():p=ROOT/'results/p13_business_completion'/shot['path']
            if not p.exists() or digest_file(p)!=shot['sha256']:bad.append({'screenshot':shot['path']})
            screenshots.add(str(p))
        offers.append({'id':offer['offer_id'],'hotel':offer['hotel_name'],'gate':g})
    for rid,payload,eid in db.execute('SELECT entity_id,payload,evidence_id FROM historical_references'):
        if eid not in evs:bad.append({'history_evidence':eid})
    old=json.loads((ROOT/'data/catalog_v1_1_20261022/manifest.json').read_text(encoding='utf-8'))
    unchanged=all(digest_file(ROOT/x['file'])==x['sha256'] for x in old['source_files'])
    manifest=json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))
    old_unchanged=digest_file(ROOT/'data/business_catalog_v1_2_20261022/catalog.sqlite3')==manifest['source_v1_2_sha256']
    integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
    history_count=db.execute('SELECT count(distinct entity_id) FROM historical_references').fetchone()[0]
    graph=db.execute('PRAGMA foreign_key_check').fetchall();db.close()
    result={'verified_at':utcnow(),'test_runs':tests,'tests_total':sum(x['count'] for x in tests),
       'tests_pass':all(x['exit_code']==0 for x in tests),'counts':dict(counts),'coverage':dict(coverage),
       'complete_native_records':dict(complete),'evidence_count':len(evs),'issues':bad,
       'offers':offers,'distinct_screenshot_files_checked':len(screenshots),'historical_entities':history_count,
       'sqlite_integrity':integrity,'foreign_key_errors':graph,'all_264_original_files_unchanged':unchanged,
       'v1_2_unchanged':old_unchanged,'no_api_calls':True,'new_local_model_loaded':False}
    result['all_checks_pass']=bool(not bad and not graph and unchanged and old_unchanged and integrity=='ok' and result['tests_pass'])
    (RES/'final_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('tests_total','counts','coverage','historical_entities','all_checks_pass','issues')},ensure_ascii=False))
    if not result['all_checks_pass']:raise SystemExit(1)
if __name__=='__main__':main()
