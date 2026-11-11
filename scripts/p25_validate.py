"""Audit guarded outcomes, fixed witness, live refresh and previous immutable runs."""
import copy,hashlib,json,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p25_reliable_retrieval'
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.retrieval_guard import evaluate,gate
from p25_run import gateway
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
    cases=read(OUT/'private/cases.json');now=read(OUT/'real/corpus.json')['captured_at']
    check('24_case_keys',len(cases)==len({(c['level'],c['uid']) for c in cases})==24)
    check('9positive15negative',sum(c['expected_policy_accepted'] for c in cases)==9)
    records=[]
    for level in ('easy','hard','human'):
        cs={c['uid']:c for c in cases if c['level']==level};receipt=read(OUT/'private'/(level+'_receipt.json'))
        static=OUT/'participants'/(level+'_static.json');responses=OUT/'responses'/(level+'.json')
        check('static_immutable:'+level,digest(static)==receipt['static_sha256'])
        check('responses_immutable:'+level,digest(responses)==receipt['responses_sha256'])
        first=read(static);response_map={r['uid']:r['events'] for r in read(responses)}
        check('gateway_replays_identically:'+level,all(gateway(cs[p['uid']]['query'],p['retrieval_requests'],cs[p['uid']]['evidence'],now)==response_map[p['uid']] for p in first))
        dynamic=read(OUT/'participants'/(level+'_dynamic.json'));check('8_dynamic_outputs:'+level,len(dynamic)==8 and {p['uid'] for p in dynamic}==set(cs))
        rows=read(OUT/'evaluations'/(level+'.json'));records.extend(rows)
        check('correct_typed_outcomes:'+level,all(r['outcome_correct'] for r in rows))
        check('no_unsafe_projected_output:'+level,all(r['guarded_check']['safe'] for r in rows))
        check('positive3_negative5:'+level,sum(r['guarded_check']['policy_accepted'] for r in rows)==3)
        check('no_execution_claim:'+level,not any(r['guarded_check']['execution_confirmed'] for r in rows))
    check('fixture_not_reality',all(r['guarded_check']['synthetic_only'] and not r['guarded_check']['execution_confirmed'] for r in records if r['kind']=='known_fixture'))
    check('overbudget_stays_blocked',all('budget_exceeded' in r['guarded_check']['issues'] and not r['guarded_check']['policy_accepted'] for r in records if r['kind']=='over_budget'))
    check('missing_and_estimated_identity_blocked',all(not r['guarded_check']['policy_accepted'] for r in records if r['kind'] in ('missing_identity','identity_estimate')))
    check('wrong_dates_and_unknown_coords_blocked',all(not r['guarded_check']['policy_accepted'] for r in records if r['kind'] in ('wrong_date','missing_coordinates')))
    regress=read(OUT/'regression/results_96.json')
    check('96_original_cases_projected_safely',len(regress)==96 and all(r['guarded_check']['safe'] for r in regress))
    check('no_fabricated_96_completion',not any(r['guarded_check']['policy_accepted'] for r in regress))
    d=read(OUT/'DELIVERABLE.json');case=next(c for c in cases if c['level']=='easy' and c['uid']=='E02')
    check('delivery_query_is_fixed_preselected_case',d['query']==case['query'] and d['query']['uid']==d['plan']['uid'])
    check('delivery_request_budget_matches_input',len(d['plan']['retrieval_requests'])<=d['query']['retrieval_budget'])
    source_evidence=list({e['evidence_id']:e for event in read(OUT/'responses/easy.json')[1]['events'] for e in event['evidence']}.values())
    # Lookup by UID rather than relying on row order for independent validation.
    source_evidence=list({e['evidence_id']:e for row in read(OUT/'responses/easy.json') if row['uid']=='E02' for event in row['events'] for e in event['evidence']}.values())
    events=next(r['events'] for r in read(OUT/'responses/easy.json') if r['uid']=='E02')
    result=evaluate(d['query'],d['plan'],source_evidence,events,now=now)
    check('base_delivery_independent_recheck',result['policy_accepted'] and result['safe'] and not result['execution_confirmed'])
    check('92_includes_both_group_fares',result['budget']['known_projected_cost']==92)
    latest=read(OUT/'DELIVERABLE_LATEST.json');refresh=read(ROOT/latest['receipt']);current=datetime.now(timezone.utc).isoformat()
    refreshed=evaluate(refresh['query'],refresh['plan'],refresh['evidence'],[{'evidence':refresh['evidence']}],now=current)
    check('refreshed_delivery_valid_at_validation_time',refreshed['policy_accepted'] and refreshed['safe'],{'at':current,'issues':refreshed['issues'],'unmet':refreshed['unmet_requirements']})
    check('refresh_no_fake_execution',not refreshed['execution_confirmed'] and bool(refreshed['prerequisites']))
    check('6_actual_successful_api_calls',len(read(OUT/'real/api_ledger.json')['audit'])==3 and len(refresh['audit'])==3 and all(a['ok'] for a in refresh['audit']))
    check('fresh_values_have_matching_source_digest',all(hashlib.sha256(e['raw_text'].encode()).hexdigest()==e['raw_sha256'] and e['quote'] in e['raw_text'] for e in refresh['evidence']))
    frozen=read(OUT/'private/freeze.json');diffs=[]
    for name,h in frozen['files'].items():
        actual=digest(ROOT/name)
        if actual!=h:diffs.append({'file':name,'frozen_sha256':h,'final_sha256':actual})
    check('only_declared_guard_implementation_changed',all(r['file'].replace('\\','/')=='src/shorttrip/retrieval_guard.py' for r in diffs),diffs)
    save(OUT/'implementation_amendments.json',{'diffs':diffs,'notes':[
        'Added exact route departure/mode and ticket multiplicity checks during integration; initial future dependency on official env fixed by local HH:MM parser.',
        'After model output, added general explicit-ID canonicalization and separated request-status notes from evidence feedback. Raw plans and per-output changes remain saved; no score feedback was sent to participants.',
        'Original raw integration output failed display-name/ID and affected_ids references. Projection is system behavior, not pure LLM improvement.',
        'Delivery metadata initially paired REAL-CS-01/4-request wrapper with E02/6-request plan; corrected to the frozen E02 input. Failed refresh receipt preserved, successful API data reused with no retry calls.',
        'Field policy, numeric safety and query/plan consistency audited; experiment evolved on the same24 focused cases, no held-out claim.']})
    for old in ('p21_flash_fixed','p22_adaptive_delivery','p23_scaled_llm','p24_dynamic_feedback'):
        m=read(OUT.parent/old/'manifest.json');base=Path(m['path_base']);bad=[]
        for row in m['files']:
            p=base/row['file']
            if not p.is_file() or digest(p)!=row['sha256']:bad.append(row['file'])
        check('old_manifest:'+old,not bad,{'files':len(m['files']),'mismatches':bad})
    protocol=read(OUT.parent/'p24_dynamic_feedback/protocol.json')
    check('formal_database_unchanged',digest(ROOT/protocol['baseline_db'])==protocol['baseline_sha256'])
    for name,count in [('guard_tests.log',21),('base_tests.log',23)]:
        text=(OUT/'logs'/name).read_text(encoding='utf-8-sig');check('unit_suite:'+name,'Ran '+str(count)+' tests' in text and '\nOK' in text)
    receipt={'at':current,'all_pass':all(r['pass'] for r in checks),'checks':checks,'scope':'Implementation and fixed-source scenario checks; reservations/execution not certified'}
    save(OUT/'validation.json',receipt)
    print(json.dumps({'all_pass':receipt['all_pass'],'checks':len(checks),'failed':[r for r in checks if not r['pass']]},ensure_ascii=True))
    if not receipt['all_pass']:raise SystemExit(1)
if __name__=='__main__':main()
