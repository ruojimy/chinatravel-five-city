"""Create a new snapshot from one completed dynamic_live place observation.

The current snapshot is never edited. This intentionally narrow updater accepts
only missing/derived coordinates with unique exact identity and proximity to an
existing reference point. It never turns Amap business.cost into ticket price.
"""
import argparse,csv,json,math,shutil,sqlite3,sys
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path

HERE=Path(__file__).resolve().parent
BASE=HERE.parent
sys.path.insert(0,str(BASE/'expanded'))
from sandbox_adapter import Sandbox
import dynamic_runtime

def digest(data):return sha256(data).hexdigest()
def dist(a,b):return math.hypot((a[0]-b[0])*111000,(a[1]-b[1])*111000*math.cos(math.radians((a[0]+b[0])/2)))
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--journal',required=True,help='completed dynamic_live.sqlite3')
    p.add_argument('--call-id',required=True,type=int)
    p.add_argument('--output',required=True,help='new, nonexistent snapshot root')
    a=p.parse_args()
    output=Path(a.output).resolve();journal=Path(a.journal).resolve()
    if output.exists():raise ValueError('output already exists; snapshots are immutable')
    if output==BASE or BASE in output.parents and not output.is_relative_to(HERE/'next_snapshots'):
        raise ValueError('nested snapshots must live under data_integration/next_snapshots')
    data=dynamic_runtime.load_snapshot()
    con=sqlite3.connect('file:'+journal.as_posix()+'?mode=ro',uri=True)
    try:r=con.execute('SELECT cache_key,at_utc,status,meta_json,raw_sha256,response_json FROM calls WHERE id=?',(a.call_id,)).fetchone()
    finally:con.close()
    if not r:raise ValueError('call not found')
    key,at,status,meta,rawhash,raw=r
    if status!='ok' or not raw or digest(raw.encode('utf-8'))!=rawhash:raise ValueError('failed/missing/corrupt evidence')
    key=json.loads(key);meta=json.loads(meta);response=json.loads(raw)
    if len(key)!=4:raise ValueError('invalid call identity')
    record_id,city,kind,name=key
    if kind not in ('attraction','restaurant','accommodation'):raise ValueError('only entity coordinates supported')
    if meta.get('endpoint')!='https://restapi.amap.com/v5/place/text' or str(response.get('infocode'))!='10000' or str(response.get('status'))!='1':
        raise ValueError('wrong endpoint or provider failure')
    if meta.get('params',{}).get('keywords')!=name or meta.get('params',{}).get('region')!=city:
        raise ValueError('search request identity mismatch')
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(at)).total_seconds()
    ttl=72 if kind=='attraction' else 168 if kind=='restaurant' else 24
    if not 0<=age<=ttl*3600:raise ValueError('stale or future observation')
    s=Sandbox('G3');path,_,rows,_,_,_,_=s._catalog(kind,city)
    matches=[(i,r) for i,r in enumerate(rows) if f"{kind}:{s.cities[city]}:{r.get('id')}"==record_id and r.get('name')==name]
    if len(matches)!=1:raise ValueError('source record not uniquely matched')
    i,row=matches[0];item=s._record(kind,city,i);view=item['payload'];ref=view['access']['reference_fields']
    if not all(k in ref or view['data'].get(k) is None or view['access'].get('dynamic_field_evidence') for k in ('lat','lon')):
        raise ValueError('source has independently known coordinates; do not override')
    pois=[x for x in response.get('pois',[]) if x.get('name')==name and x.get('cityname') in (city,city+'市') and x.get('id')]
    if len(pois)!=1:raise ValueError('provider identity is missing or ambiguous')
    parts=str(pois[0].get('location') or '').split(',')
    if len(parts)!=2:raise ValueError('invalid provider coordinate')
    lon,lat=map(float,parts);point=[lat,lon]
    if not (70<lon<140 and 15<lat<55):raise ValueError('coordinate out of range')
    old=[float(row['lat']),float(row['lon'])]
    if not all(math.isfinite(x) for x in old) or dist(old,point)>1000:raise ValueError('reference position missing or distant')
    poi_path=s.db/'poi'/s.cities[city]/'poi.json';poi_raw=poi_path.read_bytes();poi=json.loads(poi_raw.decode('utf-8-sig'))
    pm=[x for x in poi if x.get('name')==name]
    if len(pm)!=1 or dist(pm[0]['position'],point)>1000:raise ValueError('POI match missing or distant')
    pm[0]['position']=point
    # Nothing is written until all validation above succeeds.
    output.mkdir(parents=True)
    shutil.copytree(BASE/'expanded',output/'expanded',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    target=output/'data_integration';target.mkdir()
    for entry in data['evidence_files']:
        src=HERE/entry['path'];dst=target/entry['path'];dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    for source in HERE.glob('*.py'):shutil.copy2(source,target/source.name)
    capture='next_capture.sqlite3';shutil.copy2(journal,target/capture)
    rel=poi_path.relative_to(BASE);dest=output/rel
    dest.write_text(json.dumps(poi,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    overlay={'record_id':record_id,'city':city,'name':name,'source_csv_sha256':digest(path.read_bytes()),
      'fields':{'lat':lat,'lon':lon},'field_provenance':{'lat':'amap_same_name_city_poi','lon':'amap_same_name_city_poi'},
      'coordinate_system':'GCJ02','provider_poi_id':pois[0]['id'],'provider_url':'https://www.amap.com/place/'+pois[0]['id'],
      'captured_at_utc':at,'source_raw_sha256':rawhash,'evidence_path':capture,'source_row_id':a.call_id,
      'status':'single_provider_conditionally_verified','prior_reference_position':old,
      'prior_reference_distance_m':round(dist(old,point),1),'boundary':'coordinate only; no ticket, opening or travel-date inference'}
    previous=next((x for x in data.get('entity_overlays',[]) if x['record_id']==record_id),None)
    if previous and previous.get('field_conflicts'):
        overlay['field_conflicts']=previous['field_conflicts']
    data['entity_overlays']=[x for x in data.get('entity_overlays',[]) if x['record_id']!=record_id]+[overlay]
    data['evidence_files'].append({'path':capture,'sha256':digest((target/capture).read_bytes())})
    old_entry=next((x for x in data['changed_direct_files'] if x['path'].replace('\\','/')==rel.as_posix()),None)
    if old_entry:old_entry['after_sha256']=digest(dest.read_bytes())
    else:data['changed_direct_files'].append({'path':str(rel),'before_sha256':digest(poi_raw),'after_sha256':digest(dest.read_bytes())})
    data.pop('snapshot_sha256',None)
    out=target/'dynamic_snapshot_v2.json';out.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'snapshot':str(out),'snapshot_sha256':digest(out.read_bytes()),'record_id':record_id,'source_raw_sha256':rawhash},ensure_ascii=True))

if __name__=='__main__':main()
