"""Verify captured provider responses and materialize an immutable sandbox copy.

Never modifies the input. New rail records and exact-field fare fills share the
same native train files used by the model and rule planner. Other claims remain
reference-only unless their field-specific validation permits materialization.
"""
from collections import defaultdict
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import argparse,csv,json,math,re,shutil,sqlite3

HERE=Path(__file__).resolve().parent
CITIES={'北京':('beijing','1101'),'上海':('shanghai','3101'),'南京':('nanjing','3201'),
 '苏州':('suzhou','3205'),'杭州':('hangzhou','3301'),'深圳':('shenzhen','4403'),
 '成都':('chengdu','5101'),'武汉':('wuhan','4201'),'广州':('guangzhou','4401'),
 '重庆':('chongqing','5001'),'西安':('xian','6101')}
def digest(value):return sha256(value).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def distance(a,b):return math.hypot((a[0]-b[0])*111000,(a[1]-b[1])*111000*math.cos(math.radians((a[0]+b[0])/2)))
def coord(value):
    parts=re.split(r'[ ,]+',str(value or '').strip())
    try:lon,lat=map(float,parts)
    except (ValueError,TypeError):return None
    return [lat,lon] if 70<lon<140 and 15<lat<55 else None
def clock(value):
    s=str(value or '')
    if not re.fullmatch(r'\d{4,5}',s):return None
    h,m=int(s[:-2]),int(s[-2:])
    return h*60+m if h<72 and m<60 else None
def hhmm(v):return f'{(v//60)%24:02}:{v%60:02}'
def finite_price(v):
    try:x=float(v)
    except (ValueError,TypeError):return None
    return x if math.isfinite(x) and x>=0 else None

def load_events(journal):
    con=sqlite3.connect('file:'+journal.as_posix()+'?mode=ro',uri=True)
    try:rows=con.execute('SELECT id,cache_key,at_utc,status,meta_json,raw_sha256,response_json FROM calls ORDER BY id').fetchall()
    finally:con.close()
    result=[]
    for id,key,at,status,meta,rawsha,raw in rows:
        event={'id':id,'at':at,'status':status,'raw_sha256':rawsha}
        try:
            event.update(key=json.loads(key),meta=json.loads(meta))
            if status!='ok' or not raw:raise ValueError('provider_call_failed')
            if digest(raw.encode('utf-8'))!=rawsha:raise ValueError('raw_hash_mismatch')
            event['raw']=json.loads(raw)
            if str(event['raw'].get('status'))!='1' or str(event['raw'].get('infocode'))!='10000':raise ValueError('provider_response_error')
            when=datetime.fromisoformat(at)
            age=(datetime.now(timezone.utc)-when).total_seconds()
            if age<0 or age>72*3600:raise ValueError('stale_or_future_observation')
        except Exception as exc:event['error']=str(exc)
        result.append(event)
    return result

