"""Execute frozen repair episodes or apply a labelled safety projection to P24."""
import argparse,copy,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p25_reliable_retrieval'
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.retrieval_benchmark import serve
from shorttrip.retrieval_guard import VERSION,evaluate,enforce,annotate_events,triage
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def gateway(q,requests,evidence,now):
    events=serve(q,requests,evidence)
    for req,event in zip(requests,events):
        if event['status']=='budget_exhausted':continue
        if evidence and all(e.get('synthetic') for e in evidence):
            matches=[e for e in evidence if e['target_id']==req['target_id'] and e['city']==req['city'] and e['field'] in req['fields']]
            if matches:event.update(status='returned',evidence=matches,reason='Synthetic engineering fixture, not a real travel source')
        diagnostic=triage(req)
        if diagnostic['status']=='needs_clarification':event.update(status='invalid_context',evidence=[],reason='Need verified exact GCJ02 origin/destination and departure; no network request permitted. Missing: '+','.join(diagnostic['missing']))
        if diagnostic['status']=='adapter_required' and not event['evidence']:event.update(status='unavailable',reason='No authorized current intercity inventory adapter; do not invent service identifiers')
    return annotate_events(events,now)
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mode',required=True,choices=['retrieve','grade','regress']);parser.add_argument('--level',choices=['easy','hard','human']);args=parser.parse_args()
    if args.mode=='regress':
        p24=ROOT/'results/p24_dynamic_feedback';corpus=read(p24/'private/evidence_corpus.json');now=corpus['captured_at'];results=[]
        for level in ('easy','hard','human'):
            qs={q['uid']:q for q in read(p24/'private/queries_96.json') if q['level']==level};responses={v['uid']:v['events'] for v in read(p24/'responses_v2'/(level+'.json'))}
            for original in read(p24/'participants'/(level+'_dynamic.json')):
                uid=original['uid'];q=copy.deepcopy(qs[uid]);raw=copy.deepcopy(original);raw['schema_version']=VERSION
                if len(q['city_sequence'])==1 and level!='easy':q['budget_cny']=300 if level=='hard' else 200
                events=copy.deepcopy(responses[uid]);ledger={}
                for event in events:
                    for e in event['evidence']:
                        # Root reviewed these exact adult general admission lines in P24.
                        if e['field']=='price' and e['evidence_id'].startswith(('web:长沙:','web:厦门:')):e['price_scope']='adult_general_per_person_CNY'
                        ledger[e['evidence_id']]=e
                evidence=list(ledger.values());before=evaluate(q,raw,evidence,events,now=now);guarded,edits=enforce(q,raw,evidence,events,now=now)
                after=evaluate(q,guarded,evidence,events,now=now)
                save(OUT/'regression/guarded'/level/(uid+'.json'),guarded)
                results.append({'level':level,'uid':uid,'raw_v2_check':before,'guarded_check':after,'edits':edits})
        save(OUT/'regression/results_96.json',results)
        print(json.dumps({'cases':len(results),'raw_safe':sum(v['raw_v2_check']['safe'] for v in results),'guarded_safe':sum(v['guarded_check']['safe'] for v in results),
            'changed_cases':sum(bool(v['edits']) for v in results),'still_unaccepted':sum(not v['guarded_check']['policy_accepted'] for v in results),'scope':'Safety projection, not96 newLLM runs'}));return
    assert args.level,'--level required'
    cases=[c for c in read(OUT/'private/cases.json') if c['level']==args.level];cs={c['uid']:c for c in cases};now=read(OUT/'real/corpus.json')['captured_at']
    staticpath=OUT/'participants'/(args.level+'_static.json');first=read(staticpath)
    assert len(first)==8 and {p['uid'] for p in first}==set(cs)
    if args.mode=='retrieve':
        target=OUT/'responses'/(args.level+'.json');assert not target.exists(),'Preserve responses'
        rows=[{'uid':p['uid'],'events':gateway(cs[p['uid']]['query'],p['retrieval_requests'],cs[p['uid']]['evidence'],now)} for p in first]
        save(target,rows);save(OUT/'private'/(args.level+'_receipt.json'),{'static_sha256':sha(staticpath),'responses_sha256':sha(target)})
        print(json.dumps({'level':args.level,'cases':len(rows),'returned':sum(e['status']=='returned' for r in rows for e in r['events'])}));return
    receipt=read(OUT/'private'/(args.level+'_receipt.json'));assert receipt['static_sha256']==sha(staticpath)
    responsepath=OUT/'responses'/(args.level+'.json');assert receipt['responses_sha256']==sha(responsepath)
    responses={r['uid']:r['events'] for r in read(responsepath)}
    plans=read(OUT/'participants'/(args.level+'_dynamic.json'));assert len(plans)==8 and {p['uid'] for p in plans}==set(cs)
    rows=[]
    for p in plans:
        c=cs[p['uid']];events=responses[p['uid']];evidence=list({e['evidence_id']:e for event in events for e in event['evidence']}.values())
        before=evaluate(c['query'],p,evidence,events,now=now);guarded,edits=enforce(c['query'],p,evidence,events,now=now);after=evaluate(c['query'],guarded,evidence,events,now=now)
        save(OUT/'guarded'/args.level/(p['uid']+'.json'),guarded)
        rows.append({'uid':p['uid'],'level':args.level,'kind':c['kind'],'expected_policy_accepted':c['expected_policy_accepted'],
            'raw_check':before,'guarded_check':after,'edits':edits,'outcome_correct':after['policy_accepted']==c['expected_policy_accepted']})
    save(OUT/'evaluations'/(args.level+'.json'),rows)
    print(json.dumps({'level':args.level,'cases':len(rows),'raw_safe':sum(r['raw_check']['safe'] for r in rows),'guarded_safe':sum(r['guarded_check']['safe'] for r in rows),
        'raw_accepted':sum(r['raw_check']['policy_accepted'] for r in rows),'guarded_accepted':sum(r['guarded_check']['policy_accepted'] for r in rows),'correct_outcomes':sum(r['outcome_correct'] for r in rows)},ensure_ascii=True))
if __name__=='__main__':main()
