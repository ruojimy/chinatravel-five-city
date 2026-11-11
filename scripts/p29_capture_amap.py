"""Serial, persisted Amap snapshot collection for five explicitly scoped cities.

Uses the existing project credential, with one circuit breaker and no rotation.
POI costs are category-specific references, never room offers or attraction tickets.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.live_amap import LiveAmapClient

OUT=ROOT/'results/p29_five_city_completion'
CITIES={'西安':'610100','厦门':'350200','宁波':'330200','长沙':'430100','青岛':'370200'}

def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--stage',choices=['seed','metro','match'],required=True)
    ap.add_argument('--city',choices=list(CITIES))
    a=ap.parse_args()
    lp=OUT/'capture/amap_ledger.json'
    ledger=json.loads(lp.read_text(encoding='utf-8')) if lp.exists() else {'max_calls':120,'spent':0,'stopped':False,'calls':[],'key_rotation':False}
    if ledger['stopped']:raise SystemExit('Provider stopped; no retries or credential rotation')
    client=LiveAmapClient(ROOT,budget=ledger['max_calls']-ledger['spent'])
    def call(label,city,params):
        fp=OUT/'capture'/('amap_'+label+'.json')
        if fp.exists():return
        before=client.spent
        receipt={'label':label,'city':city,'at':datetime.now(timezone.utc).isoformat()}
        try:
            raw,meta=client._call('/v5/place/text',params)
            save(fp,{'raw':raw,'meta':meta,'city':city,'snapshot_scope':'provider_snapshot_no_fact_update_timestamp'})
            receipt.update(status='ok',file=str(fp.relative_to(ROOT)),count=len(raw.get('pois',[])))
        except Exception as exc:
            receipt.update(status='failed',error=str(exc))
            save(fp,{'error':str(exc),'no_retry':True})
        ledger['spent']+=client.spent-before
        ledger['stopped']=client.stopped
        receipt['audit']=client.audit[-1] if client.spent>before else None
        ledger['calls'].append(receipt);save(lp,ledger)
        print(json.dumps(receipt,ensure_ascii=False),flush=True)
        if receipt['status']!='ok':raise SystemExit('Stopped: '+receipt['error'])
    if a.stage=='seed':
        for city,code in CITIES.items():
            if a.city and city!=a.city:continue
            for label,typ,keyword in [('attraction','110000',''),('restaurant','050100',''),('hotel','100100',''),('hub','150100|150200','')]:
                call(city+'_'+label,city,{'region':code,'city_limit':'true','types':typ,'keywords':keyword,'page_size':25,'page_num':1,'show_fields':'business,children'})
    elif a.stage=='metro':
        for city,code in CITIES.items():
            if a.city and city!=a.city:continue
            # All returned pages are retained, including duplicate exits and line variants.
            for page in range(1,13):
                label=city+'_metro_'+str(page)
                call(label,city,{'region':code,'city_limit':'true','types':'150500','page_size':25,'page_num':page,'show_fields':'business'})
                raw=json.loads((OUT/'capture'/('amap_'+label+'.json')).read_text(encoding='utf-8'))['raw']
                if len(raw.get('pois',[]))<25:break
    else:
        qs=json.loads((OUT/'match_queries.json').read_text(encoding='utf-8'))
        for i,q in enumerate(qs):
            city=q['city']
            if a.city and city!=a.city:continue
            call('match_'+str(i),city,{'region':CITIES[city],'city_limit':'true','keywords':q['name'],'page_size':5,'show_fields':'business,children'})
    print(json.dumps({'spent':ledger['spent'],'stopped':ledger['stopped']},ensure_ascii=False))

if __name__=='__main__':main()
