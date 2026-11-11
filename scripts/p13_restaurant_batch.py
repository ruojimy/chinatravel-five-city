"""Eight bounded incremental public-API pages, caching each response before proceeding."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.live_amap import LiveAmapClient,LiveAmapError
from shorttrip.freshness import utcnow
def main():
    out=ROOT/'results/p13_business_completion';raw=out/'private_api_raw'
    pause=out/'AMAP_PAUSED.json'
    if pause.exists():raise RuntimeError('Provider previously stopped; no automatic retry')
    client=LiveAmapClient(ROOT,budget=8);rows=[]
    for city,slug in [('西安','xian'),('厦门','xiamen')]:
        for page in range(2,6):
            name=f'{slug}_restaurants_page{page}';path=raw/(name+'.json')
            if path.exists():
                packet=json.loads(path.read_text(encoding='utf-8'));rows.append({'page':name,'cache':True,'pois':len(packet['response'].get('pois',[]))});continue
            try:
                data,meta=client._call('/v5/place/text',{'types':'050100','region':city,'city_limit':'true',
                    'page_num':page,'page_size':25,'show_fields':'business','output':'JSON'})
            except LiveAmapError as exc:
                rows.append({'page':name,'error':str(exc)})
                pause.write_text(json.dumps({'at':utcnow(),'error':str(exc),'no_key_rotation':True}),encoding='utf-8')
                break
            path.write_text(json.dumps({'meta':meta,'response':data},ensure_ascii=False,indent=2),encoding='utf-8')
            rows.append({'page':name,'pois':len(data.get('pois',[]))});time.sleep(1.2)
        if client.stopped:break
    result={'executed_at':utcnow(),'api_calls':client.spent,'provider_stopped':client.stopped,'pages':rows,
      'audit':client.audit,'budget':8,'same_project_key':True,'total_response_rows':sum(x.get('pois',0) for x in rows)}
    (out/'restaurant_incremental_batch.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('api_calls','provider_stopped','total_response_rows','pages')},ensure_ascii=False))
if __name__=='__main__':main()
