"""Capture a bounded real witness, preserving reservations as prerequisites."""
import copy,hashlib,json,sys
from pathlib import Path
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p25_reliable_retrieval'
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.live_amap import LiveAmapClient,LiveAmapError
from shorttrip.retrieval_guard import VERSION,schema
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def ev(eid,target,field,value,context,raw,*,level='verified',source='amap',url='',**extra):
    return dict(evidence_id=eid,target_id=target,city='长沙',field=field,value=value,context=context,raw_text=raw,quote=raw,
        raw_sha256=hashlib.sha256(raw.encode()).hexdigest(),level=level,source_id=source,source_url=url,**extra)
def main():
    if (OUT/'real/corpus.json').exists():raise FileExistsError('Preserve witness capture')
    outdir=OUT/'real';outdir.mkdir(parents=True,exist_ok=True);save(OUT/'public/plan.schema.json',schema())
    p22=ROOT/'results/p22_adaptive_delivery/live';allpois=[]
    for p in sorted(p22.glob('amap_*.json')):
        packet=read(p)
        if isinstance(packet.get('raw'),dict):
            for poi in packet['raw'].get('pois',[]):allpois.append((poi,packet.get('meta',{}),str(p.relative_to(ROOT))))
    ids={'start':'B02DB00018','visit':'B02DB05TQH'};selected={key:next(x for x in allpois if x[0].get('id')==rid) for key,rid in ids.items()}
    evidence=[];candidates=[]
    rids={'start':'amap:B02DB00018','visit':'overture:dbff3d67-d928-4b8e-a90e-92a853af0c27'}
    for key,(poi,meta,file) in selected.items():
        raw=json.dumps({'pois':[poi]},ensure_ascii=False,sort_keys=True)
        evidence.append(ev('p25:identity:'+key,rids[key],'identity',{'provider_id':poi['id'],'provider_name':poi['name']},{},raw,
            url=meta['endpoint'],source_observed_at=meta['retrieved_at'],retrieved_at=meta['retrieved_at'],
            identity_binding={'provider_id':poi['id'],'expected_name':poi['name']},original_capture_file=file,
            binding_scope='Verified linkage to captured provider POI/name/city, not independent physical-world certification.'))
        candidates.append({'entity_id':rids[key],'name':poi['name'],'city':'长沙','kind':'attraction','data':{},'dataset':'expansion_with_provider_binding'})
    # Operator references already opened in P24; never refresh their source clocks.
    p24=read(ROOT/'results/p24_dynamic_feedback/private/evidence_corpus.json')
    for e in p24['evidence']:
        if e['evidence_id'] in ('web:长沙:price:2026-10-24','web:长沙:opening_hours:2026-10-24'):
            e=copy.deepcopy(e)
            if e['field']=='price':e['price_scope']='adult_general_per_person_CNY'
            evidence.append(e)
    amap=LiveAmapClient(ROOT,budget=3);date='2026-10-24'
    try:
        weather=amap.weather('430100',travel_date=date)
        save(outdir/'weather_raw.json',weather)
        observed=weather['observed_at'];deadline=(datetime.fromisoformat(observed)+timedelta(hours=1)).isoformat() if observed else None
        evidence.append(ev('p25:weather','weather:长沙','weather_forecast',weather['value'],{'travel_date':date},weather['raw_text'],level='estimate',url=weather['source_url'],
            source_observed_at=observed,retrieved_at=weather['retrieved_at'],valid_until=deadline))
        origin=selected['start'][0]['entr_location'];destination=selected['visit'][0]['entr_location']
        for key,frm,to,time in [('outbound',origin,destination,'13:00'),('return',destination,origin,'16:00')]:
            claims=amap.transit(list(map(float,frm.split(','))),list(map(float,to.split(','))),city1='0731',city2='0731',departure_at=date+'T'+time+':00+08:00')
            save(outdir/(key+'_raw.json'),claims)
            startid,end=rids['start'],rids['visit']
            if key=='return':startid,end=end,startid
            for c in claims:
                context={**c['context'],'departure_at':date+'T'+time+':00+08:00'}
                assert datetime.fromisoformat(context['departure_at'])==datetime.fromisoformat(c['context']['departure_at'])
                deadline=(datetime.fromisoformat(c['observed_at'])+timedelta(minutes=15 if c['field']=='route_duration' else 30)).isoformat()
                evidence.append(ev('p25:'+key+':'+c['field'],'route:'+startid+'>'+end,c['field'],c['value'],context,c['raw_text'],
                    level='estimate',url=c['source_url'],source_observed_at=c['observed_at'],retrieved_at=c['retrieved_at'],valid_until=deadline,
                    unit='minutes' if c['field']=='route_duration' else 'CNY/person',mode_requirement_met=c['mode_requirement_met']))
    except LiveAmapError as exc:
        save(outdir/'failure.json',{'error':str(exc),'audit':amap.audit,'no_retry':True});raise
    save(outdir/'api_ledger.json',{'spent':amap.spent,'audit':amap.audit,'old_key_reused':True,'key_rotation':False})
    now=datetime.now(timezone.utc).isoformat()
    requirements=[]
    for e in evidence:
        requirements.append({**{k:e[k] for k in ('target_id','city','field','context')},'accepted_levels':[e['level']],
            **({'entity_required':True} if e['field']=='price' else {})})
    # Confirmed booking is never fabricated; allowed output is explicitly conditional.
    requirements.append({'target_id':rids['visit'],'city':'长沙','field':'inventory','context':{'travel_date':date,'party_size':2},'accepted_levels':['verified'],'prerequisite_only':True})
    query={'schema_version':VERSION,'uid':'REAL-CS-01','people_number':2,'city_sequence':['长沙'],'dates':[date],
        'nature_language':'10月24日两人13:00从湖南省博物馆正门出发，主要乘地铁去岳麓书院，14:00到16:00参观，18:00前返回同一入口；门票和交通预算200元，不含餐饮住宿。允许输出预约尚未完成的条件方案，但必须列明前提，不能声称已订票或保证到达。',
        'candidates':candidates,'requirements':requirements,'retrieval_budget':4,'budget_cny':200,'route_buffer_minutes':10}
    save(outdir/'query.json',query);save(outdir/'corpus.json',{'captured_at':now,'evidence':evidence,'live_calls':amap.spent})
    public={k:v for k,v in query.items() if k!='requirements'};save(OUT/'public/real_query.json',public)
    print(json.dumps({'amap_calls':amap.spent,'evidence':len(evidence),'captured_at':now,'new_route_fares':[e['value'] for e in evidence if e['field']=='route_fare']}))
if __name__=='__main__':main()
