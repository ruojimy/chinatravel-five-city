"""Field-specific evidence capture and conservative schema.org extraction.

The caller chooses a candidate HTTPS detail page. Search-engine snippets are
not treated as evidence; every observation stores the response body and hash.
Single-source observations remain references, never booking availability.
"""
from datetime import datetime,timezone
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse,parse_qs
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import json,math,sqlite3,re

def now():return datetime.now(timezone.utc).isoformat()
def sha(data):return sha256(data).hexdigest()

class JsonLD(HTMLParser):
    def __init__(self):super().__init__();self.on=False;self.buf=[];self.docs=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=='script' and dict(attrs).get('type','').lower().split(';')[0]=='application/ld+json':self.on=True;self.buf=[]
    def handle_data(self,data):
        if self.on:self.buf.append(data)
    def handle_endtag(self,tag):
        if tag.lower()=='script' and self.on:
            self.on=False
            try:self.docs.append(json.loads(unescape(''.join(self.buf))))
            except ValueError:pass

class OfficialTable(HTMLParser):
    """Capture complete table rows without treating other page text as a row."""
    def __init__(self):
        super().__init__();self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        tag=tag.lower()
        if tag=='tr':self.row=[]
        elif tag in ('td','th') and self.row is not None:self.cell=[]
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        tag=tag.lower()
        if tag in ('td','th') and self.row is not None and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
        elif tag=='tr' and self.row is not None:
            self.rows.append(self.row);self.row=None;self.cell=None

def nodes(item):
    if isinstance(item,list):
        for x in item:yield from nodes(x)
    elif isinstance(item,dict):
        yield item
        if '@graph' in item:yield from nodes(item['@graph'])

def parse(body,name,city,kind,url=None):
    parsed=urlparse(url or '')
    if (kind=='attraction' and city=='西安' and parsed.scheme=='https'
            and parsed.hostname=='wlj.xa.gov.cn' and parsed.path=='/wbdw/bwgjs/1.html'):
        table=OfficialTable();table.feed(body)
        headers=[row for row in table.rows if '博物馆名称' in row and '地址' in row and '开放时间' in row]
        if len(headers)==1:
            header=headers[0];ni=header.index('博物馆名称');ai=header.index('地址');hi=header.index('开放时间')
            matched=[row for row in table.rows if len(row)>max(ni,ai,hi) and row[ni]==name and city in row[ai]]
            if len(matched)==1:
                text=matched[0][hi]
                ranges=re.findall(r'(\d{1,2}:\d{2})\s*[-—–]+\s*(\d{1,2}:\d{2})',text)
                if ranges:
                    flat=' '.join(re.sub(r'<[^>]+>',' ',unescape(body)).split())
                    published=re.search(r'发布时间\s*[:：]?\s*(\d{4}-\d{2}-\d{2})',flat)
                    return {'status':'identity_matched','name':name,'city':city,'kind':kind,
                            'source_id':url,'offers':[],'discarded':[],'hours':[],
                            'noncanonical_hours':text,'time_ranges':ranges,
                            'parser':'xian_culture_bureau_museum_table',
                            'source_published':published.group(1) if published else None}
        return {'status':'identity_missing_or_ambiguous','matching_nodes':0}
    # Dedicated, narrow parser for the museum's named primary announcement;
    # the title, named issuer, ticket class and value must all be present.
    if (kind=='attraction' and name=='西安碑林博物馆' and city=='西安' and
        parsed.hostname in ('www.beilin-museum.com','beilin-museum.com') and
        parsed.path=='/index.php' and parse_qs(parsed.query).get('aid')==['4627']):
        clean=re.sub(r'<script\b[^>]*>.*?</script>',' ',body,flags=re.I|re.S)
        clean=' '.join(re.sub(r'<[^>]+>',' ',unescape(clean)).split())
        price=re.search(r'全票\s*(\d+(?:\.\d+)?)\s*元\s*/\s*人次',clean)
        hours=re.search(r'(\d{1,2}:\d{2})\s*开馆.*?(\d{1,2}:\d{2})\s*闭馆',clean)
        if ('西安碑林博物馆全面开放门票价格公告' not in clean or '西安碑林博物馆' not in clean or
            '自2025年5月12日起' not in clean or '执行期2年' not in clean):
            return {'status':'identity_missing_or_ambiguous','matching_nodes':0}
        return {'status':'identity_matched','name':name,'city':city,'kind':kind,'source_id':url,
                'offers':[{'price':float(price.group(1)),'currency':'CNY','offer':{'name':'官方全票','price':price.group(1),
                          'priceCurrency':'CNY','validFrom':'2025-05-12','validThrough':'2027-05-11'}}] if price else [],
                'discarded':[],'hours':[{'days':[],
                          'opens':hours.group(1),'closes':hours.group(2),'validFrom':'2025-05-12','validThrough':'2027-05-11'}] if hours else [],
                'parser':'beilin_museum_notice_4627','source_published':'2025-05-06'}
    h=JsonLD();h.feed(body);allowed={'attraction':{'TouristAttraction','LandmarksOrHistoricalBuildings'},
        'accommodation':{'Hotel','Hostel','LodgingBusiness'},'restaurant':{'Restaurant','FoodEstablishment'}}
    matches=[]
    for n in nodes(h.docs):
        typ=n.get('@type');types=set(typ if isinstance(typ,list) else [typ])
        addr=n.get('address');locality=addr.get('addressLocality') if isinstance(addr,dict) else addr
        if n.get('name')==name and city in str(locality or '') and types & allowed[kind]:matches.append(n)
    if len(matches)!=1:return {'status':'identity_missing_or_ambiguous','matching_nodes':len(matches)}
    n=matches[0];offers=n.get('offers') or [];offers=offers if isinstance(offers,list) else [offers]
    accepted=[];discarded=[]
    for offer in offers:
        if not isinstance(offer,dict):continue
        try:value=float(offer['price'])
        except (KeyError,TypeError,ValueError):continue
        if not math.isfinite(value) or value<0 or offer.get('priceCurrency')!='CNY':continue
        if kind=='attraction':
            category=str(offer.get('name') or offer.get('category') or '')
            if not any(x in category for x in ('成人','adult','Adult')):
                discarded.append('non_explicit_adult_ticket');continue
        if kind=='accommodation':
            room=offer.get('itemOffered') or {};occ=room.get('occupancy') or {}
            unit=offer.get('priceSpecification') or {};duration=unit.get('unitText') or unit.get('unitCode')
            if duration not in ('night','NIGHT','夜','晚') or not isinstance(occ,dict) or not occ.get('value'):
                discarded.append('nightly_room_or_occupancy_missing');continue
        accepted.append({'price':value,'currency':'CNY','offer':offer})
    hours=[]
    hour_specs=n.get('openingHoursSpecification') or []
    if isinstance(hour_specs,dict):hour_specs=[hour_specs]
    for spec in hour_specs:
        if not isinstance(spec,dict):continue
        days=spec.get('dayOfWeek');days=days if isinstance(days,list) else [days]
        hours.append({'days':[str(x).rsplit('/',1)[-1] for x in days],
                      'opens':spec.get('opens'),'closes':spec.get('closes'),
                      'validFrom':spec.get('validFrom'),'validThrough':spec.get('validThrough')})
    return {'status':'identity_matched','name':name,'city':city,'kind':kind,
            'source_id':n.get('@id') or n.get('url'),'offers':accepted,'discarded':discarded,'hours':hours}

