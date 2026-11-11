"""Bounded, serial regional extracts; never invent ChinaTravel operational values."""
from __future__ import annotations
import argparse, collections, ctypes, gc, gzip, hashlib, json, sys, time, unicodedata
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.expansion_contract import FIELDS, VERSION, validate_record
from shorttrip.freshness import field_policy, POLICIES

# Deliberate research windows, NOT claims about full administrative boundaries.
CITIES=[
 ('西安','xian',[108.65,33.95,109.35,34.6]),
 ('天津','tianjin',[116.8,38.7,118.1,39.5]),
 ('郑州','zhengzhou',[113.35,34.5,114.05,35.0]),
 ('长沙','changsha',[112.65,27.9,113.35,28.55]),
 ('青岛','qingdao',[119.9,35.85,120.85,36.6]),
 ('济南','jinan',[116.65,36.4,117.5,37.05]),
 ('厦门','xiamen',[117.9,24.3,118.5,24.95]),
 ('福州','fuzhou',[119.0,25.8,119.8,26.5]),
 ('昆明','kunming',[102.35,24.55,103.2,25.4]),
 ('贵阳','guiyang',[106.25,26.15,107.15,27.0]),
 ('南宁','nanning',[108.0,22.5,108.8,23.2]),
 ('合肥','hefei',[116.85,31.45,117.75,32.25]),
 ('南昌','nanchang',[115.5,28.25,116.4,29.05]),
 ('沈阳','shenyang',[123.0,41.4,123.85,42.2]),
 ('大连','dalian',[121.2,38.65,122.2,39.5]),
 ('哈尔滨','haerbin',[126.1,45.4,127.1,46.2]),
 ('长春','changchun',[124.9,43.45,125.9,44.25]),
 ('石家庄','shijiazhuang',[114.1,37.75,115.0,38.45]),
 ('太原','taiyuan',[112.15,37.4,112.95,38.2]),
 ('兰州','lanzhou',[103.3,35.8,104.2,36.5]),
 ('乌鲁木齐','wulumuqi',[87.2,43.45,88.05,44.25]),
 ('呼和浩特','huhehaote',[111.3,40.5,112.15,41.2]),
 ('海口','haikou',[110.0,19.7,110.65,20.25]),
 ('三亚','sanya',[109.1,18.1,109.95,18.65]),
 ('无锡','wuxi',[119.8,31.25,120.85,31.95]),
 ('宁波','ningbo',[121.1,29.45,122.05,30.25]),
 ('温州','wenzhou',[120.25,27.6,121.2,28.35]),
 ('珠海','zhuhai',[113.0,21.9,113.7,22.6]),
 ('佛山','foshan',[112.6,22.6,113.5,23.4]),
 ('东莞','dongguan',[113.5,22.6,114.25,23.2]),
 ('泉州','quanzhou',[118.15,24.55,119.1,25.35]),
 ('扬州','yangzhou',[119.1,32.15,119.9,32.85]),
 ('常州','changzhou',[119.5,31.4,120.3,32.1]),
 ('黄山','huangshan',[117.7,29.5,118.7,30.4]),
 ('绍兴','shaoxing',[120.2,29.6,121.05,30.3]),
 ('威海','weihai',[121.7,36.85,122.6,37.65]),
 ('烟台','yantai',[120.9,37.0,121.9,37.85]),
 ('桂林','guilin',[109.95,24.8,110.8,25.6]),
 ('丽江','lijiang',[99.85,26.45,100.65,27.25]),
 ('大理','dali',[99.75,25.4,100.6,26.15]),
 ('洛阳','luoyang',[112.05,34.3,112.8,35.0]),
 ('开封','kaifeng',[114.1,34.55,114.8,35.15]),
 ('张家界','zhangjiajie',[110.05,28.8,110.8,29.65]),
 ('延安','yanan',[109.1,36.3,110.0,37.0]),
 ('敦煌','dunhuang',[94.35,39.85,95.1,40.5]),
 ('西宁','xining',[101.35,36.35,102.2,37.0]),
 ('拉萨','lasa',[90.7,29.35,91.6,30.0]),
 ('银川','yinchuan',[105.8,38.15,106.7,38.85]),
 ('北海','beihai',[108.8,21.25,109.6,21.9]),
 ('大同','datong',[113.0,39.8,113.7,40.45]),
 ('徐州','xuzhou',[116.85,33.95,117.65,34.6]),
 ('赣州','ganzhou',[114.6,25.45,115.45,26.2]),
 ('惠州','huizhou',[114.1,22.7,114.9,23.5]),
 ('中山','zhongshan',[113.1,22.2,113.7,22.85]),
 ('南通','nantong',[120.55,31.65,121.4,32.35]),
 ('镇江','zhenjiang',[119.1,31.9,119.9,32.6]),
 ('湖州','huzhou',[119.75,30.55,120.5,31.2]),
 ('嘉兴','jiaxing',[120.35,30.4,121.2,31.05]),
 ('金华','jinhua',[119.3,28.75,120.15,29.5]),
 ('台州','taizhou',[120.75,28.3,121.7,29.05]),
]
ATTRACTIONS={'museum','art_museum','history_museum','science_museum','gallery','art_gallery',
 'park','national_park','state_park','botanical_garden','garden','zoo','aquarium','theme_park',
 'amusement_park','historic_site','monument','landmark','tourist_attraction','beach','viewpoint',
 'scenic_overlook','castle','palace','temple','buddhist_temple','taoist_temple','memorial',
 'archaeological_site','arts_and_entertainment','tourist_information_center'}
