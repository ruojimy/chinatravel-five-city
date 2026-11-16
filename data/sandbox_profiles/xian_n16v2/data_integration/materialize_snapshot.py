"""Validate captured Amap evidence and materialize a new isolated benchmark snapshot.

Never writes entity CSVs or source snapshots. The same validated field overlay is
consumed by the model adapter and P34 scoped_frame. Non-unique fares, connections,
city/identity mismatches, missing dates and unsupported fields remain conditional.
"""
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import csv,json,math,re,sqlite3

HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
DB=ROOT/'expanded/G3_ext11/chinatravel/environment/database'
SOURCE=HERE/'snapshot_v4_source.json';CAPTURE=HERE/'live_capture/dynamic_live.sqlite3'
AUDIT=HERE/'materialization_audit.json';SNAPSHOT=HERE/'dynamic_snapshot_v2.json'
if AUDIT.exists() or SNAPSHOT.exists():raise FileExistsError('snapshot already materialized')
def digest(data):return sha256(data).hexdigest()
def read_json(path):return json.loads(path.read_text(encoding='utf-8-sig'))
conn=sqlite3.connect('file:'+CAPTURE.resolve().as_posix()+'?mode=ro',uri=True)
try:rows=conn.execute('SELECT id,cache_key,at_utc,status,meta_json,raw_sha256,response_json FROM calls ORDER BY id').fetchall()
finally:conn.close()
events={}
for idx,key,at,status,meta,rawsha,raw in rows:
    if status!='ok' or not raw or digest(raw.encode('utf-8'))!=rawsha:continue
    doc=json.loads(raw); metadata=json.loads(meta)
    if str(doc.get('status'))!='1' or str(doc.get('infocode'))!='10000':continue
    if not metadata.get('endpoint','').startswith('https://restapi.amap.com/v5/'):continue
    ts=datetime.fromisoformat(at)
    age=(datetime.now(timezone.utc)-ts).total_seconds()
    if age<0 or age>72*3600:continue
    events[idx]={'id':idx,'key':json.loads(key),'at_utc':at,'raw_sha256':rawsha,
                 'raw':doc,'meta':metadata}
if 1 not in events:raise ValueError('required source request missing, stale, or hash mismatch')
snapshot=read_json(SOURCE)
if snapshot.get('schema')!='chinatravel-dynamic-snapshot-v4.2':raise ValueError('wrong parent snapshot schema')
changes=[];rejections=[];entity_overlays=[];trains=[];stations=[]
slugs={'西安':'xian','重庆':'chongqing','成都':'chengdu'}
adcodes={'西安':'6101','重庆':'5001','成都':'5101'}
def dist(a,b):return math.hypot((a[0]-b[0])*111000,(a[1]-b[1])*111000*math.cos(math.radians((a[0]+b[0])/2)))
def coord(value):
    parts=re.split(r'[ ,]+',str(value or '').strip())
    if len(parts)!=2:return None
    try:lon,lat=map(float,parts)
    except (TypeError,ValueError):return None
    return [lat,lon] if 70<lon<140 and 15<lat<55 else None
def clock(value):
    text=str(value or '')
    if not re.fullmatch(r'\d{4,5}',text):return None
    hour,minute=int(text[:-2]),int(text[-2:])
    if hour>=72 or minute>59:return None
    return hour*60+minute
poi_cache={}
def poi(city):
    if city not in poi_cache:
        path=DB/'poi'/slugs[city]/'poi.json';raw=path.read_bytes()
        poi_cache[city]={'path':path,'before':raw,'rows':json.loads(raw.decode('utf-8-sig')),'changed':False}
    return poi_cache[city]

# Entity: match record identity in frozen CSV, exact provider name/city/id,
# valid GCJ02 point and proximity to old reference (not treated as verified).
event=events[1];key=event['key'];doc=event['raw']
if key!=['attraction:xian:8','西安','attraction','回民街']:
    raise ValueError('entity capture does not match intended record')
csv_path=DB/'attractions/xian/attractions.csv';csv_raw=csv_path.read_bytes()
with csv_path.open(encoding='utf-8-sig',newline='') as f:catalog=list(csv.DictReader(f))
catalog=[x for x in catalog if x.get('id')=='8' and x.get('name')=='回民街']
matches=[x for x in doc.get('pois',[]) if x.get('name')=='回民街' and '西安' in str(x.get('cityname') or '')
         and str(x.get('adcode') or '').startswith('6101') and x.get('id')]
