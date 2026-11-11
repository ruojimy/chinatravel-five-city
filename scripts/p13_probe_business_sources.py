"""Small real field probe; no key rotation, automatic retry, or default values."""
import collections,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.live_amap import LiveAmapClient,LiveAmapError
from shorttrip.freshness import utcnow,canonical
from shorttrip.travel_catalog import digest_file
OUT=ROOT/'results/p13_business_completion'
def main():
    OUT.mkdir(parents=True,exist_ok=True);raw=OUT/'private_api_raw';raw.mkdir(exist_ok=True)
    client=LiveAmapClient(ROOT,budget=4)
    requests=[('xian_restaurants',{'types':'050100','region':'西安'}),
              ('xiamen_restaurants',{'types':'050000','region':'厦门'}),
              ('tianjin_attractions',{'types':'110000','region':'天津'}),
              ('xian_hotels',{'types':'100100','region':'西安'})]
    results=[]
    for name,query in requests:
        path=raw/(name+'.json')
        if path.exists():
            packet=json.loads(path.read_text(encoding='utf-8'));data=packet['response'];meta=packet['meta']
        else:
            try:
                data,meta=client._call('/v5/place/text',{**query,'city_limit':'true','page_size':25,
                      'page_num':1,'show_fields':'business','output':'JSON'})
            except (LiveAmapError,ValueError) as exc:
                results.append({'request':name,'error':str(exc),'provider_stopped':client.stopped});break
            path.write_text(json.dumps({'meta':meta,'response':data},ensure_ascii=False,indent=2),encoding='utf-8')
        counts=collections.Counter();samples=[]
        for row in data.get('pois',[]):
            b=row.get('business') or {}
            counts['pois']+=1
            for key in ('cost','tag','keytag','rectag','opentime_today','opentime_week'):
                if b.get(key) not in (None,'',[]):counts[key]+=1
            if len(samples)<2:samples.append({'name':row.get('name'),'city':row.get('cityname'),
                'type':row.get('type'),'business':{k:v for k,v in b.items() if k!='tel'}})
        results.append({'request':name,'counts':dict(counts),'samples':samples,
            'raw_file':str(path.relative_to(ROOT)),'raw_sha256':digest_file(path),
            'retrieved_at':meta['retrieved_at']})
        if client.stopped:break
        time.sleep(1.2)
    report={'recorded_at':utcnow(),'api_calls_this_run':client.spent,'provider_stopped':client.stopped,
        'audit':client.audit,'results':results,'private_evidence_only':True,
        'field_semantics':'AMap business.cost is average per-person spend, not an attraction ticket or matched room-night rate. Opening hours are provider descriptions, not operator confirmations.',
        'docs':'https://lbs.amap.com/api/webservice/guide/api-advanced/newpoisearch'}
    (OUT/'amap_business_probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'api_calls':client.spent,'stopped':client.stopped,
        'results':[{k:v for k,v in r.items() if k in ('request','counts','error')} for r in results]},ensure_ascii=False))
if __name__=='__main__':main()
