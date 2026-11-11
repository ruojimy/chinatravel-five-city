"""Additional pool-only control; preserves the original six treatment outputs."""
import os
os.environ['BAIDU_OFFLINE']='1'
os.environ['BAIDU_REQUEST_BUDGET']='0'
from pathlib import Path
import sys,json,hashlib,time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'ChinaTravel'))
from shorttrip.env import get_env
from shorttrip.planner import SkeletonPlanner,PlannerOptions
from shorttrip.candidate_matching import CandidateMatcher
from p10_sandbox_matching_experiment import stats

def main():
    out=ROOT/'results/p10_tag_matching'
    query=json.loads((ROOT/'ChinaTravel/chinatravel/data/easy_short/e20241028160248698752.json').read_text(encoding='utf-8'))
    query['nature_language']+=' 喜欢自然风光，尽量少等车。'
    manifest={'purpose':'Isolate the expanded 40-place pool from review scoring.',
              'query':query,'max_attractions_per_day':2,'evidence':[],
              'include_routes':False,'applies_to':'Both original scenarios have identical queries and planner options.',
              'domain':'sandbox mechanism control; no visitor-effectiveness claim'}
    (out/'pool_control_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    start=time.monotonic()
    matcher=CandidateMatcher([],include_routes=False)
    result=SkeletonPlanner(get_env('zh'),PlannerOptions(max_attractions_per_day=2),candidate_matcher=matcher).build(query)
    comparisons={}
    for label,folder in [('initial',out),('window_filtered',out/'feasible_case')]:
        baseline=json.loads((folder/'sandbox_baseline.json').read_text(encoding='utf-8'))
        comparisons[label]={'plan_identical_to_original_baseline':result.plan==baseline['plan']}
    payload={'arm':'expanded_pool_no_review_evidence','seconds':round(time.monotonic()-start,3),
             'ok':result.ok,'official_report':result.report.to_dict() if result.report else None,
             'stats':stats(result.plan),'plan':result.plan,'matching_trace':matcher.trace,
             'comparisons':comparisons,'external_api_calls':0}
    (out/'sandbox_pool_control.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in payload.items() if k not in ('plan','matching_trace')},ensure_ascii=False))
    if not result.ok:raise AssertionError('Pool control failed feasibility check')

if __name__=='__main__':main()
