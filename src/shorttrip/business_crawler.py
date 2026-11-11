"""Small resumable public-page crawler. No cookies, proxies or challenge bypass."""
from __future__ import annotations
import gzip,hashlib,json,re,sqlite3,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit,urljoin
import requests
from bs4 import BeautifulSoup
from protego import Protego

UA='ShortTripResearchBot/1.0 (public travel-data field verification)'

class LocalCrawlBudget(RuntimeError):
    """A local request/time/stop budget, never a provider access failure."""
class LocalResponseLimit(RuntimeError):
    """A response exceeded our own memory cap; no publisher restriction inferred."""
    def __init__(self,limit,seen,status):
        super().__init__('response_size_cap');self.limit=limit;self.seen=seen;self.http_status=status
def stamp():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def page_fields(html):
    soup=BeautifulSoup(html,'html.parser');items=[]
    for script in soup.find_all('script',type='application/ld+json'):
        try:value=json.loads(script.string or script.get_text())
        except (ValueError,TypeError):continue
        def walk(value,path='$'):
            if isinstance(value,list):
                for i,v in enumerate(value):walk(v,f'{path}[{i}]')
            elif isinstance(value,dict):
                typ=value.get('@type')
                if typ:items.append({'path':path,'type':typ,'data':value})
                for k,v in value.items():
                    if isinstance(v,(list,dict)):walk(v,path+'.'+k)
        walk(value)
    for node in soup(['script','style','noscript']):node.decompose()
    text=soup.get_text(' ',strip=True)
    title=soup.title.get_text(' ',strip=True) if soup.title else ''
    heading=[x.get_text(' ',strip=True) for x in soup.find_all('h1')]
    challenge=bool(re.search(r'滑动验证|请完成安全验证|访问过于频繁|访问异常|请拖动滑块|人机验证|verify you are human|access denied|unusual traffic',text,re.I))
    observations=[]
    for label,pattern in [('money',r'(?:¥|￥|CNY\s*)\s*\d+(?:\.\d{1,2})?'),
              ('bed_text',r'.{0,15}(?:双床房|两张单人床|2张单人床|大床房).{0,25}'),
              ('hours_text',r'.{0,15}\b\d{1,2}:\d{2}\s*[-—至]\s*\d{1,2}:\d{2}.{0,20}')]:
        observations.extend({'kind':label,'quote':m.group(0),'status':'unbound_observation_not_fact'} for m in list(re.finditer(pattern,text))[:20])
    return {'title':title,'headings':heading,'text_chars':len(text),'challenge':challenge,
        'jsonld':items,'unbound_observations':observations,'visible_text':text,
        'projection_note':'A currency token is not a date-bound same-room total. Bed text and prices must share an explicitly verified room offer before native projection.'}

