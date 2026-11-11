"""Root-only request execution and independent static/dynamic episode grading."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p24_dynamic_feedback'
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.retrieval_benchmark import evaluate,serve
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--level',required=True,choices=['easy','hard','human']);p.add_argument('--stage',required=True,choices=['retrieve','grade']);args=p.parse_args()
    queries={q['uid']:q for q in read(OUT/'private/queries_96.json') if q['level']==args.level}
    src=OUT/'participants'/(args.level+'_static.json');plans=read(src)
    assert len(plans)==32 and {v['uid'] for v in plans}==set(queries),'Missing or duplicate static UID'
    first={v['uid']:v for v in plans};corpus=read(OUT/'private/evidence_corpus.json')
    if args.stage=='retrieve':
        target=OUT/'responses_v2'/(args.level+'.json')
        if target.exists():raise FileExistsError('Preserve request responses')
        entries=[]
        for uid,q in queries.items():
            events=serve(q,first[uid]['retrieval_requests'],corpus['evidence'])
            entries.append({'uid':uid,'events':events,'scope':'These are actual gateway responses to your first-plan requests, replaying captured sources. Not another live call. Unknown origin coordinates and unsourced intercity legs remain unavailable.'})
        save(target,entries)
        save(OUT/'private'/(args.level+'_static_receipt_v2.json'),{'file':str(src.relative_to(ROOT)),'sha256':sha(src),'count':32,'response_sha256':sha(target)})
        print(json.dumps({'level':args.level,'cases':len(entries),'requests':sum(len(e['events']) for e in entries),'returned':sum(event['status']=='returned' for e in entries for event in e['events'])}))
        return
    receipt=read(OUT/'private'/(args.level+'_static_receipt_v2.json'));assert sha(src)==receipt['sha256'],'First outputs changed'
    responsepath=OUT/'responses_v2'/(args.level+'.json');assert sha(responsepath)==receipt['response_sha256'],'Responses changed'
    responses={r['uid']:r['events'] for r in read(responsepath)}
    dynamic=read(OUT/'participants'/(args.level+'_dynamic.json'))
    assert len(dynamic)==32 and {v['uid'] for v in dynamic}==set(queries),'Missing or duplicate dynamic UID'
    records=[]
    for after in dynamic:
        uid=after['uid'];q=queries[uid];events=responses[uid]
        returned={e['evidence_id']:e for event in events for e in event['evidence']}
        before_report=evaluate(q,first[uid],stage='static',now=corpus['captured_at'])
        after_report=evaluate(q,after,list(returned.values()),events,stage='dynamic',previous=first[uid],now=corpus['captured_at'])
        records.append({'uid':uid,'level':args.level,'static':before_report,'dynamic':after_report,
            'static_sha256':receipt['sha256'],'dynamic_sha256':sha(OUT/'participants'/(args.level+'_dynamic.json')),
            'gateway_requests':len(events),'returned_events':sum(e['status']=='returned' for e in events),
            'unavailable_events':sum(e['status']=='unavailable' for e in events)})
    save(OUT/'evaluations'/(args.level+'.json'),records)
    for stage in ('static','dynamic'):
        print(json.dumps({'level':args.level,'stage':stage,'cases':len(records),
            'schema':sum(r[stage]['schema_ok'] for r in records),'protocol':sum(r[stage]['protocol_ok'] for r in records),
            'safe':sum(r[stage]['safe'] for r in records),'complete':sum(r[stage]['complete'] for r in records),
            'resolved_fields':sum(r[stage]['metrics'].get('resolved_fields',0) for r in records)},ensure_ascii=True))
if __name__=='__main__':main()
