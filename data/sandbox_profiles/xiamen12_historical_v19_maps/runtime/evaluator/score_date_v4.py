"""Independent tri-state benchmark scorer with date-aware time gate.

Outputs are write-once. If --base-score is not supplied, the prior independent
scorer runs first and its unmodified result is preserved alongside this output.
No score or case data is returned to the planning participant.
"""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
from copy import deepcopy
import argparse,json,subprocess,sys
from date_timeline import validate_timeline
from source_duration import DurationResolver
from attraction_prices import AttractionPriceEvidence

HERE=Path(__file__).resolve().parent
BASE_SCORER=HERE/'score_tristate.py'
def sha(path):return sha256(path.read_bytes()).hexdigest()
def verdict(states):
    return 'fail' if 'fail' in states else 'unknown' if not states or 'unknown' in states else 'pass'

def merge(base,query,plan,duration_resolver=None,attraction_price_evidence=None):
    output=deepcopy(base)
    groups=output.get('groups')
    if not isinstance(groups,list):raise ValueError('base score does not contain independent group results')
    indices=[i for i,x in enumerate(groups) if x.get('name')=='Is_time_correct']
    if len(indices)!=1:raise ValueError('expected exactly one native time group')
    time=validate_timeline(query,plan,duration_resolver)
    output['superseded_time_group']=groups[indices[0]]
    groups[indices[0]]={'name':'Is_time_correct','state':time['state'],'issues':time['issues'],
                        'policy':time.get('policy'),'implementation':'date_timeline_v4'}
    conditional_group_state=None;conditional_assumptions=[]
    if attraction_price_evidence is not None:
        price_items=attraction_price_evidence.check(query,plan)
        hits=[i for i,x in enumerate(groups) if x.get('name')=='Is_attractions_correct']
        if len(hits)!=1:raise ValueError('expected exactly one native attraction group')
        i=hits[0];old=groups[i];cells=old.get('cells')
        price_state=verdict([x['state'] for x in price_items]) if price_items else 'pass'
        def combine(price_state,allow_zero=False):
          if not isinstance(cells,dict):
            return 'fail' if price_state=='fail' else 'unknown'
          else:
            price_key='Incorrect price Information of attraction'
            if price_key not in cells:
                return 'fail' if price_state=='fail' else 'unknown'
            elif any(v for k,v in cells.items() if k!=price_key):
                return 'fail'
            elif price_state=='fail':return 'fail'
            elif price_state=='unknown':return 'unknown'
            elif old.get('state') in ('fail','unknown'):
                # Only conditional scoring can resolve a legacy missing-price
                # failure, and only for evidenced user-authorized assumptions.
                return 'pass' if allow_zero and old.get('state')=='fail' and conditional_assumptions else 'unknown'
            else:return 'pass'
        new_state=combine(price_state)
        conditional_assumptions=[x for x in price_items if x.get('conditional_assumption_eligible')]
        conditional_price_state=verdict(['pass' if x.get('conditional_assumption_eligible') else x['state']
                                         for x in price_items]) if price_items else 'pass'
        conditional_group_state=combine(conditional_price_state,allow_zero=True)
        output['superseded_attraction_group']=old
        groups[i]={'name':'Is_attractions_correct','state':new_state,'legacy_cells':cells,
                   'legacy_messages':old.get('messages',[]),'price_evidence':price_items,
                   'policy':'Unknown or assumed attraction price remains conditional; other definite violations remain failures.'}
    output['commonsense']={'state':verdict([x['state'] for x in groups])}
    output['overall']=verdict([output['schema']['state'],output['commonsense']['state'],output['hard']['state']])
    conditional_common=verdict([conditional_group_state if g['name']=='Is_attractions_correct' and conditional_group_state is not None
                                else g['state'] for g in groups])
    output['conditional_zero_assumption']={
        'applied':bool(conditional_assumptions),
        'overall':verdict([output['schema']['state'],conditional_common,output['hard']['state']]),
        'commonsense':conditional_common,'attractions':conditional_group_state,
        'assumptions':conditional_assumptions,
        'boundary':'Conditional benchmark result under user-authorized zero after documented searches; does not establish that a real attraction is free.'}
    output['date_scoring']={'policy':'native time group replaced with explicit day-number timeline; other original gates preserved',
                            'timeline_module_sha256':sha(HERE/'date_timeline.py'),
                            'wrapper_sha256':sha(HERE/'score_date_v4.py'),
                            'scored_at_utc':datetime.now(timezone.utc).isoformat(),
                            'real_world_boundary':'No given travel date or verified inventory is not evidence of real-world ticket availability.'}
    return output

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--target-root',type=Path,required=True)
    ap.add_argument('--query',type=Path,required=True);ap.add_argument('--plan',type=Path,required=True)
    ap.add_argument('--audit',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--base-score',type=Path)
    ap.add_argument('--dynamic-snapshot',type=Path,help='Optional explicit immutable dynamic source snapshot')
    args=ap.parse_args()
    if args.output.exists():raise FileExistsError('final score already exists')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    base_path=args.base_score or args.output.with_name(args.output.name+'.base.json')
    if args.base_score is None:
        if base_path.exists():raise FileExistsError('base score already exists')
        cmd=[sys.executable,'-X','utf8',str(BASE_SCORER),'--target-root',str(args.target_root),
             '--query',str(args.query),'--plan',str(args.plan),'--audit',str(args.audit),'--output',str(base_path)]
        p=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace')
        if p.returncode:raise RuntimeError('base scorer failed: '+p.stderr[-4000:])
    base=json.loads(base_path.read_text(encoding='utf-8'))
    if base.get('query_sha256')!=sha(args.query) or base.get('plan_sha256')!=sha(args.plan):
        raise ValueError('base score does not match query and plan bytes')
    if base.get('query_audit_sha256')!=sha(args.audit):raise ValueError('base score does not match audit')
    if Path(base['target_root']).resolve()!=args.target_root.resolve():raise ValueError('base score target root mismatch')
    query=json.loads(args.query.read_text(encoding='utf-8-sig'))
    plan=json.loads(args.plan.read_text(encoding='utf-8-sig'))
    evidence_events=[]
    try:source=DurationResolver(args.target_root)
    except Exception:source=None
    def resolve(query,activity):
        result=source(query,activity) if source else None
        evidence_events.append({'type':activity.get('type'),
                                'id':activity.get('TrainID') or activity.get('FlightID'),
                                'start':activity.get('start'),'end':activity.get('end'),
                                'matched_duration':result})
        return result
    default_snapshot=args.target_root.resolve().parents[1]/'dynamic_snapshot_v2.json'
    snapshot=args.dynamic_snapshot or (default_snapshot if default_snapshot.is_file() else None)
    price_evidence=AttractionPriceEvidence(args.target_root,snapshot)
    final=merge(base,query,plan,resolve,price_evidence)
    final['date_scoring']['base_score_path']=str(base_path.resolve())
    final['date_scoring']['base_score_sha256']=sha(base_path)
    final['date_scoring']['duration_evidence']=evidence_events
    final['date_scoring']['duration_source_reader_sha256']=sha(HERE/'source_duration.py')
    final['date_scoring']['price_evidence_reader_sha256']=sha(HERE/'attraction_prices.py')
    final['date_scoring']['dynamic_snapshot_path']=str(snapshot.resolve()) if snapshot else None
    final['date_scoring']['dynamic_snapshot_sha256']=sha(snapshot) if snapshot else None
    with args.output.open('x',encoding='utf-8') as f:json.dump(final,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({'uid':query['uid'],'original':base.get('overall'),'overall':final['overall'],
                      'date_state':next(x['state'] for x in final['groups'] if x['name']=='Is_time_correct'),
                      'base_score':str(base_path.resolve()),'output':str(args.output.resolve())},ensure_ascii=False))

if __name__=='__main__':main()
