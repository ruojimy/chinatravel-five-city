"""Replay all 54 saved P7 plans with matching disabled; no stored result changes."""
from pathlib import Path
import sys,json,hashlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'ChinaTravel'))
from shorttrip.env import get_env
from shorttrip.planner import PlannerOptions,SkeletonPlanner
from shorttrip.checker import check_plan

def main():
    source=ROOT/'results/p7_human_evaluation/pools.json'
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    pools=json.loads(source.read_text(encoding='utf-8'))['pools'];env=get_env('zh');rows=[]
    windows={'early':(420,660),'mid':(480,780),'late':(540,840)}
    for pool in pools:
        path=ROOT/f'ChinaTravel/chinatravel/data/easy_short/{pool["uid"]}.json'
        query=json.loads(path.read_text(encoding='utf-8'))
        for index,candidate in enumerate(pool['candidates']):
            c=candidate['config']
            options=PlannerOptions(max_attractions_per_day=c['attractions_per_day'],go_window=windows[c['window']],order_by=c['order_by'],prefer_mode=c['mode'])
            result=SkeletonPlanner(env,options).build(query,deep_check=False)
            report=check_plan(query,result.plan) if result.plan else None
            rows.append({'uid':pool['uid'],'candidate':index,'exact_plan_equal':result.plan==candidate['plan'],
                         'official_all_ok':report.all_ok if report else False})
    unchanged=hashlib.sha256(source.read_bytes()).hexdigest()==before
    summary={'historical_plans':len(rows),'exact_equal':sum(r['exact_plan_equal'] for r in rows),
             'official_pass':sum(r['official_all_ok'] for r in rows),'historical_source_unchanged':unchanged,'source_sha256':before,'rows':rows}
    out=ROOT/'results/p10_tag_matching/baseline_regression.json'
    out.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='rows'},ensure_ascii=False))
    if not unchanged or any(not r['exact_plan_equal'] or not r['official_all_ok'] for r in rows):raise SystemExit(1)

if __name__=='__main__':main()
