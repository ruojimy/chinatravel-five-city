"""Controlled synthetic-review intervention on unchanged ChinaTravel sandbox.

NOT evidence of real visitor satisfaction or an actual-route review benchmark.
The fixture is saved before any treatment plans, never enters the TAG database.
"""
from pathlib import Path
import sys,json,copy,time
from dataclasses import asdict
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'ChinaTravel'))
from shorttrip.env import get_env
from shorttrip.planner import SkeletonPlanner,PlannerOptions
from shorttrip.planner import _window_allows
from shorttrip.env import minutes
from shorttrip.candidate_matching import CandidateMatcher,extract_evidence

OUT=ROOT/'results/p10_tag_matching'

def stats(plan):
    if not plan:return None
    stops=[];walk=0;cost=0.;modes=[]
    for day in plan['itinerary']:
        for a in day['activities']:
            cost+=float(a.get('cost',0))
            legs=a.get('transports') or []
            for leg in legs:
                cost+=float(leg.get('cost',0))
                if leg['mode']=='walk':
                    def m(s):h,n=map(int,s.split(':'));return h*60+n
                    walk+=m(leg['end_time'])-m(leg['start_time'])
            if a['type']=='attraction':
                stops.append(a['position']);modes.append('taxi' if any(l['mode']=='taxi' for l in legs) else 'metro' if any(l['mode']=='metro' for l in legs) else 'walk')
    return {'attractions':stops,'attraction_access_modes':modes,'walk_minutes':walk,'cost':round(cost,2)}

def main():
    feasible_target='--feasible-target' in sys.argv
    out=OUT/'feasible_case' if feasible_target else OUT
    out.mkdir(parents=True,exist_ok=True)
    path=ROOT/'ChinaTravel/chinatravel/data/easy_short/e20241028160248698752.json'
    query=json.loads(path.read_text(encoding='utf-8'))
    env=get_env('zh');options=PlannerOptions(max_attractions_per_day=2)
    base=SkeletonPlanner(env,options).build(query)
    if not base.plan:raise RuntimeError('No baseline plan')
    initial=stats(base.plan)['attractions'];origin=base.plan['itinerary'][0]['activities'][0]['end']
    table=env.attraction_table(query['target_city'])
    names=SkeletonPlanner(env,options)._ranked(table,query['target_city'],origin,float('inf'))
    # A new reachable, open candidate from the same 40-place search neighbourhood.
    alternatives=[str(r['name']) for r in names[:40] if str(r['name']) not in initial and
        (not feasible_target or _window_allows(r,minutes(base.plan['itinerary'][0]['activities'][0]['end_time']),
                                             max(45,int(round(float(r['recommendmintime'])*60)))))]
    target=next((name for name in alternatives if env.leg_templates(query['target_city'],origin,name,'metro') and env.leg_templates(query['target_city'],origin,name,'taxi')),None)
    if target is None:raise RuntimeError('No dual-mode fixture target')
    fixture=[]
    for index,row in enumerate(names[:40]):
        name=str(row['name'])
        fixture.append({'review_id':f'SYNTHETIC-POI-{index}','poi_hint':name,
                        'text':'The forest has natural beauty. The path is flat.' if name==target else 'This is a historical site.'})
        for mode,waiting in [('metro',40),('taxi',5)]:
            fixture.append({'review_id':f'SYNTHETIC-ROUTE-{index}-{mode}','poi_hint':name,
                'text':f'We waited {waiting} minutes.','route':{'origin':origin,'mode':mode}})
    intent='喜欢自然风光，尽量少等车。'
    manifest={'domain':'SYNTHETIC_REVIEW_INTERVENTION_ON_REAL_SANDBOX','source_query':str(path.relative_to(ROOT)),
        'case':'operating_window_filtered_target' if feasible_target else 'initial_unfiltered_target',
        'intent_added_to_original_query':intent,'target_with_nature_fixture':target,'origin':origin,
        'candidate_pool_limit':40,'expected_local_effect':'Prefer the nature-labelled candidate and, where the scoped evidence applies, the five-minute-wait route.',
        'limitations':'Fixtures intentionally favour one candidate. Mechanism calibration, not preference accuracy or real review validation.',
        'fixture_reviews':fixture}
    (out/'sandbox_intervention_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    q=copy.deepcopy(query);q['nature_language']+=' '+intent
    evidence=[e for r in fixture for e in extract_evidence(r,'synthetic',allow_synthetic=True)]
    results=[]
    arms=[('baseline',None),('poi_only',CandidateMatcher(evidence,include_routes=False,allow_synthetic=True)),
          ('poi_and_route',CandidateMatcher(evidence,include_routes=True,allow_synthetic=True))]
    for arm,matcher in arms:
        start=time.monotonic();planner=SkeletonPlanner(env,options,candidate_matcher=matcher)
        result=planner.build(q)
        payload={'arm':arm,'seconds':round(time.monotonic()-start,3),'ok':result.ok,
                 'official_report':result.report.to_dict() if result.report else None,
                 'matching_report':result.matching_report,'stats':stats(result.plan),
                 'plan':result.plan,'matching_trace':matcher.trace if matcher else []}
        (out/f'sandbox_{arm}.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        results.append({k:v for k,v in payload.items() if k not in ('plan','matching_trace')})
        print(json.dumps(results[-1],ensure_ascii=False),flush=True)
    baseline_replay=SkeletonPlanner(env,options).build(query)
    baseline_unchanged=baseline_replay.plan==base.plan
    summary={'arms':results,'baseline_replay_identical':baseline_unchanged,'fixture_target':target,
             'all_official_checks_pass':all(r['official_report'] and r['official_report']['all_ok'] for r in results),
             'external_api_calls':0,'real_review_preference_accuracy':None,'published_to_tag_store':0}
    (out/'sandbox_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    if not baseline_unchanged:raise AssertionError('Opt-in treatment changed baseline')

if __name__=='__main__':main()