# Broad categories above are narrowed below; neither business parking nor generic
# entertainment venues count as attractions.
ATTRACTIONS.discard('arts_and_entertainment');ATTRACTIONS.discard('tourist_information_center')
LODGING={'hotel','hostel','motel','resort','bed_and_breakfast','guest_house','inn','lodging'}
ACCEPTED_LICENSES={'CDLA-Permissive-2.0','Apache-2.0','CC0-1.0','CC-BY-4.0'}
def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def dumps(x):return json.dumps(x,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def rss_mb():
 class M(ctypes.Structure):
  _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong)]+[(x,ctypes.c_size_t) for x in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
 m=M();m.cb=ctypes.sizeof(m)
 kernel=ctypes.windll.kernel32;kernel.GetCurrentProcess.restype=ctypes.c_void_p
 get=ctypes.windll.psapi.GetProcessMemoryInfo
 get.argtypes=[ctypes.c_void_p,ctypes.POINTER(M),ctypes.c_ulong];get.restype=ctypes.c_int
 if not get(kernel.GetCurrentProcess(),ctypes.byref(m),m.cb):raise OSError('memory_monitor_failed')
 return round(m.PeakWorkingSetSize/1048576,2)
def kind_for(row):
 t=row.get('taxonomy') or {}; primary=t.get('primary'); h=t.get('hierarchy') or []
 if 'restaurant' in h or primary=='restaurant':return 'restaurant'
 if any(x in LODGING for x in h) or row.get('basic_category') in LODGING:return 'accommodation'
 if any(x in ATTRACTIONS for x in h) or row.get('basic_category') in ATTRACTIONS:return 'attraction'
 return None
def envelope(row,city,slug,line,raw_path,retrieved,release):
 from shapely import wkb
 kind=kind_for(row); name=(row.get('names') or {}).get('primary')
 if not kind or not name:return None,'irrelevant_or_unnamed'
 if row.get('operating_status') in ('permanently_closed','closed'):return None,'closed'
 addresses=row.get('addresses') or []
 if addresses and all(a.get('country') not in (None,'CN') for a in addresses):return None,'outside_cn'
 localities=[a.get('locality') for a in addresses if a.get('locality')]
 def norm(value):return ''.join(c for c in unicodedata.normalize('NFKD',value).lower() if c.isalnum())
 aliases={norm(slug),{'haerbin':'harbin','wulumuqi':'urumqi','huhehaote':'hohhot'}.get(slug,slug)}
 city_asserted=any(city in value or norm(value).removesuffix('shi') in aliases for value in localities)
 # Window-only candidates remain explicitly unverified and never planning-ready.
 src=row.get('sources') or []
 licences={s.get('license') for s in src if s.get('license')}
 if not licences or not licences<=ACCEPTED_LICENSES:return None,'unapproved_licence'
 p=wkb.loads(row['geometry'])
 if p.geom_type!='Point':return None,'non_point'
 data={f:None for f in FIELDS[kind]}
 data.update(id=int(hashlib.sha256(row['id'].encode()).hexdigest()[:12],16),name=name,lat=p.y,lon=p.x)
 category=(row.get('taxonomy') or {}).get('primary') or row.get('basic_category')
 if kind=='attraction':data['type']=category
 # Overture categories are evidence of category, not prices/cuisine/room capacity.
 sid='overture_places_20261021';url='https://docs.overturemaps.org/guides/places/'
 policy={f:field_policy(f,kind) for f in data}
 prov={f:{'source_id':sid,'source_url':url,'observed_at':None,
       'status':'unknown' if v is None else 'source_value',
       'source_property':{'lat':'geometry.coordinates[1]','lon':'geometry.coordinates[0]',
          'name':'names.primary','id':'derived_stable_id','type':'taxonomy.primary'}.get(f),
       'valid_until':None} for f,v in data.items()}
 prov['id']['status']='derived'
 tag={'tag':'category','value':category,'basis':'taxonomy.primary','status':'source_attribute_unverified',
      'policy_id':'theme','source_time_ref':'record.observed_at','valid_until':None}
 return {'schema_version':VERSION,'record_id':'overture:'+row['id'],'language':'zh',
  'kind':kind,'city':city,'city_slug':slug,'name':name,'data':data,'tags':[tag],
  'source_id':sid,'source_url':url,'source_locator':{'release':release,'gers_id':row['id'],
      'raw_file':raw_path,'raw_line':line,'raw_sha256':hashlib.sha256(dumps(row).encode()).hexdigest(),
      'providers':src,'city_assertions':localities,'provider_city_match':city_asserted,
      'city_assignment':'provider_locality' if city_asserted else 'research_window_unverified',
      'provider_confidence':row.get('confidence'),
      'release_date_is_not_fact_observation':True},
  'source_published_at':None,
  'source_updated_at':None,'observed_at':None,'retrieved_at':retrieved,'catalogued_at':retrieved,
  'valid_from':None,'valid_until':None,'field_policies':policy,'field_provenance':prov,
  'authority':'open_aggregate_dataset','licence_status':'allowed','licences':sorted(licences),
  'coordinate_system':'WGS84','coordinate_order':'named_lat_lon_columns','trust_status':'discovery_only',
  'entity_verified':False,'needs_live_verification':True,'synthetic':False,
  'uncertainty_flags':['unknown_fact_observation_time','operational_fields_missing',
                       'provider_city_assertion_not_boundary_validation','category_not_manually_reviewed']+
                       ([] if city_asserted else ['city_assignment_unverified'])},None
def collect(args):
 import overturemaps.core as ov
 import pyarrow as pa
 import pyarrow.compute as pc
 import pyarrow.parquet as pq
 import requests
 pa.set_cpu_count(1);pa.set_io_thread_count(1)
 out=ROOT/'data'/'expansion_v1_20261022';out.mkdir(parents=True,exist_ok=True)
 raw=out/'raw';raw.mkdir(exist_ok=True)
 if (out/'NETWORK_PAUSED.json').exists() and not args.resume_after_limit:
  raise RuntimeError('Source paused after HTTP429; explicit resume is required. No network request made.')
 release='2026-10-21.0';cities=CITIES[args.start:args.start+args.count]
 index_path=out/'collections.parquet'
 if not index_path.exists():
  response=requests.get(f'https://stac.overturemaps.org/{release}/collections.parquet',timeout=45)
  if response.status_code in (401,403,429):
   (out/'NETWORK_PAUSED.json').write_text(json.dumps({'at':now(),'status':response.status_code,
    'source':response.url,'retry_after':response.headers.get('Retry-After'),'no_automatic_fallback':True}),encoding='utf-8')
  response.raise_for_status();index_path.write_bytes(response.content)
 index=pq.read_table(index_path)
 def local_stac(theme,typ,box,rel):
  x1,y1,x2,y2=box.as_tuple()
  filt=((pc.field('collection')==typ)&(pc.field('type')=='Feature')&
        (pc.field('bbox','xmin')<x2)&(pc.field('bbox','xmax')>x1)&
        (pc.field('bbox','ymin')<y2)&(pc.field('bbox','ymax')>y1))
  return [x['aws']['alternate']['s3']['href'][5:] for x in index.filter(filt)['assets'].to_pylist()]
 ov._get_files_from_stac=local_stac
 manifest={'version':'expansion-v1-20261022','release':release,'created_at':now(),
   'source':'Overture Maps Foundation','licence_url':'https://docs.overturemaps.org/attribution/',
   'python_client':'overturemaps==1.0.2','method':'STAC selected GeoParquet files; serial bounded batches',
   'batch_size':512,'threads':1,'rss_limit_mib':args.memory_mb,'city_windows':cities,
   'not_full_city_boundaries':True,'fact_observation_not_inferred_from_release':True,'cities':[]}
 destination=out/'collection_manifest.json'
 started=time.monotonic()
 for city,slug,bbox in cities:
  rp=raw/(slug+'.jsonl.gz');ep=out/(slug+'.records.jsonl.gz');receipt=out/(slug+'.receipt.json')
  if receipt.exists():
   saved=json.loads(receipt.read_text(encoding='utf-8'));manifest['cities'].append(saved)
   print(dumps({'city':city,'cache':True,'counts':saved.get('counts')}),flush=True);continue
  counts=collections.Counter(); skips=collections.Counter(); seen=set(); retrieved=now()
  info={'city':city,'slug':slug,'bbox':bbox,'started_at':retrieved,'status':'running'}
  try:
   d,f=ov._prepare_query('place',bbox,release=release,connect_timeout=15,request_timeout=45,stac=True)
   info['cloud_files']=d.files if d else []
   if d:
    with gzip.open(rp,'wt',encoding='utf-8',newline='\n') as r,gzip.open(ep,'wt',encoding='utf-8',newline='\n') as e:
     for batch in d.to_batches(filter=f,batch_size=512,use_threads=False,batch_readahead=0,fragment_readahead=0):
      for row in batch.to_pylist():
       counts['scanned']+=1
       if not kind_for(row):continue
       if row['id'] in seen:skips['duplicate_gers_id']+=1;continue
       seen.add(row['id'])
       # Preserve a lossless WKB hex in evidence JSON, not an approximate bbox center.
       row['geometry']=row['geometry'].hex()
       record,reason=envelope(row,city,slug,counts['accepted']+1,str(rp.relative_to(ROOT)),retrieved,release)
       if reason:skips[reason]+=1;continue
       verdict=validate_record(record)
       if not verdict['discovery_ok']:raise ValueError(verdict['errors'])
       r.write(dumps(row)+'\n');e.write(dumps(record)+'\n')
       counts['accepted']+=1;counts[record['kind']]+=1;counts['planning_ready']+=verdict['planning_ready']
       counts['provider_city_match']+=record['source_locator']['provider_city_match']
      if rss_mb()>args.memory_mb:raise MemoryError('memory_guard_mib:'+str(rss_mb()))
   info['status']='complete'
  except Exception as exc:
   info['status']='incomplete';info['error']=type(exc).__name__+':'+str(exc)[:600]
  info.update(completed_at=now(),counts=dict(counts),skipped=dict(skips),peak_rss_mib=rss_mb())
  info['files']={str(p.relative_to(ROOT)):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in (rp,ep) if p.exists()}
  receipt.write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
  manifest['cities'].append(info);manifest['elapsed_seconds']=round(time.monotonic()-started,2)
  destination.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
  print(dumps(info|{'cloud_files':len(info.get('cloud_files',[])),'files':None}),flush=True)
  if info['status']!='complete':break
  del d;gc.collect()
  if time.monotonic()-started>args.seconds:break
  time.sleep(1)
 manifest['completed_at']=now();manifest['peak_rss_mib']=rss_mb()
 destination.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--start',type=int,default=0);p.add_argument('--count',type=int,default=60)
 p.add_argument('--seconds',type=int,default=1200);p.add_argument('--memory-mb',type=int,default=650)
 p.add_argument('--resume-after-limit',action='store_true',help='Only after explicit user direction and provider restrictions have cleared')
 collect(p.parse_args())
