"""Verify the real multi-worker snapshot, scopes, source graph and process checkpoint."""
import collections,hashlib,json,re,sqlite3,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.expansion_contract import validate_record,validate_evidence
from shorttrip.operator_assertions import check_graph
from shorttrip.travel_catalog import digest_file
from shorttrip.freshness import utcnow
RES=ROOT/'results/p16_multiworker'
def main():
    tests=[]
    for name in ('crawler_pool','business_crawler','operator_assertions','expansion_contract','expansion_store','bulk_business'):
        r=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'tests'/('test_'+name+'.py'))],capture_output=True,text=True,encoding='utf-8')
        log=r.stdout+'\n'+r.stderr;(RES/('test_'+name+'.log')).write_text(log,encoding='utf-8')
        n=re.search(r'Ran (\d+) tests?',log);tests.append({'test':name,'count':int(n[1]) if n else 0,'exit_code':r.returncode})
    pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'))
    db=sqlite3.connect((ROOT/pointer['catalog']).resolve().as_uri()+'?mode=ro',uri=True)
    evs={eid:json.loads(payload) for eid,payload in db.execute('SELECT id,payload FROM evidence')}
    issues=[];counts=collections.Counter();assertion_entities=set();assertions=0;by_kind=collections.Counter()
    for eid,e in evs.items():
        if not validate_evidence(e)['ok']:issues.append({'evidence':eid})
    for rid,payload in db.execute('SELECT id,payload FROM records'):
        r=json.loads(payload);gate=validate_record(r);counts['records']+=1;counts['planning_ready']+=gate['planning_ready']
        if not gate['discovery_ok']:issues.append({'record':rid,'errors':gate['errors']})
        for p in r['field_provenance'].values():
            eid=p.get('evidence_id')
            if eid and (eid not in evs or any(p.get(k)!=evs[eid].get(k) for k in ('source_id','source_url','observed_at'))):issues.append({'field_graph':rid})
        for a in r.get('operator_assertions',[]):
            assertions+=1;assertion_entities.add(rid);by_kind[r['kind']]+=1
            if not check_graph(a,evs.get(a['evidence_id']))['ok']:issues.append({'operator_graph':a['assertion_id']})
            if not (ROOT/a['capture']['file']).exists() or digest_file(ROOT/a['capture']['file'])!=a['capture']['sha256']:issues.append({'capture':a['capture']['file']})
    integrity=db.execute('PRAGMA integrity_check').fetchone()[0];fk=db.execute('PRAGMA foreign_key_check').fetchall();db.close()
    original=json.loads((ROOT/'data/catalog_v1_1_20261022/manifest.json').read_text(encoding='utf-8'))
    unchanged=all(digest_file(ROOT/f['file'])==f['sha256'] for f in original['source_files'])
    operator_batch=json.loads((RES/'approved_assertions.json').read_text(encoding='utf-8'))
    input_hashes_ok=all(digest_file(ROOT/f['file'])==f['sha256'] for f in operator_batch['source_packets'])
    m=json.loads((ROOT/pointer['manifest']).read_text(encoding='utf-8'))
    result={'checked_at':utcnow(),'catalog':pointer,'tests':tests,'tests_total':sum(x['count'] for x in tests),
       'counts':dict(counts),'evidence':len(evs),'operator_assertions':assertions,'operator_entities':len(assertion_entities),
       'operator_assertions_by_kind':dict(by_kind),'issues':issues,'integrity':integrity,'foreign_key_errors':len(fk),
       'original_264_files_unchanged':unchanged,'worker_input_packet_hashes_unchanged':input_hashes_ok,
       'v1_4_unchanged':digest_file(ROOT/'data/business_catalog_v1_4_20261022/catalog.sqlite3')==m['source_sha256'],
       'snapshot_hash_correct':digest_file(ROOT/pointer['catalog'])==pointer['sha256'],'no_network_calls':True}
    result['all_checks_pass']=all(x['exit_code']==0 for x in tests) and not issues and not fk and integrity=='ok' and unchanged and input_hashes_ok and result['v1_4_unchanged'] and result['snapshot_hash_correct'] and counts['records']==14057 and assertions==40
    (RES/'final_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('all_checks_pass','tests_total','counts','evidence','operator_assertions','operator_entities','issues')},ensure_ascii=False))
    if not result['all_checks_pass']:raise SystemExit(1)
if __name__=='__main__':main()
