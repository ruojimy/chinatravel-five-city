"""Recover observed directory links omitted by city-window mismatch; no new IDs."""
import gzip,hashlib,json,re,sqlite3,sys,time,collections,os
from pathlib import Path
from urllib.parse import urljoin,urlsplit,unquote
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_crawler import BusinessCrawler
from shorttrip.business_archives import normalize_name as norm
from shorttrip.source_identity import language_aliases
from opencc import OpenCC
CC=OpenCC('t2s')
OUT=ROOT/'results/p17_continuous/restaurants';CITIES={'Guangzhou':'广州','GuangZhou':'广州','广州':'广州','广州市':'广州','廣州':'广州','Guangzhou Shi':'广州','Suzhou':'苏州','suzhou':'苏州','Suchou':'苏州','苏州':'苏州','苏州市':'苏州'}
def key(s):return norm(CC.convert(s))
def main():
 c=BusinessCrawler(OUT/'crawler',minimum_interval=6);p=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'));db=sqlite3.connect(ROOT/p['catalog']);rs={};wanted=collections.defaultdict(dict);lookup=collections.defaultdict(set)
 for payload, in db.execute("SELECT payload FROM records WHERE kind='restaurant'"):
  r=json.loads(payload);loc=r.get('source_locator',{});hints=loc.get('city_assertions',[]);city=next((CITIES[x] for x in hints if x in CITIES),None)
  # Empty locality can be explored inside an existing research window only;
  # this never verifies the actual city or a branch by itself.
  if not hints:city={'佛山':'广州','无锡':'苏州'}.get(r['city'])
  if not city or not loc.get('raw_file'):continue
  rs[r['record_id']]=(r,city);wanted[loc['raw_file']][loc['raw_line']]=r['record_id']
 for filename,rows in wanted.items():
  with gzip.open(ROOT/filename,'rb') as f:
   for n,line in enumerate(f,1):
    rid=rows.get(n)
    if rid is None:continue
    r,city=rs[rid];raw=line.rstrip(b'\r\n')
    if hashlib.sha256(raw).hexdigest()!=r['source_locator']['raw_sha256']:raise ValueError('Raw mismatch')
    for alias in language_aliases(json.loads(raw)).values():lookup[(city,key(alias['value']))].add(rid)
 ix=sqlite3.connect(OUT/'feinfood_provider_entities.sqlite3');ix.execute('CREATE TABLE IF NOT EXISTS listings(entity_id TEXT,source_city TEXT,source_name TEXT,detail_url TEXT,parent_url TEXT,parent_sha256 TEXT,PRIMARY KEY(entity_id,detail_url))');done=set();all_links=[]
 def parse():
  seeds=[]
  for url,res in c.db.execute("SELECT url,result FROM jobs WHERE status='captured'").fetchall():
   if url in done:continue
   done.add(url);ev=json.loads(res);raw=gzip.open(ev['raw_file'],'rb').read()
   if hashlib.sha256(raw).hexdigest()!=ev['sha256']:raise ValueError('Capture changed')
   soup=BeautifulSoup(raw,'html.parser');parts=unquote(urlsplit(url).path).split('/');city=parts[3].removesuffix('.xhtml') if len(parts)>3 else None
   if city in CITIES.values():
    for h in soup.find_all('h2'):
     a=h.find_parent('a',href=True);li=h.find_parent('li')
     if not a or not li or '/restaurant/' not in a['href']:continue
     names=[h.get_text(' ',strip=True),''.join(str(x) for x in h.contents if isinstance(x,str)).strip()]
     if h.b:names.append(h.b.get_text(strip=True).strip('()（）'))
     ids=set(rid for name in names for rid in lookup.get((city,key(name)),set()))
     # Brand containment is a discovery lead only. Never emit business fields
     # until the retained original address or full international phone binds.
     for (look_city,look_name),look_ids in lookup.items():
      if look_city!=city or len(re.findall(r'[\u4e00-\u9fff]',look_name))<3:continue
      if any(look_name in key(name) or (len(re.findall(r'[\u4e00-\u9fff]',key(name)))>=3 and key(name) in look_name) for name in names if key(name)):ids.update(look_ids)
     if not ids or len(ids)>8:continue
     dest=urljoin(url,a['href'])
     if urlsplit(dest).hostname!='www.feinfood.com' or urlsplit(dest).scheme!='https':continue
     for rid in ids:
      with ix:ix.execute('INSERT OR IGNORE INTO listings VALUES(?,?,?,?,?,?)',(rid,city,h.get_text(' ',strip=True),dest,url,ev['sha256']))
      all_links.append({'url':dest,'parent_url':url,'parent_sha256':ev['sha256'],'entity_id':rid,'role':'source_name_containment_or_t2s_alias_and_actual_city_or_empty_locality_window_discovery_only_branch_unverified'})
     seeds.append({'url':dest,'kind':'restaurant'})
   for a in soup.find_all('a',href=True):
    dest=urljoin(url,a['href']);pp=urlsplit(dest);path=unquote(pp.path)
    if pp.hostname!='www.feinfood.com' or pp.scheme!='https' or not path.startswith('/restaurants/中国/'):continue
    target=path.removeprefix('/restaurants/中国/').removesuffix('.xhtml')
    if target in CITIES.values() and (not pp.query or a.get_text(strip=True).startswith('下一页')):
     seeds.append({'url':dest,'kind':'restaurant'});all_links.append({'url':dest,'parent_url':url,'parent_sha256':ev['sha256'],'text':a.get_text(' ',strip=True),'role':'observed_provider_actual_city_directory_not_catalogue_city_assignment'})
  c.enqueue(seeds)
 parse();started=time.monotonic();events=[]
 while time.monotonic()-started<600 and c.requests_made<40 and c.db.execute("SELECT 1 FROM jobs WHERE status='pending'").fetchone():
  shared=sqlite3.connect(ROOT/'results/p15_whole_catalog/web_crawler/queue.sqlite3',timeout=30);state=shared.execute("SELECT status,reason FROM hosts WHERE host='https://www.feinfood.com'").fetchone();shared.close()
  if state and state[0]=='paused':break
  ev=c.run(max_requests=40,max_seconds=12);events.append(ev);parse();(OUT/'feinfood_provider_progress.json').write_text(json.dumps({'at':ev['executed_at'],'pid':os.getpid(),'requests_this_run':c.requests_made,'states':ev['job_counts'],'matched_name_candidates':ix.execute('SELECT COUNT(*) FROM listings').fetchone()[0]},ensure_ascii=False,indent=2),encoding='utf-8')
  pauses=c.db.execute("SELECT host,status,last_at,delay,robots,reason FROM hosts WHERE status='paused'").fetchall()
  if pauses:
   shared=sqlite3.connect(ROOT/'results/p15_whole_catalog/web_crawler/queue.sqlite3',timeout=30)
   for row in pauses:
    old=shared.execute('SELECT status FROM hosts WHERE host=?',(row[0],)).fetchone()
    with shared:
     if not old:shared.execute('INSERT INTO hosts VALUES(?,?,?,?,?,?)',tuple(row))
     elif old[0]!='paused':shared.execute("UPDATE hosts SET status='paused',reason=? WHERE host=?",(row[5],row[0]))
   shared.close();break
  time.sleep(2)
 label=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime());(OUT/('feinfood_provider_run_'+label+'.json')).write_text(json.dumps({'requests':c.requests_made,'events':events,'observed_links':all_links,'candidate_entities':len(rs),'formal_database_modified':False},ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'requests':c.requests_made,'candidate_entities':len(rs),'name_candidate_pairs':ix.execute('SELECT COUNT(*) FROM listings').fetchone()[0]}));ix.close();c.close()
if __name__=='__main__':main()
