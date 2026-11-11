"""Audit P23 stored evidence and independently regrade three regenerated plans."""
import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p23_scaled_llm'
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'ChinaTravel')]
from shorttrip.checker import check_plan

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
    freeze=read(OUT/'private/freeze.json')
    for path,h in freeze['files'].items():check('initial_freeze:'+path,digest(ROOT/path)==h)
    for split in ('easy','medium','human'):
        first=OUT/'intents'/(split+'.json');frozen=read(OUT/'private'/('first_intent_hash_'+split+'.json'))
        check('first_intent_immutable:'+split,digest(first)==frozen['sha256'])
        public=read(OUT/'public'/split/'queries.json');allowed={'uid','start_city','target_city','days','people_number','nature_language','retrieved_candidates'}
        check('public_query_allowlist:'+split,all(set(q)<=allowed and 'hard_logic_py' not in json.dumps(q) for q in public))
        query={q['uid']:q for q in public}
        supplement={q['uid']:q for q in read(OUT/'public_v2'/split/'supplement.json')}
        check('supplement_public_fields:'+split,all(set(q)<= {'uid','nature_language','additional_candidates','scope'} for q in supplement.values()))
        for folder in ('intents','intents_v2'):
            rows=read(OUT/folder/(split+'.json'));check('intent_uid_coverage:'+folder+':'+split,len(rows)==50 and {r['uid'] for r in rows}==set(query))
            issues=[]
            for r in rows:
                for kind,fields in [('attractions',('required_attractions','preferred_attractions')),('restaurants',('required_restaurants','preferred_restaurants')),('hotels',('hotel_names',))]:
                    names={v['name'] for v in query[r['uid']]['retrieved_candidates'][kind]}
                    if folder=='intents_v2':names.update(v['name'] for v in supplement[r['uid']]['additional_candidates'][kind])
                    issues.extend({'uid':r['uid'],'field':field,'name':name} for field in fields for name in r.get(field,[]) if name not in names)
            check('selected_names_in_candidates:'+folder+':'+split,not issues,issues)
    summary=read(OUT/'summary.json')
    evals=[read(p) for p in (OUT/'evaluations').glob('*/*/*.json')]
    check('all_attempts_covered',len(evals)==1154==summary['evaluation_attempts'])
    check('delivered_plans_count',len(list((OUT/'plans').glob('*/*/*.json')))==1148==summary['delivered_plans'])
    check('zero_live_api_calls',all(r['live_api_calls']==0 for r in evals))
    check('proposal_before_official_grading_marker',all(r['no_oracle_to_planner'] for r in evals),'Code/role evidence; not an OS-level access proof')
    for a in summary['aggregates']:
        records=[r for r in evals if r['arm']==a['arm'] and r['split']==a['split']]
        check('aggregate_reconciled:'+a['arm']+':'+a['split'],len(records)==a['queries'] and sum(r['official']['all_ok'] for r in records)==a['all_pass'])
    for stage in ('p21_flash_fixed','p22_adaptive_delivery'):
        manifest=read(OUT.parent/stage/'manifest.json');base=Path(manifest['path_base']);bad=[]
        for row in manifest['files']:
            p=base/row['file']
            if not p.exists() or digest(p)!=row['sha256']:bad.append(row['file'])
        check('historical_manifest:'+stage,not bad,{'files':len(manifest['files']),'mismatches':bad})
    amendments=[]
    for path,h in read(OUT/'private/implementation_snapshot.json')['files'].items():
        actual=digest(ROOT/path)
        amendments.append({'file':path,'intermediate_sha256':h,'final_sha256':actual,'changed':h!=actual})
    save(OUT/'implementation_amendments.json',{'files':amendments,'notes':[
        'Initial public packets/protocol/selection remain frozen. This is an evolving engineering experiment, not a fully preregistered trial.',
        'Runner gained retrieval_only (same V1 planner as participant) and a guard against unsupported phase2 participant runs.',
        'Experimental V2 added semantic field coverage penalty before optimized generation; source intermediate snapshot precedes that amendment.',
        'After optimized generation, unit tests removed an implicit metro penalty for absent mode_preference. All 300 recorded intents have explicit mode_preference, so stored-run behavior is unchanged.',
        'Analysis, validation and a generic V1 CLI were added after generation; no saved proposals were altered.']})
    rows=[r for split in ('easy','medium','human') for folder in ('intents','intents_v2') for r in read(OUT/folder/(split+'.json'))]
    check('V2_default_mode_amendment_inactive_for_recorded_intents',len(rows)==300 and all(r.get('mode_preference') for r in rows))
    examples=[('easy','m20241028164833637716'),('medium','e20241028161042873410'),('human','h20241029143909714190')]
    example_reports=[]
    for split,uid in examples:
        p=OUT/'examples'/(split+'_reproduced.json');original=OUT/'plans/retrieval_only'/split/(uid+'.json')
        check('independent_CLI_plan_hash:'+split,digest(p)==digest(original))
        q=next(q for q in read(OUT/'private'/split/'queries.json') if q['uid']==uid)
        report=check_plan(q,read(p),lang='zh').to_dict()
        check('regenerated_example_official_gates:'+split,report['all_ok'])
        example_reports.append({'split':split,'uid':uid,'report':report})
    save(OUT/'examples/official_recheck.json',example_reports)
    unit=(OUT/'logs/unit_tests.log').read_text(encoding='utf-8-sig')
    check('unit_test_log', 'Ran 7 tests' in unit and '\nOK' in unit)
    policy=read(OUT/'recommended_policy.json')
    check('one_fixed_policy_no_per_UID_oracle',policy['arm']=='retrieval_only' and not policy['cost_repair_enabled'] and not policy['per_case_oracle_selection'])
    receipt={'at':datetime.now(timezone.utc).isoformat(),'all_pass':all(c['pass'] for c in checks),'checks':checks,
        'scope':'Implementation/evidence consistency and three official regrades; not reality validation or full new LLM rerun'}
    save(OUT/'validation.json',receipt)
    print(json.dumps({'all_pass':receipt['all_pass'],'checks':len(checks),'failed':[c for c in checks if not c['pass']]},ensure_ascii=True))
    if not receipt['all_pass']:raise SystemExit(1)

if __name__=='__main__':main()
