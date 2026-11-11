"""Audit all P24 cases, replay, profiles, evidence hashes and historical protection."""
import hashlib,json,sys,warnings
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlparse,unquote
from urllib.request import url2pathname
from jsonschema import Draft202012Validator
from referencing import Registry,Resource
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p24_dynamic_feedback'
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.retrieval_benchmark import serve
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
    checks=[]
    def check(name,ok,detail=None):checks.append({'check':name,'pass':bool(ok),'detail':detail})
    freeze=read(OUT/'private/freeze.json');diffs=[]
    for name,h in freeze['files'].items():
        actual=digest(ROOT/name)
        if actual!=h:diffs.append({'file':name,'frozen_sha256':h,'final_sha256':actual})
    check('only_declared_implementation_amended',all(d['file']=='src/shorttrip/retrieval_benchmark.py' for d in diffs),diffs)
    save(OUT/'implementation_amendments.json',{'differences_from_96case_freeze':diffs,'notes':[
        '36 to96 user-requested scaling occurred before any participant input; preliminary files retained in private/pre_scale_*.',
        'V1 empty gateway responses preserved in responses; descriptive metadata matching corrected before any dynamic response was given to a participant. V2 responses replay identically with final implementation.',
        'Legacy sandbox price lookup accepts only exactly supplied old-city frozen values; it does not verify real prices. Amendment occurred after static outputs but before final grading.',
        'Final intercity request city dispatcher accepts either endpoint; exact origin/destination/date remain mandatory. Old516/528 coverage scores retained in evaluations_v1; final528/528. No model output or served response changed.',
        'Additional field-level feedback and time/price change metrics were added after generation without changing proposals.',
        '30city/6chain schema profiles and audit/report scripts added after first output; profile ref paths repaired before delivery. Participant base schema remains frozen.',
        'This is evolving engineering evaluation, not a fully preregistered or blind experiment.']})
    full=read(OUT/'private/queries_96.json');corpus=read(OUT/'private/evidence_corpus.json');summary=read(OUT/'summary.json')
    check('96_scoped_cases',len(full)==96 and len({(q['level'],q['uid']) for q in full})==96)
    check('30_new_cities',len({q['city_sequence'][-1] for q in full})==30)
    check('6_mixed_cases',sum(len(q['city_sequence'])==2 for q in full)==6)
    qvalidator=Draft202012Validator(read(OUT/'public/schemas/query.schema.json'))
    pvalidator=Draft202012Validator(read(OUT/'public/schemas/plan.schema.json'))
    profiles=read(OUT/'profiles/index.json')['profiles']
    check('36_profiles',len(profiles)==36)
    def retrieve(uri):
        parsed=urlparse(uri)
        if parsed.scheme!='file':raise ValueError('Local profile references only')
        return Resource.from_contents(read(Path(url2pathname(parsed.path))))
    registry=Registry(retrieve=retrieve)
    profile_validators={}
    for row in profiles:
        p=OUT/'profiles'/row['profile'];schema=read(p)
        # Resolve relative refs from the actual saved profile URI.
        wrapped={'$schema':schema['$schema'],'$ref':p.as_uri()}
        profile_validators[tuple(row['city_sequence'])]=Draft202012Validator(wrapped,registry=registry)
    for level in ('easy','hard','human'):
        public=read(OUT/'public/levels'/(level+'.json'));private={q['uid']:q for q in full if q['level']==level}
        check('32_public_queries:'+level,len(public)==32 and {q['uid'] for q in public}==set(private))
        check('no_hidden_labels:'+level,all('requirements' not in q and 'hard_logic_py' not in json.dumps(q) for q in public))
        check('public_query_schema:'+level,all(qvalidator.is_valid(q) for q in public))
        receipt=read(OUT/'private'/(level+'_static_receipt_v2.json'))
        check('static_immutable:'+level,digest(OUT/'participants'/(level+'_static.json'))==receipt['sha256'])
        responsepath=OUT/'responses_v2'/(level+'.json')
        check('responses_immutable:'+level,digest(responsepath)==receipt['response_sha256'])
        first={p['uid']:p for p in read(OUT/'participants'/(level+'_static.json'))}
        events=read(responsepath);rebuilt=[{'uid':row['uid'],'events':serve(private[row['uid']],first[row['uid']]['retrieval_requests'],corpus['evidence'])} for row in events]
        check('replay_identical:'+level,all(a['uid']==b['uid'] and a['events']==b['events'] for a,b in zip(events,rebuilt)))
        for stage in ('static','dynamic'):
            plans=read(OUT/'participants'/(level+'_'+stage+'.json'))
            check('output_coverage:'+level+':'+stage,len(plans)==32 and {p['uid'] for p in plans}==set(private))
            check('base_schema:'+level+':'+stage,all(pvalidator.is_valid(p) for p in plans))
            profile_errors=[{'uid':p['uid'],'errors':[e.message for e in profile_validators[tuple(private[p['uid']]['city_sequence'])].iter_errors(p)]} for p in plans]
            check('city_profile:'+level+':'+stage,all(not r['errors'] for r in profile_errors),[r for r in profile_errors if r['errors']])
    for field in ('raw_text','raw_sha256','quote'):
        check('evidence_required:'+field,all(e.get(field) for e in corpus['evidence']))
    check('evidence_raw_hashes_and_quotes',all(hashlib.sha256(e['raw_text'].encode()).hexdigest()==e['raw_sha256'] and e['quote'] in e['raw_text'] for e in corpus['evidence']))
    weather=[e for e in corpus['evidence'] if e['source_id']=='amap']
    check('weather_values_from_actual_casts',all(e['value'] in json.loads(e['raw_text'])['forecasts'][0]['casts'] and e['value']['date']==e['context']['travel_date'] for e in weather))
    check('no_synthetic_evidence',not any(e.get('synthetic') for e in corpus['evidence']))
    ledger=read(OUT/'live/amap_ledger.json');check('6_successful_amap_calls',ledger['spent']==6 and len(ledger['audit'])==6 and all(r['ok'] for r in ledger['audit']))
    check('no_route_or_intercity_injection',not any(e['field'] in ('route_duration','route_fare','intercity_schedule','intercity_fare') for e in corpus['evidence']))
    allrecords=read(OUT/'evaluations/all_96.json');check('all192_evaluations_present',len(allrecords)==96 and all('static' in r and 'dynamic' in r for r in allrecords))
    check('summary_resolution_reconciles',summary['total']['dynamic']['metrics']['resolved_fields']==sum(r['dynamic']['metrics']['resolved_fields'] for r in allrecords)==40)
    check('all_feedback_coverage_reconciles',summary['total']['dynamic']['metrics']['reviewed_evidence']==summary['gateway']['evidence_deliveries']==59)
    check('no_false_full_completion',sum(r['dynamic']['complete'] for r in allrecords)==0)
    protocol=read(OUT/'protocol.json');check('formal_catalog_unchanged',digest(ROOT/protocol['baseline_db'])==protocol['baseline_sha256'])
    for old in ('p21_flash_fixed','p22_adaptive_delivery','p23_scaled_llm'):
        m=read(OUT.parent/old/'manifest.json');base=Path(m['path_base']);bad=[]
        for row in m['files']:
            if not (base/row['file']).is_file() or digest(base/row['file'])!=row['sha256']:bad.append(row['file'])
        check('historical_manifest:'+old,not bad,{'files':len(m['files']),'mismatches':bad})
    unit=(OUT/'logs/unit_tests.log').read_text(encoding='utf-8-sig');check('23_unit_tests_pass','Ran 23 tests' in unit and '\nOK' in unit)
    receipt={'at':datetime.now(timezone.utc).isoformat(),'all_pass':all(r['pass'] for r in checks),'checks':checks,
        'scope':'Evidence integrity, coverage, profiles and regression checks. Does not certify reality or erase participant failures.'}
    save(OUT/'validation.json',receipt);print(json.dumps({'all_pass':receipt['all_pass'],'checks':len(checks),'failed':[r for r in checks if not r['pass']]},ensure_ascii=True))
    if not receipt['all_pass']:raise SystemExit(1)
if __name__=='__main__':main()
