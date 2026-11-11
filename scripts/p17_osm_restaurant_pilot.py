"""One-off small native OSM POI pilot; never alternate instances or retry."""
import collections,gzip,hashlib,json,math,sqlite3,sys,time
from pathlib import Path
from urllib.parse import urlencode
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_crawler import BusinessCrawler,UA
from shorttrip.business_archives import normalize_name as norm
from shorttrip.source_identity import language_aliases
from protego import Protego
OUT=ROOT/'results/p17_continuous/restaurants';HOST='https://overpass-api.de'
def now():return datetime.now(timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def main(label):
 folder=OUT/label;folder.mkdir(exist_ok=False);p=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'));db=sqlite3.connect(ROOT/p['catalog']);records=[]
 for payload, in db.execute("SELECT payload FROM records WHERE kind='restaurant'"):
  r=json.loads(payload)
  if r.get('coordinate_system')=='WGS84':records.append(r)
 # A tiny pilot on three existing-city central restaurant clusters only.
 plans=[]
 for city in ['西安','厦门','大连']:
  subset=[r for r in records if r['city']==city]
  if not subset:continue
  lon=sorted(r['data']['lon'] for r in subset)[len(subset)//2];lat=sorted(r['data']['lat'] for r in subset)[len(subset)//2]
  box=(round(lat-.08,6),round(lon-.08,6),round(lat+.08,6),round(lon+.08,6))
  q='[out:json][timeout:15][maxsize:16777216];nwr["amenity"~"^(restaurant|cafe|fast_food)$"][~"^(opening_hours|cuisine)$"~"."]('+','.join(map(str,box))+');out meta center;'
  plans.append({'city_window':city,'bbox_WGS84_S_W_N_E':box,'query':q,'url':HOST+'/api/interpreter?'+urlencode({'data':q})})
 (folder/'plans.json').write_text(json.dumps({'created_at':now(),'plans':plans,'policy_urls':['https://dev.overpass-api.de/overpass-doc/en/preface/commons.html','https://wiki.openstreetmap.org/wiki/Overpass_API'],'max_queries':3,'max_response_bytes':4194304,'same_instance_only':True,'no_retry':True,'community_data_not_official_operator':True},ensure_ascii=False,indent=2),encoding='utf-8')
 c=BusinessCrawler(folder/'crawler',minimum_interval=6);shared=sqlite3.connect(ROOT/'results/p15_whole_catalog/web_crawler/queue.sqlite3',timeout=30);state=shared.execute('SELECT status,reason FROM hosts WHERE host=?',(HOST,)).fetchone();shared.close();events=[]
 if state and state[0]=='paused':events.append({'status':'inherited_shared_pause','reason':state[1]})
 else:
  h=c._host(HOST+'/api/interpreter')
  for i,plan in enumerate(plans,1):
   h=dict(c.db.execute('SELECT * FROM hosts WHERE host=?',(HOST,)).fetchone())
   if h['status']!='ready':events.append({'status':'source_paused','reason':h['reason']});break
   if not Protego.parse(h['robots']).can_fetch(plan['url'],UA):events.append({'status':'robots_disallowed','url':plan['url']});break
   delay=max(0,h['last_at']+h['delay']-time.time())
   if delay:time.sleep(delay)
   try:
    response,body=c._get(plan['url']);event={'city_window':plan['city_window'],'query':plan['query'],'url':plan['url'],'http_status':response.status_code,'content_type':response.headers.get('Content-Type'),'retrieved_at':now(),'bytes':len(body),'sha256':sha(body),'content_file':f'response_{i:02}.json'};(folder/event['content_file']).write_bytes(body)
    with c.db:c.db.execute('UPDATE hosts SET last_at=? WHERE host=?',(time.time(),HOST))
    if response.status_code!=200:
     event['status']='http_failure'
     if response.status_code in (401,403,429):
      with c.db:c.db.execute("UPDATE hosts SET status='paused',reason=? WHERE host=?",('HTTP_'+str(response.status_code),HOST))
     events.append(event);break
    obj=json.loads(body)
    if obj.get('remark'):event['status']='provider_query_remark_stop';event['remark']=obj['remark'];events.append(event);break
    event['status']='captured_native_osm_json';event['elements']=len(obj.get('elements',[]));event['osm_database_snapshot_time']=obj.get('osm3s',{}).get('timestamp_osm_base');events.append(event)
   except Exception as exc:
    events.append({'status':'source_error_stop','error_type':type(exc).__name__,'at':now(),'url':plan['url']})
    with c.db:c.db.execute("UPDATE hosts SET status='paused',reason=? WHERE host=?",(type(exc).__name__,HOST))
    break
 # Persist the source state without resetting any existing shared pause.
 shared=sqlite3.connect(ROOT/'results/p15_whole_catalog/web_crawler/queue.sqlite3',timeout=30)
 for row in c.db.execute('SELECT host,status,last_at,delay,robots,reason FROM hosts'):
  old=shared.execute('SELECT status FROM hosts WHERE host=?',(row[0],)).fetchone()
  with shared:
   if not old:shared.execute('INSERT INTO hosts VALUES(?,?,?,?,?,?)',tuple(row))
   elif old[0]!='paused' and row[1]=='paused':shared.execute("UPDATE hosts SET status='paused',reason=? WHERE host=?",(row[5],row[0]))
 shared.close();report={'created_at':now(),'events':events,'requests_this_run_including_robots':c.requests_made,'formal_database_modified':False,'full_completion':False};(folder/'capture_manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');c.close();print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main(sys.argv[1])
