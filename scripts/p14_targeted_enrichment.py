"""Bounded entity-targeted map retrieval; cache first, stop on provider failure."""
import argparse,collections,gzip,hashlib,json,re,sqlite3,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.live_amap import LiveAmapClient,LiveAmapError
from shorttrip.freshness import utcnow
from shorttrip.business_archives import name_aliases
from shorttrip.travel_catalog import digest_file
OUT=ROOT/'results/p14_targeted_completion'
SOURCE=ROOT/'data/business_catalog_v1_2_20261022/catalog.sqlite3'

def prepare():
    OUT.mkdir(exist_ok=True);(OUT/'private_api_raw').mkdir(exist_ok=True)
    db=sqlite3.connect(SOURCE.resolve().as_uri()+'?mode=ro',uri=True)
    counts=collections.defaultdict(collections.Counter);jobs=[];cities=collections.Counter()
    required={'attraction':['price','opentime','endtime','recommendmintime','recommendmaxtime'],
       'restaurant':['price','cuisine','opentime','endtime'],'accommodation':['price','numbed']}
    targets=[]
    for payload, in db.execute('SELECT payload FROM records ORDER BY city,id'):
        r=json.loads(payload);kind=r['kind']
        if kind not in required:continue
        miss=[k for k in required[kind] if r['data'].get(k) is None]
        counts[kind]['records']+=1;counts[kind]['complete_requested_native_values']+=not miss
        for k in miss:counts[kind]['missing:'+k]+=1
        # Target old entities, not the separate map restaurant list already collected.
        if r['record_id'].startswith('overture:') and r['source_locator'].get('provider_city_match'):
            cities[r['city']]+=1
            if kind=='restaurant' and miss and re.search('[\u4e00-\u9fff]',r['name']):targets.append(r)
    db.close()
    # Two entities per city in the first reviewable batch; preserve a full gap inventory.
    quota=collections.Counter()
    for r in targets:
        if quota[r['city']]>=2:continue
        quota[r['city']]+=1
        jobs.append({'entity_id':r['record_id'],'city':r['city'],'name':r['name'],'kind':r['kind'],
           'longitude_wgs84':r['data']['lon'],'latitude_wgs84':r['data']['lat'],
           'keywords':r['name'],'missing':[k for k in required[r['kind']] if r['data'].get(k) is None]})
    inventory={'prepared_at':utcnow(),'source_catalog':str(SOURCE.relative_to(ROOT)),
       'source_sha256':digest_file(SOURCE),'counts':{k:dict(v) for k,v in counts.items()},
       'eligible_cities':dict(cities),'targeted_restaurant_jobs':len(jobs),
       'remaining_eligible_restaurant_entities':len(targets)-len(jobs),'jobs':jobs,
       'no_default_values':True,'complete_values_are_not_current_planning_ready':True}
    path=OUT/'inventory.json'
    if not path.exists():path.write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
    return json.loads(path.read_text(encoding='utf-8'))

def run(limit,queue_file=None):
    inv=json.loads(queue_file.read_text(encoding='utf-8')) if queue_file else prepare()
    pause=OUT/'AMAP_PAUSED.json';old_pause=ROOT/'results/p13_business_completion/AMAP_PAUSED.json'
    if pause.exists() or old_pause.exists():raise RuntimeError('Provider stopped; no automatic retry or key rotation')
    client=LiveAmapClient(ROOT,budget=limit);entries=[]
    for job in inv['jobs']:
        key=hashlib.sha256(job['entity_id'].encode()).hexdigest()[:20];path=OUT/'private_api_raw'/(key+'.json')
        if path.exists():continue
        if client.spent>=limit:break
        try:
            response,meta=client._call('/v5/place/text',{'keywords':job['keywords'],'types':'050000',
              'region':job['city'],'city_limit':'true','page_num':1,'page_size':5,'show_fields':'business','output':'JSON'})
        except LiveAmapError as exc:
            fail={'at':utcnow(),'error':str(exc),'entity_id':job['entity_id'],'no_key_rotation':True}
            pause.write_text(json.dumps(fail,ensure_ascii=False,indent=2),encoding='utf-8');entries.append(fail);break
        packet={'target':job,'meta':meta,'response':response}
        path.write_text(json.dumps(packet,ensure_ascii=False,indent=2),encoding='utf-8')
        entries.append({'entity_id':job['entity_id'],'city':job['city'],'pois':len(response.get('pois',[])),'cache_file':str(path.relative_to(ROOT))})
        if client.spent%8==0:print(json.dumps({'progress_calls':client.spent,'provider_stopped':False},ensure_ascii=False),flush=True)
        time.sleep(1.3)
    report={'executed_at':utcnow(),'api_calls':client.spent,'provider_stopped':client.stopped,
       'budget':limit,'single_project_key':True,'entries':entries,'audit':client.audit,
       'cached_queries_total':len(list((OUT/'private_api_raw').glob('*.json')))}
    name='run_'+report['executed_at'].replace(':','').replace('+','_')+'.json'
    (OUT/name).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('api_calls','provider_stopped','cached_queries_total')},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--max-calls',type=int,default=4);p.add_argument('--prepare-only',action='store_true');p.add_argument('--queue-file',type=Path);a=p.parse_args()
    if a.prepare_only:
        inv=prepare();print(json.dumps({k:inv[k] for k in ('counts','targeted_restaurant_jobs','remaining_eligible_restaurant_entities')},ensure_ascii=False))
    elif not 1<=a.max_calls<=60:raise ValueError('Use a bounded 1..60 call batch')
    else:run(a.max_calls,a.queue_file)