def rail_candidates(event):
    key=event.get('key') or []
    if len(key)!=4 or key[2]!='transport' or not str(key[0]).startswith('transport:'):
        return [],[{'call_id':event['id'],'reason':'not_transport'}]
    _,origin,destination,mode=key[0].split(':',3)
    if origin not in CITIES or destination not in CITIES or key[1]!=origin or key[3]!=f'{origin}->{destination}':
        return [],[{'call_id':event['id'],'reason':'direction_identity_mismatch'}]
    if event['meta'].get('endpoint')!='https://restapi.amap.com/v5/direction/transit/integrated':
        return [],[{'call_id':event['id'],'reason':'wrong_endpoint'}]
    results=[];reject=[]
    for transit in (event['raw'].get('route') or {}).get('transits',[]):
        rails=[s['railway'] for s in transit.get('segments',[]) if isinstance(s.get('railway'),dict) and s['railway']]
        if len(rails)!=1:
            reject.append({'call_id':event['id'],'reason':'transfer_or_no_rail','rail_legs':len(rails)});continue
        r=rails[0];ident=r.get('trip');a=r.get('departure_stop') or {};b=r.get('arrival_stop') or {}
        def reject_one(reason,**extra):reject.append({'call_id':event['id'],'train_id':ident,'reason':reason,**extra})
        if not isinstance(ident,str) or not re.fullmatch(r'[A-Z]\d{1,5}(?:/[A-Z]?\d{1,5})?',ident):reject_one('invalid_train_id');continue
        if not str(a.get('adcode','')).startswith(CITIES[origin][1]) or not str(b.get('adcode','')).startswith(CITIES[destination][1]):reject_one('not_direct_between_requested_cities');continue
        start,end=clock(a.get('time')),clock(b.get('time'))
        try:seconds=int(r.get('time'))
        except (ValueError,TypeError):seconds=0
        if start is None or end is None or seconds<=0 or abs((seconds/60)%1440-(end-start)%1440)>2:
            reject_one('time_duration_mismatch');continue
        seat='火车二等座' if ident.startswith(('G','D','C')) else '火车硬座'
        fares={v for x in r.get('spaces',[]) if isinstance(x,dict) and x.get('code')==seat
               for v in [finite_price(x.get('cost'))] if v is not None}
        if len(fares)!=1:reject_one('seat_fare_missing_or_conflicting',values=sorted(fares));continue
        if not all(isinstance(s.get('name'),str) and s.get('name') and s.get('id') and coord(s.get('location')) for s in (a,b)):
            reject_one('station_identity_missing');continue
        fare=next(iter(fares));row={'TrainID':ident,'TrainType':'高铁' if ident.startswith(('G','D','C')) else '普速',
            'From':a['name'],'To':b['name'],'BeginTime':hhmm(start),'EndTime':hhmm(end),
            'Duration':round(seconds/3600,2),'Cost':int(fare) if fare.is_integer() else fare}
        results.append({'origin':origin,'destination':destination,'row':row,'seat':seat,
            'stations':[{'city':origin,'name':a['name'],'provider_id':a['id'],'position':coord(a['location'])},
                        {'city':destination,'name':b['name'],'provider_id':b['id'],'position':coord(b['location'])}],
            'call_id':event['id'],'at':event['at'],'raw_sha256':event['raw_sha256'],
            'trip_date':event['meta'].get('params',{}).get('date'),'availability':'unknown'})
    return results,reject

