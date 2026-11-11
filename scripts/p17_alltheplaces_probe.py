"""Inspect existing upstream IDs and one documented public dataset endpoint."""
import collections,gzip,hashlib,json,sqlite3,sys,time
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_crawler import BusinessCrawler,UA
from shorttrip.freshness import utcnow
from protego import Protego
OUT=ROOT/'results/p17_continuous/open_datasets/alltheplaces_001'

def main():
 OUT.mkdir(exist_ok=False);pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text());db=sqlite3.connect(ROOT/pointer['catalog'])
 wanted={}
 for payload, in db.execute('SELECT payload FROM records'):
  r=json.loads(payload);loc=r.get('source_locator',{})
  if any(z.get('dataset')=='AllThePlaces' for z in loc.get('providers',[])):
   wanted[r['record_id']]={'name':r['name'],'city':r['city'],'kind':r['kind'],'source_locator':loc,'data':{k:r['data'].get(k) for k in ('lat','lon')}}
 db.close();counts=collections.Counter();rows=[]
 for file in sorted((ROOT/'data/expansion_v1_20261022/raw').glob('*.jsonl.gz')):
  with gzip.open(file,'rb') as f:
   for ordinal,raw in enumerate(f,1):
    row=json.loads(raw);rid='overture:'+row['id'];r=wanted.get(rid)
    if r is None or Path(r['source_locator']['raw_file'])!=file.relative_to(ROOT):continue
    content=raw.rstrip(b'\r\n')
    if hashlib.sha256(content).hexdigest()!=r['source_locator']['raw_sha256']:raise ValueError('Raw changed')
    host=urlsplit((row.get('websites') or [''])[0]).hostname;counts[(r['kind'],host)]+=1
    rows.append({'entity_id':rid,**r,'website':row.get('websites'),'upstream_ids':[s['record_id'] for s in row.get('sources',[]) if s.get('dataset')=='AllThePlaces']})
 (OUT/'existing_upstream_entities.json').write_text(json.dumps({'at':utcnow(),'entities':rows,'host_counts':[{'kind':k[0],'host':k[1],'count':v} for k,v in counts.most_common()]},ensure_ascii=False,indent=2),encoding='utf-8')
 c=BusinessCrawler(ROOT/'results/p15_whole_catalog/web_crawler',max_bytes=2*1024*1024,minimum_interval=8)
 url='https://data.alltheplaces.xyz/runs/latest.json';host=c._host(url);result={'at':utcnow(),'url':url,'requests':c.requests_made,'source_status':host['status'],'robots_reason':host['reason']}
 if host['status']=='ready' and Protego.parse(host['robots']).can_fetch(url,UA):
  time.sleep(max(0,host['last_at']+host['delay']-time.time()))
  try:
   response,content=c._get(url);status=response.status_code;result.update(http_status=status,headers={'content_type':response.headers.get('Content-Type'),'location':response.headers.get('Location')},bytes=len(content))
   (OUT/'latest_response.bin').write_bytes(content);result['sha256']=hashlib.sha256(content).hexdigest()
   if status in (401,403,429):
    with c.db:c.db.execute("UPDATE hosts SET status='paused',reason=? WHERE host=?",('HTTP_'+str(status),host['host']))
   if status==200:
    try:result['metadata']=json.loads(content)
    except ValueError:result['not_json']=True
   with c.db:c.db.execute('UPDATE hosts SET last_at=? WHERE host=?',(time.time(),host['host']))
  except Exception as exc:
   result['error_type']=type(exc).__name__
   with c.db:c.db.execute("UPDATE hosts SET status='paused',reason=? WHERE host=?",(type(exc).__name__,host['host']))
 else:result['no_request_to_blocked_or_disallowed_source']=True
 result['requests']=c.requests_made;c.close();(OUT/'metadata_probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'entities_with_original_upstream_ids':len(rows),'host_counts':[{'kind':k[0],'host':k[1],'count':v} for k,v in counts.most_common(14)],'metadata_probe':result},ensure_ascii=False))
if __name__=='__main__':main()
