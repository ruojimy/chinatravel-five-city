"""CLI backing the travel-live-retrieval skill. No network unless explicitly live."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.travel_catalog import TravelCatalog,annotate_dataset,preflight
from shorttrip.freshness import reconcile,utcnow,retrieval_task
from shorttrip.live_amap import LiveAmapClient,LiveAmapError

def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def save(path,data):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def followup(claim,verdict):
    if not verdict['needs_user_confirmation']:return None
    reasons=list(dict.fromkeys(r for c in verdict['checks'] for r in c['reasons'])) or [verdict['status']]
    return retrieval_task({'entity_id':claim['entity_id']},claim['field'],reasons=reasons,context=claim.get('context'))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=ROOT)
    sub=p.add_subparsers(dest='command',required=True)
    annotate=sub.add_parser('annotate');annotate.add_argument('--output',type=Path,required=True)
    prepare=sub.add_parser('prepare');prepare.add_argument('--catalog',type=Path,required=True)
    prepare.add_argument('--query',type=Path,required=True);prepare.add_argument('--date')
    prepare.add_argument('--limit',type=int,default=6);prepare.add_argument('--output',type=Path,required=True)
    live=sub.add_parser('live');live.add_argument('--request',type=Path,required=True)
    live.add_argument('--budget',type=int,default=4);live.add_argument('--catalog',type=Path)
    live.add_argument('--output',type=Path,required=True)
    ingest=sub.add_parser('ingest');ingest.add_argument('--claim',type=Path,required=True)
    ingest.add_argument('--catalog',type=Path,required=True);ingest.add_argument('--registry',type=Path)
    ingest.add_argument('--output',type=Path,required=True)
    search=sub.add_parser('search-static',help='Read baseline and validated expansion before live retrieval')
    search.add_argument('--expansion',type=Path,required=True);search.add_argument('--baseline',type=Path)
    search.add_argument('--city',required=True);search.add_argument('--kind',required=True,
        choices=('attraction','restaurant','accommodation','poi','metro_station','train','flight'))
    search.add_argument('--tag');search.add_argument('--limit',type=int,default=6)
    search.add_argument('--date');search.add_argument('--output',type=Path,required=True)
    detail=sub.add_parser('business-details',help='Read business fields, room/date context and current validity')
    detail.add_argument('--catalog',type=Path,required=True);detail.add_argument('--entity-id',required=True)
    detail.add_argument('--output',type=Path,required=True)
    args=p.parse_args();registry=load(args.project/'data/travel_source_registry.json')
    if args.command=='business-details':
        from shorttrip.business_completion import details
        result=details(args.catalog,args.entity_id);save(args.output,result)
        print(json.dumps({'native_operational_complete':result['native_operational_complete'],
             'offers':len(result['room_offers']),'planning_ready':result['current_record_gate']['planning_ready'],
             'network_calls':0},ensure_ascii=False));return
    if args.command=='search-static':
        from shorttrip.static_lookup import lookup,verification_tasks
        result=lookup(args.expansion,args.city,args.kind,baseline=args.baseline,tag=args.tag,limit=args.limit)
        result['retrieval_tasks']=verification_tasks(result,travel_date=args.date)
        save(args.output,result)
        print(json.dumps({'candidates':len(result['candidates']),'tasks':len(result['retrieval_tasks']),
             'network_calls':0,'ready':False},ensure_ascii=False));return
    if args.command=='annotate':
        result=annotate_dataset(args.project,args.output,registry)
        print(json.dumps({k:result[k] for k in ('files','records','counts','source_files_modified')},ensure_ascii=False));return
    if args.command=='prepare':
        catalog=TravelCatalog(args.catalog)
        try:result=preflight(catalog,load(args.query),travel_date=args.date,limit=args.limit)
        finally:catalog.close()
        save(args.output,result)
        print(json.dumps({'candidates':len(result['candidates']),'tasks':len(result['retrieval_tasks']),
                          'ready':result['ready_for_real_world_recommendation']},ensure_ascii=False));return
    if args.command=='ingest':
        if args.registry:registry=load(args.registry)
        claim=load(args.claim);catalog=TravelCatalog(args.catalog)
        try:
            result=reconcile(catalog.claims(claim['entity_id'],claim['field'])+[claim],claim['field'],registry,
                             context=claim.get('context'),entity_id=claim['entity_id'])
            result['retrieval_task']=followup(claim,result)
            result['question_stage']='after_bounded_multi_source_attempts'
            # Append, even quarantined evidence; queries must use the gate verdict.
            claim['ingest_verdict']=result;catalog.add_claim(claim)
        finally:catalog.close()
        save(args.output,result);print(json.dumps({'status':result['status'],'needs_user_confirmation':result['needs_user_confirmation']}));return
    request=load(args.request);client=LiveAmapClient(args.project,budget=args.budget)
    claims=[];errors=[]
    for item in request['requests']:
        try:
            if item['kind']=='weather':claims.append(client.weather(item['adcode'],travel_date=item.get('travel_date')))
            elif item['kind']=='transit':claims.extend(client.transit(**{k:v for k,v in item.items() if k!='kind'}))
            else:raise ValueError('unsupported request kind')
        except (LiveAmapError,ValueError) as exc:
            errors.append({'kind':item['kind'],'reason':str(exc)})
            if client.stopped or client.spent>=client.budget:break
    evaluations=[];tasks=[];catalog=TravelCatalog(args.catalog) if args.catalog else None
    try:
        for claim in claims:
            prior=catalog.claims(claim['entity_id'],claim['field']) if catalog else []
            evaluation=reconcile(prior+[claim],claim['field'],registry,context=claim['context'],entity_id=claim['entity_id'])
            evaluations.append({'claim_id':claim['claim_id'],'field':claim['field'],**evaluation})
            task=followup(claim,evaluation)
            if task:tasks.append(task)
            if catalog:catalog.add_claim(claim)
    finally:
        if catalog:catalog.close()
    result={'recorded_at':utcnow(),'request':request,'budget':client.budget,'api_calls':client.spent,
            'provider_stopped':client.stopped,'request_audit':client.audit,'claims':claims,'evaluations':evaluations,'errors':errors,
            'retrieval_tasks':tasks,'question_stage':'after_bounded_multi_source_attempts',
            'multi_source_complete':False,'ready_for_real_world_recommendation':False,
            'pending_source_checks':['Applicable official weather bulletin / independent forecast lineage',
                                     'Applicable metro operator disruption / service notice'],
            'note':'API smoke/one-provider stage. Skill must perform bounded independent-source retrieval and preserve unresolved fields. No source-estimate is a guaranteed hard fact.'}
    save(args.output,result)
    print(json.dumps({'api_calls':client.spent,'claims':len(claims),'errors':errors,
                      'statuses':[{ 'field':v['field'],'status':v['status']} for v in evaluations]},ensure_ascii=False))

if __name__=='__main__':main()
