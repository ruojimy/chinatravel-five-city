"""Run official frozen-sandbox controls or independent LLM intent compilations."""
import argparse,contextlib,io,json,sys,time
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p23_scaled_llm'
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'ChinaTravel')]
from shorttrip.env import get_env
from shorttrip.planner import SkeletonPlanner,PlannerOptions
from shorttrip.intent_planner import IntentPlanner
from shorttrip.intent_planner_v2 import IntentPlannerV2
from shorttrip.checker import check_plan

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--split',required=True,choices=['easy','medium','human','competition_test']);parser.add_argument('--arm',required=True,choices=['control','participant','retrieval_only','optimized']);args=parser.parse_args()
    if args.split=='competition_test' and args.arm!='control':parser.error('competition_test has no participant sample; use --arm control')
    lang='en' if args.split=='competition_test' else 'zh'
    env=get_env(lang);queries=[];intents={}
    if args.arm=='control':queries=[read(p) for p in sorted((ROOT/'ChinaTravel/chinatravel/data'/args.split).glob('*.json'))]
    else:
        queries=read(OUT/'private'/args.split/'queries.json')
        rows=read(OUT/('intents_v2' if args.arm in ('optimized','retrieval_only') else 'intents')/(args.split+'.json'));intents={x['uid']:x for x in rows}
        assert len(rows)==len(intents)==50 and set(intents)=={q['uid'] for q in queries},'participant output incomplete'
    results=[];began=time.time()
    for n,q in enumerate(queries,1):
        uid=q['uid'];respath=OUT/'evaluations'/args.arm/args.split/(uid+'.json');planpath=OUT/'plans'/args.arm/args.split/(uid+'.json')
        if respath.exists():results.append(read(respath));continue
        start=time.time();plan=None;error=None;trace=[]
        public={k:q[k] for k in ('uid','start_city','target_city','days','people_number','nature_language')}
        try:
            planner=SkeletonPlanner(env,PlannerOptions(max_combos=6)) if args.arm=='control' else (IntentPlannerV2 if args.arm=='optimized' else IntentPlanner)(env,intents[uid])
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                built=planner.build(public,deep_check=False) if args.arm=='control' else planner.build_proposal(public)
            plan=built.plan
            if not plan:error=planner.last_reason or 'no plan materialized'
            trace=getattr(planner,'retrieval_events',[])
        except Exception as exc:error=type(exc).__name__+': '+str(exc)
        if plan:save(planpath,plan)
        report=check_plan(q,plan or {},lang=lang).to_dict()
        result={'uid':uid,'split':args.split,'lang':lang,'arm':args.arm,'proposal_delivered':bool(plan),
                'official':report,'error':error,'elapsed_s':round(time.time()-start,3),
                'no_oracle_to_planner':True,'live_api_calls':0,'at':datetime.now(timezone.utc).isoformat()}
        save(respath,result)
        if trace:save(OUT/'tool_events'/args.arm/args.split/(uid+'.json'),trace)
        if args.arm=='optimized':save(OUT/'search_history'/args.split/(uid+'.json'),getattr(planner,'search_history',[]))
        results.append(result)
        if n%10==0:print(json.dumps({'split':args.split,'arm':args.arm,'done':n,'total':len(queries),'delivered':sum(r['proposal_delivered'] for r in results),'all_pass':sum(r['official']['all_ok'] for r in results),'elapsed_s':round(time.time()-began,1)}),flush=True)
    summary={'split':args.split,'lang':lang,'arm':args.arm,'queries':len(queries),'delivered':sum(r['proposal_delivered'] for r in results),'schema_pass':sum(r['official']['schema_ok'] for r in results),'commonsense_pass':sum(r['official']['commonsense_ok'] for r in results),'hard_pass':sum(all(r['official']['hard_results']) and r['proposal_delivered'] for r in results),'all_pass':sum(r['official']['all_ok'] for r in results),'runtime_errors':sum(bool(r['error']) for r in results),'seconds':round(time.time()-began,1)}
    save(OUT/'aggregates'/(args.arm+'_'+args.split+'.json'),summary);print(json.dumps(summary),flush=True)

if __name__=='__main__':main()