def main():
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--journal',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--stage-budget',type=int,default=4);args=p.parse_args()
    base=args.base.resolve();journal=args.journal.resolve();out=args.output.resolve()
    if out.exists():raise FileExistsError('output must be new; input snapshots immutable')
    if out==base or base in out.parents:raise ValueError('output must not be inside the input snapshot')
    parent=read(base/'data_integration/dynamic_snapshot_v2.json')
    for e in parent['evidence_files']:
        f=(base/'data_integration'/e['path']).resolve()
        if not f.is_relative_to((base/'data_integration').resolve()) or digest(f.read_bytes())!=e['sha256']:raise ValueError('parent evidence hash mismatch')
    for e in parent['changed_direct_files']:
        f=(base/e['path']).resolve()
        if not f.is_relative_to(base) or digest(f.read_bytes())!=e['after_sha256']:raise ValueError('parent database hash mismatch')
    events=load_events(journal)
    db_meta=sqlite3.connect('file:'+journal.as_posix()+'?mode=ro',uri=True)
    try:used=int((db_meta.execute("SELECT value FROM meta WHERE key='count'").fetchone() or ['0'])[0])
    finally:db_meta.close()
    if args.stage_budget<1 or used>args.stage_budget:raise ValueError('provider stage budget inconsistent')
    stages=parent.get('provider_stages') or [
      {'stage':'v4_prefetch','calls_used':parent.get('provider_calls_used',0),'budget':parent.get('provider_budget',0)},
      {'stage':'v5_prefetch','calls_used':parent.get('v5_provider_calls_used',0),'budget':parent.get('v5_provider_budget',0)}]
    parent['provider_stages']=stages+[{'stage':'incremental_amap_rail','calls_used':used,'budget':args.stage_budget}]
    parent['provider_total_calls_used']=sum(int(s['calls_used']) for s in parent['provider_stages'])
    parent['provider_total_budget']=sum(int(s['budget']) for s in parent['provider_stages'])
    parent['provider_calls_used']=used;parent['provider_budget']=args.stage_budget
    parent['provider_state']='budget_exhausted' if used>=args.stage_budget else 'budget_remaining'
    out.mkdir(parents=True)
    shutil.copytree(base/'expanded',out/'expanded',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    dat=out/'data_integration';dat.mkdir()
    for e in parent['evidence_files']:
        src=base/'data_integration'/e['path'];dst=dat/e['path'];dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    for src in (base/'data_integration').glob('*.py'):shutil.copy2(src,dat/src.name)
    number=1
    while (dat/f'new_capture_{number}.sqlite3').exists():number+=1
    capture=f'new_capture_{number}.sqlite3';shutil.copy2(journal,dat/capture)
    journal_hash=digest((dat/capture).read_bytes());db=out/'expanded/G3_ext11/chinatravel/environment/database'
    accepted=[];rejected=[];changed={};poi_cache={};train_cache={};anchors={}
    city_codes={'北京':'010','上海':'021','南京':'025','苏州':'0512','杭州':'0571','深圳':'0755',
                '成都':'028','武汉':'027','广州':'020','重庆':'023','西安':'029'}
    def document(path,cache):
        if path not in cache:
            raw=path.read_bytes();cache[path]={'before':raw,'data':json.loads(raw.decode('utf-8-sig')),'dirty':False}
        return cache[path]
    for event in events:
        if event.get('error'):
            rejected.append({'call_id':event['id'],'reason':event['error']});continue
        key=event.get('key') or []
        if len(key)==4 and key[2]=='station':
            _,city,_,name=key
            meta=event['meta'];matches=[x for x in event['raw'].get('pois',[]) if x.get('name')==name
                and x.get('cityname') in (city,city+'市') and str(x.get('adcode','')).startswith(CITIES.get(city,('','!'))[1])
                and x.get('id') and coord(x.get('location'))]
            if (city in CITIES and meta.get('endpoint')=='https://restapi.amap.com/v5/place/text' and
                meta.get('params',{}).get('keywords')==name and meta.get('params',{}).get('region')==city and len(matches)==1):
                poi=matches[0];anchors[city]={'city':city,'name':name,'code':city_codes[city],
                    'location':poi['location'],'provider_poi_id':poi['id'],'source_journal':capture,
                    'source_journal_sha256':journal_hash,'source_call_id':event['id'],
                    'source_raw_sha256':event['raw_sha256'],'observed_at_utc':event['at'],
                    'status':'single_provider_coordinate_reference','coordinate_system':'GCJ02'}
            else:rejected.append({'call_id':event['id'],'reason':'station_anchor_identity_unverified'})
            continue
        if len(key)!=4 or key[2]!='transport':continue
        candidates,invalid=rail_candidates(event);rejected.extend(invalid)
        for candidate in candidates:
            row=candidate['row'];origin=candidate['origin'];destination=candidate['destination']
            old=[x for x in parent.get('direct_trains',[]) if x.get('from_city')==origin and x.get('to_city')==destination
                 and x.get('record',{}).get('TrainID')==row['TrainID']]
            if old:
                rejected.append({'call_id':event['id'],'train_id':row['TrainID'],'reason':'dynamic_train_already_present'});continue
            path=db/'intercity_transport/train'/f'from_{origin}_to_{destination}.json';store=document(path,train_cache)
            matches=[x for x in store['data'] if x.get('TrainID')==row['TrainID']]
            same=[x for x in matches if all(x.get(k)==row[k] for k in ('From','To','BeginTime','EndTime'))
                  and finite_price(x.get('Duration')) is not None and abs(float(x['Duration'])-row['Duration'])<=0.02]
            if len(matches)>1 or matches and len(same)!=1:
                rejected.append({'call_id':event['id'],'train_id':row['TrainID'],'reason':'existing_identity_or_timing_conflict'});continue
            if same and finite_price(same[0].get('Cost')) is not None and abs(float(same[0]['Cost'])-row['Cost'])>0.01:
                rejected.append({'call_id':event['id'],'train_id':row['TrainID'],'reason':'existing_fare_conflict','existing':same[0]['Cost'],'observed':row['Cost']});continue
            pending=[];station_error=None
            for station in candidate['stations']:
                poi_path=db/'poi'/CITIES[station['city']][0]/'poi.json';poi=document(poi_path,poi_cache)
                matches_poi=[x for x in poi['data'] if x.get('name')==station['name']]
                if len(matches_poi)>1:station_error='ambiguous_existing_station';break
                if matches_poi:
                    try:delta=distance(matches_poi[0]['position'],station['position'])
                    except (TypeError,ValueError,IndexError):station_error='invalid_station_position';break
                    if delta>1000:station_error='conflicting_station_position';break
                    station['reference_distance_m']=round(delta,1)
                else:pending.append((poi,station))
            if station_error:
                rejected.append({'call_id':event['id'],'train_id':row['TrainID'],'reason':station_error});continue
            for poi,station in pending:
                poi['data'].append({'name':station['name'],'position':station['position']});poi['dirty']=True
            if same:
                if finite_price(same[0].get('Cost')) is None:same[0]['Cost']=row['Cost'];store['dirty']=True
                final=dict(same[0]);action='existing_exact_fare_fill'
            else:store['data'].append(row);store['dirty']=True;final=row;action='new_direct_train'
            entry={'from_city':origin,'to_city':destination,'record':final,'seat':candidate['seat'],
                   'currency':'CNY','currency_basis':'Amap mainland China seat-fare context',
                   'observation_time_utc':candidate['at'],'source_raw_sha256':candidate['raw_sha256'],
                   'evidence_path':capture,'source_row_id':candidate['call_id'],'trip_date':candidate['trip_date'],
                   'availability':'unknown','status':'new_amap_conditional_reference','action':action,
                   'station_evidence':candidate['stations']}
            parent.setdefault('direct_trains',[]).append(entry);accepted.append(entry)
    for path,store in list(poi_cache.items())+list(train_cache.items()):
        if not store['dirty']:continue
        path.write_text(json.dumps(store['data'],ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
        rel=path.relative_to(out).as_posix();old=next((e for e in parent['changed_direct_files'] if e['path'].replace('\\','/')==rel),None)
        if old:old['after_sha256']=digest(path.read_bytes())
        else:parent['changed_direct_files'].append({'path':rel,'before_sha256':digest(store['before']),'after_sha256':digest(path.read_bytes())})
        changed[rel]=digest(path.read_bytes())
    audit={'schema':'dynamic-materialization-audit-v1','journal_sha256':journal_hash,
           'parent_snapshot_sha256':digest((base/'data_integration/dynamic_snapshot_v2.json').read_bytes()),
           'calls':[{'id':e['id'],'status':e['status'],'error':e.get('error'),'raw_sha256':e.get('raw_sha256')} for e in events],
           'accepted_trains':accepted,'rejected':rejected,'changed_direct_files':changed,
           'boundary':'Date-unspecified seat fares are conditional benchmark references, not bookings. Transfer legs and route totals are not direct train tickets.'}
    ap=dat/f'new_materialization_audit_{number}.json';ap.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    parent['evidence_files'].extend([{'path':capture,'sha256':journal_hash},{'path':ap.name,'sha256':digest(ap.read_bytes())}])
    anchor_path=dat/f'amap_anchors_{number}.json'
    anchor_path.write_text(json.dumps({'schema':'amap-verified-anchor-v1','anchors':anchors},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    parent['evidence_files'].append({'path':anchor_path.name,'sha256':digest(anchor_path.read_bytes())})
    parent.setdefault('anchor_evidence',[]).append({'path':anchor_path.name,'sha256':digest(anchor_path.read_bytes())})
    parent.pop('snapshot_sha256',None)
    snap=dat/'dynamic_snapshot_v2.json';snap.write_text(json.dumps(parent,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'snapshot':str(snap),'snapshot_sha256':digest(snap.read_bytes()),'accepted':len(accepted),
                      'rejected':len(rejected),'trains':[x['record']['TrainID'] for x in accepted]},ensure_ascii=False))

if __name__=='__main__':main()
