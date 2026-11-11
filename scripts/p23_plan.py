"""Compile a public query and supplied LLM intent with the P23 delivery policy.

This entry point does not call an LLM, inspect hidden labels, or grade proposals.
Saved intent files make the delivered experiment reproducible without API keys.
"""
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'), str(ROOT/'ChinaTravel')]
from shorttrip.env import get_env
from shorttrip.intent_planner import IntentPlanner

def select(path, uid):
    value=json.loads(path.read_text(encoding='utf-8'))
    if isinstance(value, list):
        matches=[r for r in value if r.get('uid')==uid]
        if len(matches)!=1: raise ValueError('--uid must identify exactly one row in each input list')
        return matches[0]
    if uid is not None and value.get('uid')!=uid: raise ValueError('UID mismatch')
    return value

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--query',type=Path,required=True);p.add_argument('--intent',type=Path,required=True)
    p.add_argument('--uid');p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists(): p.error('output already exists; choose a new output path')
    query=select(args.query,args.uid);intent=select(args.intent,args.uid)
    if query.get('uid')!=intent.get('uid'): p.error('query and intent UID mismatch')
    planner=IntentPlanner(get_env('zh'),intent)
    result=planner.build_proposal(query)
    if not result.plan: raise RuntimeError(planner.last_reason or 'proposal construction failed')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result.plan,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'uid':query['uid'],'output':str(args.output.resolve()),'policy':'retrieval_only',
                      'official_grade_performed':False,'live_api_calls':0},ensure_ascii=False))

if __name__=='__main__':main()