if len(catalog)!=1 or len(matches)!=1:raise ValueError('entity identity not unique')
point=coord(matches[0].get('location'))
try:old=[float(catalog[0]['lat']),float(catalog[0]['lon'])]
except (TypeError,ValueError):old=None
if not point or not old or dist(old,point)>1000:raise ValueError('entity point or proximity invalid')
p=poi('西安');old_poi=[x for x in p['rows'] if x.get('name')=='回民街']
if len(old_poi)!=1 or dist(old_poi[0].get('position'),point)>1000:raise ValueError('POI match invalid')
old_poi[0]['position']=point;p['changed']=True
entity_overlays.append({'record_id':'attraction:xian:8','city':'西安','name':'回民街',
    'source_csv_sha256':digest(csv_raw),'fields':{'lat':point[0],'lon':point[1]},
    'field_provenance':{'lat':'amap_same_name_city_poi','lon':'amap_same_name_city_poi'},
    'coordinate_system':'GCJ02','provider_poi_id':matches[0]['id'],
    'provider_url':'https://www.amap.com/place/'+matches[0]['id'],
    'captured_at_utc':event['at_utc'],'source_raw_sha256':event['raw_sha256'],
    'evidence_path':'live_capture/dynamic_live.sqlite3','source_row_id':event['id'],
    'status':'single_provider_conditionally_verified','prior_reference_position':old,
    'prior_reference_distance_m':round(dist(old,point),1),
    'boundary':'Identity and coordinate match only; current opening, booking and other fields are not inferred.'})
entity_overlays[-1]['field_conflicts']=[{'fields':['opentime','endtime'],
    'status':'conflict_unresolved_do_not_treat_as_current','benchmark_value':['10:00','23:00'],
    'benchmark_source':'attractions/xian/attractions.csv; historical sandbox value',
    'amap_value':(matches[0].get('business') or {}).get('opentime_today'),
    'amap_source_raw_sha256':event['raw_sha256'],'amap_evidence_path':'live_capture/dynamic_live.sqlite3',
    'amap_source_row_id':event['id'],
    'rule_planner_limitation':'uses historical benchmark hours; pass does not establish current operating hours'}]
# Existing data says 10:00–23:00; provider says 24h. Preserve source and report
# conflict rather than silently replacing the operating interval.
rejections.append({'record_id':'attraction:xian:8','field':'opening_hours',
                   'source_value':[catalog[0]['opentime'],catalog[0]['endtime']],
                   'provider_value':(matches[0].get('business') or {}).get('opentime_today'),
                   'reason':'conflicting_operating_hours_no_override'})

