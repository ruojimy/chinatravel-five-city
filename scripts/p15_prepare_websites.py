"""Index record-linked source websites from saved raw files, without another API scan."""
import collections,gzip,json,sqlite3,sys
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_crawler import BusinessCrawler
from shorttrip.freshness import utcnow,canonical
from shorttrip.travel_catalog import digest_file
RES=ROOT/'results/p15_whole_catalog';CAT=ROOT/'data/business_catalog_v1_4_20261022/catalog.sqlite3'

def main():
    src=sqlite3.connect(CAT.resolve().as_uri()+'?mode=ro',uri=True);groups=collections.defaultdict(dict)
    for payload, in src.execute('SELECT payload FROM records'):
        r=json.loads(payload);loc=r['source_locator']
        if loc.get('raw_file'):groups[loc['raw_file']][loc['raw_line']]={'entity_id':r['record_id'],'kind':r['kind'],'name':r['name'],'city':r['city']}
    links=sqlite3.connect(RES/'source_links.sqlite3')
    links.executescript('''CREATE TABLE IF NOT EXISTS links(entity_id TEXT,url TEXT,kind TEXT,city TEXT,
       role TEXT,raw_file TEXT,raw_line INTEGER,status TEXT,PRIMARY KEY(entity_id,url));
       CREATE TABLE IF NOT EXISTS source_hints(entity_id TEXT PRIMARY KEY,payload TEXT);
       CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);''')
    counts=collections.Counter();hosts=collections.Counter();existing=links.execute('SELECT count(*) FROM source_hints').fetchone()[0]
    if not existing:
      with links:
        for filename,targets in groups.items():
            with gzip.open(ROOT/filename,'rt',encoding='utf-8') as f:
              for i,line in enumerate(f,1):
                if i not in targets:continue
                t=targets[i];row=json.loads(line)
                if t['entity_id']!='overture:'+row['id']:raise ValueError('Raw pointer identity mismatch')
                hints={'schema_version':'source-identity-hints-v1','entity_id':t['entity_id'],
                  'source_id':'saved_overture_record','source_published_at':None,'source_updated_at':None,
                  'observed_at':None,'indexed_at':utcnow(),'raw_file':filename,'raw_line':i,
                  'raw_line_sha256':__import__('hashlib').sha256(line.encode()).hexdigest(),
                  'names':row.get('names'),'addresses':row.get('addresses'),'websites':row.get('websites'),
                  'role':'provider_hint_not_verified_operator_or_fact_clock','ttl_policy':'identity_90d_requires_known_fact_clock',
                  'valid_until':None,'tags':[]}
                links.execute('INSERT INTO source_hints VALUES(?,?)',(t['entity_id'],canonical(hints)))
                for url in row.get('websites') or []:
                    if not isinstance(url,str):continue
                    parsed=urlsplit(url)
                    state='pending' if parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password else 'needs_url_review'
                    if parsed.hostname and any(parsed.hostname==h or parsed.hostname.endswith('.'+h) for h in ('facebook.com','instagram.com','weibo.com','twitter.com','x.com')):state='social_link_not_operator_page'
                    links.execute('INSERT OR IGNORE INTO links VALUES(?,?,?,?,?,?,?,?)',
                      (t['entity_id'],url,t['kind'],t['city'],'record_link_not_verified_operator',filename,i,state))
        links.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('indexed_at',canonical(utcnow())))
    crawler=BusinessCrawler(RES/'web_crawler',minimum_interval=8)
    # Carry forward every known host pause and last-request clock; a new queue cannot reset them.
    for folder in (ROOT/'results/p13_business_completion/crawler',ROOT/'results/p14_targeted_completion/crawler'):
        path=folder/'queue.sqlite3'
        if not path.exists():continue
        old=sqlite3.connect(path);old.row_factory=sqlite3.Row
        with crawler.db:
            for row in old.execute('SELECT * FROM hosts'):
                current=crawler.db.execute('SELECT * FROM hosts WHERE host=?',(row['host'],)).fetchone()
                if current and current['status']=='paused':continue
                if not current or row['status']=='paused' or row['last_at']>current['last_at']:
                    crawler.db.execute('INSERT OR REPLACE INTO hosts VALUES(?,?,?,?,?,?)',tuple(row))
        old.close()
    # One provided page per URL, no recursive link traversal or endpoint discovery.
    crawler.enqueue({'url':url,'entity_id':rid,'kind':kind} for url,rid,kind in links.execute(
       "SELECT url,entity_id,kind FROM links WHERE status='pending' GROUP BY url ORDER BY kind,url"))
    report={'indexed_at':utcnow(),'hints':links.execute('SELECT count(*) FROM source_hints').fetchone()[0],
            'links':links.execute('SELECT count(*) FROM links').fetchone()[0],
            'link_states':dict(links.execute('SELECT status,count(*) FROM links GROUP BY status')),
            'linked_entities':links.execute('SELECT count(distinct entity_id) FROM links').fetchone()[0],
            'crawl_jobs':dict(crawler.db.execute('SELECT status,count(*) FROM jobs GROUP BY status')),
            'inherited_paused_hosts':[dict(x) for x in crawler.db.execute("SELECT host,status,reason FROM hosts WHERE status='paused'")],
            'network_calls':0,'linked_website_is_not_verified_official':True}
    (RES/'source_links_summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(canonical(report));crawler.close();links.close();src.close()
if __name__=='__main__':main()
