"""Formal v5 scorer: date and assumption gates plus proven station aliases.

The v4-style result and its underlying base result are written first, unchanged;
the v5 result is a separate write-once file. No submission is ever rewritten.
"""
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import argparse,json,subprocess,sys
from space_gate import validate_space

HERE=Path(__file__).resolve().parent
def digest(path):return sha256(path.read_bytes()).hexdigest()
def verdict(states):return 'fail' if 'fail' in states else 'unknown' if not states or 'unknown' in states else 'pass'

def merge(v4,query,plan,root):
    out=deepcopy(v4);groups=out.get('groups')
    if not isinstance(groups,list):raise ValueError('missing scored gate groups')
    hits=[i for i,g in enumerate(groups) if g.get('name')=='Is_space_correct']
    if len(hits)!=1:raise ValueError('exactly one space gate required')
    ix=hits[0];previous=groups[ix];space=validate_space(query,plan,root)
    out['superseded_space_group']=previous
    groups[ix]={'name':'Is_space_correct','state':space['state'],'issues':space['issues'],
                'station_alias_evidence':space['station_alias_evidence'],'policy':space['policy'],
                'implementation':'station_alias_space_v5'}
    common=verdict([x['state'] for x in groups]);out['commonsense']={'state':common}
    out['overall']=verdict([out['schema']['state'],common,out['hard']['state']])
    cond=out.get('conditional_zero_assumption')
    if not isinstance(cond,dict):raise ValueError('v4 conditional score missing')
    conditional_attraction=cond.get('attractions')
    conditional_common=verdict([conditional_attraction if g['name']=='Is_attractions_correct' and conditional_attraction is not None
                                 else g['state'] for g in groups])
    cond['commonsense']=conditional_common
    cond['overall']=verdict([out['schema']['state'],conditional_common,out['hard']['state']])
    out['station_scoring']={'policy':space['policy'],'station_module_sha256':digest(root/'chinatravel/environment/station_aliases.py'),
                            'space_gate_sha256':digest(HERE/'space_gate.py'),'wrapper_sha256':digest(HERE/'score_v5.py'),
                            'scored_at_utc':datetime.now(timezone.utc).isoformat()}
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--target-root',type=Path,required=True)
    ap.add_argument('--query',type=Path,required=True);ap.add_argument('--plan',type=Path,required=True)
    ap.add_argument('--audit',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--base-score',type=Path);ap.add_argument('--dynamic-snapshot',type=Path)
    args=ap.parse_args()
    if args.output.exists():raise FileExistsError('v5 score exists')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    v4_path=args.output.with_name(args.output.name+'.date_v4.json')
    if v4_path.exists():raise FileExistsError('v4 intermediate exists')
    cmd=[sys.executable,'-X','utf8',str(HERE/'score_date_v4.py'),'--target-root',str(args.target_root),
         '--query',str(args.query),'--plan',str(args.plan),'--audit',str(args.audit),'--output',str(v4_path)]
    if args.base_score:cmd+=['--base-score',str(args.base_score)]
    if args.dynamic_snapshot:cmd+=['--dynamic-snapshot',str(args.dynamic_snapshot)]
    result=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace')
    if result.returncode:raise RuntimeError('date scorer failed: '+result.stderr[-4000:])
    v4=json.loads(v4_path.read_text(encoding='utf-8'))
    query=json.loads(args.query.read_text(encoding='utf-8-sig'));plan=json.loads(args.plan.read_text(encoding='utf-8-sig'))
    out=merge(v4,query,plan,args.target_root)
    out['station_scoring']['v4_score_path']=str(v4_path.resolve())
    out['station_scoring']['v4_score_sha256']=digest(v4_path)
    with args.output.open('x',encoding='utf-8') as f:json.dump(out,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({'uid':query['uid'],'v4':v4['overall'],'overall':out['overall'],
                      'space':next(x['state'] for x in out['groups'] if x['name']=='Is_space_correct'),
                      'conditional_zero':out['conditional_zero_assumption']['overall'],
                      'score':str(args.output.resolve())},ensure_ascii=False))
if __name__=='__main__':main()