# Direct railway legs only. Four-digit clock may be >24h in source; modulo is
# stored in the native schema while source duration/date evidence stays intact.
for idx,from_city,to_city in [(2,'西安','重庆'),(4,'成都','西安')]:
    event=events.get(idx)
    if not event:rejections.append({'request':idx,'reason':'provider_not_available'});continue
    if event['key'][0]!=f'transport:{from_city}:{to_city}:any':raise ValueError('direction capture mismatch')
    path=DB/'intercity_transport/train'/f'from_{from_city}_to_{to_city}.json';before=path.read_bytes()
    records=json.loads(before.decode('utf-8-sig'));changed=False
    rails=[seg['railway'] for transit in event['raw'].get('route',{}).get('transits',[])
           for seg in transit.get('segments',[]) if isinstance(seg.get('railway'),dict)]
    for rail in rails:
        ident=rail.get('trip');departure=rail.get('departure_stop') or {};arrival=rail.get('arrival_stop') or {}
        if not isinstance(ident,str) or not re.fullmatch(r'[A-Z]\d{1,5}(?:/[A-Z]?\d{1,5})?',ident):
            rejections.append({'id':ident,'reason':'invalid_train_id'});continue
        if not str(departure.get('adcode','')).startswith(adcodes[from_city]) or not str(arrival.get('adcode','')).startswith(adcodes[to_city]):
            rejections.append({'id':ident,'reason':'not_direct_between_requested_cities'});continue
        start,end=clock(departure.get('time')),clock(arrival.get('time'))
        try:seconds=int(rail.get('time'))
        except (TypeError,ValueError):seconds=0
        if start is None or end is None or seconds<=0 or abs((seconds/60)%1440-(end-start)%1440)>2:
            rejections.append({'id':ident,'reason':'time_duration_mismatch'});continue
        seat='火车二等座' if ident.startswith(('G','D','C')) else '火车硬座'
        fares=set()
        for x in rail.get('spaces',[]):
            if x.get('code')!=seat:continue
            try:value=float(x['cost'])
            except (KeyError,TypeError,ValueError):continue
            if math.isfinite(value) and value>=0:fares.add(value)
        if len(fares)!=1:
            rejections.append({'id':ident,'reason':'seat_price_missing_or_ambiguous','values':sorted(fares)});continue
        pending=[];valid=True
        for city,stop in [(from_city,departure),(to_city,arrival)]:
            name=stop.get('name');location=coord(stop.get('location'));store=poi(city)
            existing=[x for x in store['rows'] if x.get('name')==name]
            if not isinstance(name,str) or not name or not location or len(existing)>1:
                valid=False;break
            if existing and dist(existing[0]['position'],location)>1000:valid=False;break
            if not existing:pending.append((city,name,location,stop.get('id')))
        if not valid:rejections.append({'id':ident,'reason':'station_identity_not_matched'});continue
        if any(x.get('TrainID')==ident for x in records):
            rejections.append({'id':ident,'reason':'existing_train_requires_exact_field_merge'});continue
        for city,name,location,provider_id in pending:
            store=poi(city);store['rows'].append({'name':name,'position':location});store['changed']=True
            stations.append({'city':city,'name':name,'position':location,'provider_id':provider_id,
                             'source_raw_sha256':event['raw_sha256']})
        # Chengdu East railway/POI provider IDs match exactly. Update the old
        # suffixed alias in this independent copy to the same observed point.
        if from_city=='成都' and departure.get('id')=='B001C80DL2':
            station_event=events.get(3);obs=((station_event or {}).get('meta',{}).get('observation') or {})
            if obs.get('source_url','').endswith('/B001C80DL2') and coord(obs.get('location'))==coord(departure.get('location')):
                store=poi('成都');suffix=[x for x in store['rows'] if x.get('name')=='成都东站']
                if len(suffix)==1 and dist(suffix[0]['position'],coord(obs['location']))<1000:
                    suffix[0]['position']=coord(obs['location']);store['changed']=True
                    stations.append({'city':'成都','name':'成都东站','position':coord(obs['location']),
                                     'provider_id':'B001C80DL2','source_raw_sha256':station_event['raw_sha256']})
        value=next(iter(fares));fare=int(value) if value.is_integer() else value
        row={'TrainID':ident,'TrainType':'高铁' if ident.startswith(('G','D','C')) else '普速',
             'From':departure['name'],'To':arrival['name'],'BeginTime':f'{(start//60)%24:02}:{start%60:02}',
             'EndTime':f'{(end//60)%24:02}:{end%60:02}','Duration':round(seconds/3600,2),'Cost':fare}
        records.append(row);changed=True
        trains.append({'from_city':from_city,'to_city':to_city,'record':row,'seat':seat,
                       'observation_time_utc':event['at_utc'],'source_raw_sha256':event['raw_sha256'],
                       'evidence_path':'live_capture/dynamic_live.sqlite3','source_row_id':event['id'],
                       'trip_date':None,'availability':'unknown','status':'new_amap_conditional_reference'})
    if changed:path.write_text(json.dumps(records,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
    changes.append({'path':str(path.relative_to(ROOT)).replace('\\','/'),'before_sha256':digest(before),'after_sha256':digest(path.read_bytes())})
for city,store in poi_cache.items():
    if store['changed']:
        store['path'].write_text(json.dumps(store['rows'],ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
    changes.append({'path':str(store['path'].relative_to(ROOT)).replace('\\','/'),
                    'before_sha256':digest(store['before']),'after_sha256':digest(store['path'].read_bytes())})
audit={'source_sqlite_sha256':digest(CAPTURE.read_bytes()),'parent_snapshot_sha256':digest(SOURCE.read_bytes()),
       'entity_overlays':entity_overlays,'trains_added':trains,'stations_changed':stations,
       'rejections':rejections,'changed_files':changes,'entity_csv_was_not_modified':True,
       'boundary':'Single-provider observations and no travel date: conditional benchmark references, not proof of real-world availability.'}
with AUDIT.open('x',encoding='utf-8') as f:json.dump(audit,f,ensure_ascii=False,indent=2);f.write('\n')
snapshot['entity_overlays']=entity_overlays
snapshot['direct_trains']=snapshot.get('direct_trains',[])+trains
snapshot['dynamic_stations']=snapshot.get('dynamic_stations',[])+stations
snapshot['v5_parent_snapshot_sha256']=digest(SOURCE.read_bytes())
snapshot['v5_materialization_audit_sha256']=digest(AUDIT.read_bytes())
snapshot['v5_provider_budget']=4;snapshot['v5_provider_calls_used']=len(rows)
lookup={str(x['path']).replace('\\','/'):x for x in snapshot.get('changed_direct_files',[])}
for change in changes:lookup[change['path']]=change
snapshot['changed_direct_files']=list(lookup.values())
for item in ['snapshot_v4_source.json','live_capture/dynamic_live.sqlite3','live_capture_evidence.json','materialization_audit.json']:
    snapshot['evidence_files'].append({'path':item,'sha256':digest((HERE/item).read_bytes())})
snapshot['boundary']+=' v5 adds independently observed conditional fields and direct trains; raw CSVs unchanged.'
with SNAPSHOT.open('x',encoding='utf-8') as f:json.dump(snapshot,f,ensure_ascii=False,indent=2);f.write('\n')
print(json.dumps({'entity_fields':len(entity_overlays),'trains_added':len(trains),'stations_changed':len(stations),
                  'rejections':len(rejections),'snapshot_sha256':digest(SNAPSHOT.read_bytes())},ensure_ascii=False))
