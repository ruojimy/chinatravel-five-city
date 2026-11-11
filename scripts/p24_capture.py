"""Finite source capture for P24; six recovered-key weather calls, no routing guesses."""
import copy,hashlib,json,sqlite3,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p24_dynamic_feedback'
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.live_amap import LiveAmapClient,LiveAmapError
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def evidence(eid,target,city,field,value,context,source,url,raw,quote,*,level='reference',rejected=None,**extra):
    assert quote and quote in raw
    return dict(evidence_id=eid,target_id=target,city=city,field=field,value=value,context=context,source_id=source,source_url=url,
        raw_text=raw,quote=quote,raw_sha256=hashlib.sha256(raw.encode()).hexdigest(),level=level,rejected_reason=rejected,**extra)
def main():
    if (OUT/'private/evidence_corpus.json').exists():raise FileExistsError('Preserve captured corpus')
    queries=read(OUT/'private/queries_96.json');stamp=datetime.now(timezone.utc).isoformat();corpus=[]
    wanted={r['target_id'] for q in queries for r in q['requirements'] if r['field']=='price'}
    dbpath=ROOT/'data/business_catalog_v1_7_20261023T021649Z/catalog.sqlite3'
    db=sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)
    # Existing raw operator references are returned as quarantined clues, never
    # promoted by a regex or recent download. No paused source is fetched here.
    cached=0
    for rid in sorted(wanted):
        row=db.execute('select payload from records where id=?',(rid,)).fetchone()
        if not row:continue
        record=json.loads(row[0]);city=record['city']
        for a in record.get('operator_assertions',[]):
            capture=a.get('capture',{});p=ROOT/capture.get('file','')
            if not p.is_file() or digest(p)!=capture.get('sha256'):continue
            raw=p.read_text(encoding='utf-8-sig');quote=a.get('quote','')
            if not quote or quote not in raw:continue
            field='opening_hours' if a['field'] in ('opening_rules_raw','opening_hours') else 'price' if a['field'] in ('admission','admission_listed_free_reference','admission_listed_price_reference') else None
            if not field:continue
            # Extracted historical values can be useful clues, not current prices.
            for date in ('2026-10-24','2026-10-25'):
                corpus.append(evidence('cache:'+hashlib.sha256((a['assertion_id']+date).encode()).hexdigest()[:20],rid,city,field,a.get('value'),{'travel_date':date},a['source_id'],a['source_url'],quote,quote,
                    level='reference',rejected='cached_reference_entity_or_fact_age_unverified',retrieved_at=a.get('retrieved_at'),source_observed_at=a.get('observed_at'),
                    original_capture_file=str(p.relative_to(ROOT)),original_capture_sha256=digest(p),scope=a.get('scope'),synthetic=False))
                cached+=1
    db.close()
    # These exact quotes were independently opened and reviewed in this turn.
    records={'长沙':'overture:dbff3d67-d928-4b8e-a90e-92a853af0c27','厦门':'overture:f107cf72-41d7-4eb5-805b-14d5e5645cad','海口':'overture:59c3bd14-c203-45f5-8639-debdfc9a3be8'}
    source_rows=[
        ('长沙','price',40,'https://ylsy.hnu.edu.cn/wbly/cgdn/zxdp.htm','全价票：40元/人次','web_pages_01.json'),
        ('长沙','opening_hours',{'open':'07:50','close':'18:00','last_admission':'17:40','ticket_stop':'17:30','months':'5-10'},'https://ylsy.hnu.edu.cn/wbly/cgdn/zxdp.htm','5月-10月：7:50-17:30（17:30停止售票，17:40停止入院，18:00闭馆）','web_pages_01.json'),
        ('厦门','price',30,'https://www.xiamenbg.cn/Home/yyzn3','厦发改收费〔2023〕354号','web_xiamen_guides_03.json'),
        ('海口','opening_hours',{'open':'09:00','close':'17:00','last_admission':'16:30','closed_weekday':'Monday'},'https://www.hainanmuseum.org/hnbwgcms/info/3055','周二至周日 09:00（开馆）——16:30（停止检票）——17:00（闭馆）','web_pages_01.json')]
    for city,field,value,url,quote,file in source_rows:
        rawfile=OUT/'live'/file;packet=rawfile.read_text(encoding='utf-8');assert quote in packet
        # Only retain the tiny supporting excerpt in the distributable evidence.
        excerpt=quote if not(city=='厦门' and field=='price') else '景区门票\n30\n元/人·次\n厦发改收费〔2023〕354号'
        if city=='厦门':
            assert all(v in packet for v in ['景区门票','30','元/人·次',quote])
        for date in ('2026-10-24','2026-10-25'):
            corpus.append(evidence('web:'+city+':'+field+':'+date,records[city],city,field,value,{'travel_date':date},'operator:'+city,url,excerpt,quote,
                retrieved_at=stamp,source_observed_at=None,source_published_at='2026-04-17T16:52:00+08:00' if city=='海口' else None,
                original_capture_file=str(rawfile.relative_to(ROOT)),original_capture_sha256=digest(rawfile),
                scope='Published operator reference only. Entity linked by explicit city/name, not independent address/GCJ02 verification. No booking/inventory/current-price guarantee.',synthetic=False))
    # Request weather once per city; reuse provider casts, never invent date values.
    amap=LiveAmapClient(ROOT,budget=6)
    codes={'长沙':'430100','厦门':'350200','西安':'610100','昆明':'530100','宁波':'330200','海口':'460100'}
    failures=[]
    for city,code in codes.items():
        try:
            claim=amap.weather(code,travel_date='2026-10-24');raw=json.loads(claim['raw_text']);row=(raw.get('forecasts') or [{}])[0]
            save(OUT/'live'/('amap_weather_'+code+'.json'),{'claim':claim,'audit':amap.audit[-1]})
            for date in ('2026-10-24','2026-10-25'):
                cast=next((v for v in row.get('casts',[]) if v.get('date')==date),None)
                if cast is None:continue
                observed=claim.get('observed_at');deadline=None
                if observed:deadline=(datetime.fromisoformat(observed)+timedelta(hours=1)).isoformat()
                corpus.append(evidence('amap:'+code+':'+date,'weather:'+city,city,'weather_forecast',cast,{'travel_date':date},'amap',claim['source_url'],claim['raw_text'],claim['quote'],
                    level='estimate',retrieved_at=claim['retrieved_at'],source_observed_at=observed,valid_until=deadline,synthetic=False,
                    scope='Captured provider forecast, date/adcode matched. Frozen replay only; no weather guarantee.',amap_claim_id=claim['claim_id']))
        except LiveAmapError as exc:
            failures.append({'city':city,'error':str(exc)});break
    save(OUT/'live/amap_ledger.json',{'audit':amap.audit,'spent':amap.spent,'stopped':amap.stopped,'failures':failures,'no_routes_called':'No exact origin/verified GCJ02 anchors; do not guess coordinates'})
    # Frozen evaluation time is after collection, not renewed on each replay.
    now=datetime.now(timezone.utc).isoformat()
    save(OUT/'private/evidence_corpus.json',{'captured_at':now,'evidence':corpus,'cached_rows':cached,'new_weather_calls':amap.spent,
        'synthetic_records':0,'explicitly_no_synthetic_attacks':True,'capture_policy':'Root bounded source capture and reviewed extraction; model request gateway filters later. Not autonomous live search by LLM.'})
    print(json.dumps({'corpus':len(corpus),'cached':cached,'amap_calls':amap.spent,'failures':failures},ensure_ascii=True))
if __name__=='__main__':main()