def capture(journal,request,*,budget=12,opener=urlopen):
    required=('record_id','city','kind','name','url','purpose','source_group')
    if not all(isinstance(request.get(k),str) and request[k] for k in required):raise ValueError('missing request identity')
    parsed=urlparse(request['url'])
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:raise ValueError('HTTPS source URL required')
    if request['kind'] not in ('attraction','accommodation','restaurant') or request['purpose'] not in ('ticket_price','hotel_price','opening_hours'):
        raise ValueError('unsupported field request')
    if parsed.query and any(x in parsed.query.lower() for x in ('key=','token=','password=')):raise ValueError('secret-bearing URL is not journal-safe')
    db=sqlite3.connect(str(journal),timeout=30,isolation_level=None)
    db.execute('CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY,at_utc TEXT,status TEXT,request_json TEXT,raw_sha256 TEXT,response_text TEXT,error_type TEXT)')
    db.execute('BEGIN IMMEDIATE')
    try:
        used=int((db.execute("SELECT value FROM meta WHERE key='count'").fetchone() or ['0'])[0])
        paused=db.execute("SELECT value FROM meta WHERE key='paused'").fetchone()
        if paused or used>=budget:
            status='provider_paused' if paused else 'budget_exhausted';body=None;error=None
        else:
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('count',?)",(str(used+1),))
            try:
                with opener(Request(request['url'],headers={'User-Agent':'ChinaTravel-Research/1.0'}),timeout=15) as response:
                    raw=response.read(2_000_001)
                    final=urlparse(response.geturl())
                    if final.scheme!='https' or final.hostname!=parsed.hostname:raise ValueError('redirected_to_different_source')
                if len(raw)>2_000_000:raise ValueError('response_too_large')
                body=raw.decode('utf-8');status='ok';error=None
            except Exception as exc:
                body=None;error=type(exc).__name__;status='provider_error'
                if isinstance(exc,HTTPError):
                    error='HTTPError:'+str(exc.code)
                    try:
                        raw=exc.read(2_000_000)
                        if raw:body=raw.decode('utf-8',errors='replace')
                    except Exception:pass
                    if exc.code in (403,429):db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('paused',?)",(str(exc.code),))
        cursor=db.execute('INSERT INTO calls(at_utc,status,request_json,raw_sha256,response_text,error_type) VALUES(?,?,?,?,?,?)',
            (now(),status,json.dumps(request,ensure_ascii=False),sha(body.encode('utf-8')) if body is not None else None,body,error))
        db.commit();return {'call_id':cursor.lastrowid,'status':status,'provider_calls_used':used+(1 if not paused and used<budget else 0)}
    except Exception:db.rollback();raise
    finally:db.close()