class BusinessCrawler:
    def __init__(self,directory,*,max_bytes=4*1024*1024,minimum_interval=5,transport=None,
                 partition_index=0,partition_count=1,request_gate=None):
        if type(partition_count) is not int or not 1<=partition_count<=8 or type(partition_index) is not int or not 0<=partition_index<partition_count:
            raise ValueError('Invalid fixed host partition')
        self.root=Path(directory);self.root.mkdir(parents=True,exist_ok=True)
        (self.root/'private_pages').mkdir(exist_ok=True)
        self.db=sqlite3.connect(self.root/'queue.sqlite3',timeout=30);self.db.row_factory=sqlite3.Row
        self.db.executescript('''CREATE TABLE IF NOT EXISTS jobs(url TEXT PRIMARY KEY,kind TEXT,entity_id TEXT,
          status TEXT DEFAULT 'pending',attempts INTEGER DEFAULT 0,result TEXT);
          CREATE TABLE IF NOT EXISTS hosts(host TEXT PRIMARY KEY,status TEXT,last_at REAL,delay REAL,robots TEXT,reason TEXT);''')
        self.max_bytes=max_bytes;self.minimum_interval=minimum_interval
        self.transport=transport or requests.get;self.requests_made=0
        self.partition_index=partition_index;self.partition_count=partition_count;self.request_gate=request_gate
    def owns_url(self,url):
        # All URLs of one hostname always have one owner, including robots.txt.
        host=urlsplit(url).hostname or ''
        return int(hashlib.sha256(host.encode()).hexdigest(),16)%self.partition_count==self.partition_index
    def enqueue(self,rows):
        with self.db:
            for row in rows:
                parsed=urlsplit(row['url'])
                if parsed.scheme!='https' or not parsed.hostname:raise ValueError('HTTPS public URL required')
                if parsed.username or parsed.password:raise ValueError('No credentials in URL')
                if any(s in parsed.path.lower() for s in ('/order/','/payment/','/checkout/','/booking/submit')):
                    raise ValueError('Read-only page crawler excludes transactional endpoints')
                self.db.execute('INSERT OR IGNORE INTO jobs(url,kind,entity_id) VALUES(?,?,?)',
                   (row['url'],row.get('kind'),row.get('entity_id')))
    def seed_robots(self,host,text,*,retrieved_at=None):
        if not re.search(r'(?im)^\s*user-agent\s*:',text):raise ValueError('Not a robots response')
        rules=Protego.parse(text);delay=max(self.minimum_interval,rules.crawl_delay(UA) or 0)
        at=datetime.fromisoformat(retrieved_at).timestamp() if retrieved_at else 0
        with self.db:self.db.execute('INSERT OR IGNORE INTO hosts VALUES(?,?,?,?,?,?)',
             (host,'ready',at,delay,text,'cached_robots'))
    def _get(self,url):
        if self.request_gate is not None and not self.request_gate(url):
            raise LocalCrawlBudget('local_request_time_or_stop_budget')
        self.requests_made+=1
        response=self.transport(url,headers={'User-Agent':UA},timeout=20,stream=True,allow_redirects=False)
        chunks=[];size=0
        for chunk in response.iter_content(65536):
            size+=len(chunk)
            if size>self.max_bytes:
                close=getattr(response,'close',None)
                if callable(close):close()
                raise LocalResponseLimit(self.max_bytes,size,response.status_code)
            chunks.append(chunk)
        return response,b''.join(chunks)
    def _host(self,url):
        parts=urlsplit(url);host=parts.scheme+'://'+parts.netloc
        row=self.db.execute('SELECT * FROM hosts WHERE host=?',(host,)).fetchone()
        if row:return dict(row)
        try:
            response,content=self._get(host+'/robots.txt')
            text=content.decode('utf-8','replace')
            if response.status_code==404:
                state={'host':host,'status':'ready','last_at':time.time(),'delay':self.minimum_interval,
                    'robots':'User-agent: *\nAllow: /\n','reason':'robots_missing_404_no_exclusion_rules'}
            elif response.status_code!=200 or not re.search(r'(?im)^\s*user-agent\s*:',text):
                state={'host':host,'status':'paused','last_at':time.time(),'delay':self.minimum_interval,
                    'robots':'','reason':'robots_unavailable_or_nontext:'+str(response.status_code)}
            else:
                rules=Protego.parse(text)
                state={'host':host,'status':'ready','last_at':time.time(),
                    'delay':max(self.minimum_interval,rules.crawl_delay(UA) or 0),'robots':text,'reason':''}
        except LocalCrawlBudget:raise
        except Exception as exc:
            state={'host':host,'status':'paused','last_at':time.time(),'delay':self.minimum_interval,'robots':'','reason':type(exc).__name__}
        with self.db:self.db.execute('INSERT INTO hosts VALUES(:host,:status,:last_at,:delay,:robots,:reason)',state)
        return state
    def run(self,*,max_requests=6,max_seconds=45):
        started=time.monotonic();events=[]
        for row in self.db.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY rowid").fetchall():
            if not self.owns_url(row['url']):continue
            if self.requests_made>=max_requests or time.monotonic()-started>=max_seconds:break
            host=self._host(row['url'])
            if host['status']!='ready':
                event={'url':row['url'],'status':'source_paused','reason':host['reason']}
            elif not Protego.parse(host['robots']).can_fetch(row['url'],UA):
                event={'url':row['url'],'status':'robots_disallowed'}
            elif time.time()-host['last_at']<host['delay']:
                events.append({'url':row['url'],'status':'deferred_rate_limit',
                    'retry_not_before_epoch':host['last_at']+host['delay']});continue
            elif self.requests_made>=max_requests:break
            else:
                try:
                    response,content=self._get(row['url']);status=response.status_code
                    event={'url':row['url'],'http_status':status,'retrieved_at':stamp(),'bytes':len(content)}
                    if status in (401,403,429):
                        event['status']='source_paused';event['reason']='HTTP_'+str(status)
                        with self.db:self.db.execute("UPDATE hosts SET status='paused',reason=? WHERE host=?",(event['reason'],host['host']))
                    elif 300<=status<400:
                        event['status']='redirect_needs_review';event['location']=urljoin(row['url'],response.headers.get('Location',''))
                    elif status!=200:event['status']='unavailable'
                    elif 'html' not in response.headers.get('Content-Type','').lower():event['status']='not_html'
                    else:
                        encoding=response.encoding if response.encoding and response.encoding.lower()!='iso-8859-1' else 'utf-8'
                        parsed=page_fields(content.decode(encoding,'replace'))
                        if parsed['challenge']:
                            event['status']='source_paused';event['reason']='visible_access_challenge'
                            with self.db:self.db.execute("UPDATE hosts SET status='paused',reason=? WHERE host=?",(event['reason'],host['host']))
                        else:
                            event['status']='captured';event['sha256']=hashlib.sha256(content).hexdigest()
                            name=hashlib.sha256(row['url'].encode()).hexdigest()[:20]
                            raw=self.root/'private_pages'/(name+'.html.gz')
                            with gzip.open(raw,'wb') as f:f.write(content)
                            parsed_path=self.root/(name+'.extraction.json')
                            parsed_path.write_text(json.dumps({'capture':event,'extraction':parsed},ensure_ascii=False,indent=2),encoding='utf-8')
                            event.update(raw_file=str(raw),extraction_file=str(parsed_path),
                                jsonld_objects=len(parsed['jsonld']),observations=len(parsed['unbound_observations']))
                    with self.db:self.db.execute('UPDATE hosts SET last_at=? WHERE host=?',(time.time(),host['host']))
                except LocalCrawlBudget:raise
                except LocalResponseLimit as exc:
                    event={'url':row['url'],'status':'local_resource_limit','reason':'response_size_cap',
                        'max_bytes':exc.limit,'bytes_seen':exc.seen,'http_status':exc.http_status,'retrieved_at':stamp()}
                    with self.db:self.db.execute('UPDATE hosts SET last_at=? WHERE host=?',(time.time(),host['host']))
                except Exception as exc:
                    event={'url':row['url'],'status':'error','error_type':type(exc).__name__}
                    with self.db:self.db.execute("UPDATE hosts SET status='paused',reason=? WHERE host=?",(event['error_type'],host['host']))
            with self.db:self.db.execute('UPDATE jobs SET status=?,attempts=attempts+1,result=? WHERE url=?',
                 (event['status'],json.dumps(event,ensure_ascii=False),row['url']))
            events.append(event)
        return {'executed_at':stamp(),'requests_this_run':self.requests_made,'events':events,
            'job_counts':dict(self.db.execute('SELECT status,count(*) FROM jobs GROUP BY status').fetchall()),
            'single_process':True,'no_credentials_or_proxy':True,'max_requests':max_requests,'max_seconds':max_seconds,
            'host_partition':{'index':self.partition_index,'count':self.partition_count}}
    def close(self):self.db.close()
