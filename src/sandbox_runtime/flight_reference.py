"""Date-scoped, re-extracted third-party flight references; never booking evidence."""
from pathlib import Path
from html.parser import HTMLParser
from datetime import datetime,timedelta
from urllib.parse import parse_qs,urlsplit
import hashlib,json,re
CITIES={'西安':('SIA',{'XIY'}),'厦门':('XMN',{'XMN'}),'北京':('BJS',{'PEK','PKX'}),
        '上海':('SHA',{'SHA','PVG'}),'南京':('NKG',{'NKG'}),'杭州':('HGH',{'HGH'}),
        '深圳':('SZX',{'SZX'}),'成都':('CTU',{'CTU','TFU'}),'武汉':('WUH',{'WUH'}),
        '广州':('CAN',{'CAN'}),'重庆':('CKG',{'CKG'})}
VOID={'meta','link','img','input','br','hr','area','source','wbr'}
class Cards(HTMLParser):
 def __init__(self):super().__init__();self.stack=[];self.current=None;self.cabin=None;self.cards=[]
 def handle_starttag(self,tag,attrs):
  attrs=dict(attrs); classes=set(attrs.get('class','').split())
  if self.current is None and tag=='a' and 'flight-card' in classes:
   self.current={'href':attrs.get('href'),'fields':{},'cabins':[]};self.stack=[]
  if self.current is None:return
  if tag not in VOID:self.stack.append((tag,classes))
  if 'cabin-row' in classes:self.cabin={'name':[],'price':[]}
 def handle_data(self,data):
  if self.current is None or not self.stack:return
  value=data.strip()
  if not value:return
  classes=self.stack[-1][1]
  for key in ('time','airport','airline-tag','duration','aircraft','tag'):
   if key in classes:self.current['fields'].setdefault(key,[]).append(value)
  if self.cabin is not None:
   if 'cabin-name' in classes:self.cabin['name'].append(value)
   if 'price' in classes:self.cabin['price'].append(value)
 def handle_endtag(self,tag):
  if self.current is None:return
  if not self.stack:return
  i=next((i for i in range(len(self.stack)-1,-1,-1) if self.stack[i][0]==tag),None)
  if i is None:return
  popped=self.stack[i:];self.stack=self.stack[:i]
  if self.cabin is not None and any('cabin-row' in cl for _,cl in popped):
   self.current['cabins'].append(self.cabin);self.cabin=None
  if tag=='a':self.cards.append(self.current);self.current=None;self.stack=[]

def parse_card(c,origin,dest,observed,source_hash,url):
 f=c['fields']; q=parse_qs(urlsplit(c.get('href') or '').query)
 def one(k):return q.get(k,[None])[0]
 flight=one('fn');times=f.get('time',[]);airport=f.get('airport',[]);dur=f.get('duration',[])
 reasons=[]
 if one('dcn')!=origin or one('acn')!=dest:reasons.append('city_mismatch')
 if one('dd')!='2026-11-16':reasons.append('date_mismatch')
 if one('dac') not in CITIES[origin][1] or one('aac') not in CITIES[dest][1]:reasons.append('airport_mismatch')
 if not flight or not re.fullmatch(r'[A-Z0-9]{2}\d{2,4}',flight):reasons.append('flight_id_invalid')
 if not any(re.search(r'\b'+re.escape(flight)+r'\b',x) for x in f.get('airline-tag',[])):reasons.append('flight_label_mismatch')
 if len(times)!=2 or len(airport)!=2 or len(dur)!=1:reasons.append('card_structure_invalid')
 offers=[]
 for cabin in c['cabins']:
  if len(cabin['name'])!=1 or len(cabin['price'])!=1 or not re.fullmatch(r'¥\d+(?:\.\d{1,2})?',cabin['price'][0]):
   reasons.append('cabin_price_structure_invalid');continue
  offers.append({'cabin':cabin['name'][0],'displayed_price_cny':float(cabin['price'][0][1:])})
 if not offers:reasons.append('no_cabin_offer')
 if not reasons:
  try:
   start=datetime.fromisoformat('2026-11-16T'+times[0]);end=datetime.fromisoformat('2026-11-16T'+times[1]);
   if end<start:end+=timedelta(days=1)
   match=re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?',dur[0]);minutes=int(match.group(1) or 0)*60+int(match.group(2) or 0)
   if not 0<(end-start).total_seconds()<=86400 or minutes!=int((end-start).total_seconds()/60):reasons.append('duration_mismatch')
   if one('depDateTime')!='2026-11-16 '+times[0]:reasons.append('departure_timestamp_mismatch')
  except (ValueError,AttributeError,TypeError):reasons.append('invalid_times')
 if reasons:return None,{'flight_no':flight,'reasons':reasons}
 return {'flight_no':flight,'origin':origin,'destination':dest,'origin_airport':one('dac'),
         'destination_airport':one('aac'),'departure':start.isoformat(timespec='minutes'),
         'arrival':end.isoformat(timespec='minutes'),'duration_minutes':minutes,'offers':offers,
         'airport_display':airport,'airline_display':f.get('airline-tag',[]),'raw_tags':f.get('tag',[]),
         'source_url':url,'source_raw_sha256':source_hash,'observed_at_utc':observed,
         'basis':'third_party_displayed_fare_reference','fees_final_payment_availability':'unknown'},None

def lookup(root,origin,dest,travel_date):
    """Re-parse the pinned original page; unknown date or missing source fails closed."""
    if travel_date != '2026-11-16' or origin not in CITIES or dest not in CITIES or origin==dest:return []
    try:
        base=Path(root).resolve(); plan=json.loads((base/'plan.json').read_text(encoding='utf8'))
        if plan.get('date')!=travel_date:return []
        hits=[i+1 for i,p in enumerate(plan['pairs']) if p==[origin,dest]]
        if len(hits)!=1:return []
        index=hits[0]; folders=list(base.glob(f'{index:02d}_*'))
        if len(folders)!=1:return []
        folder=folders[0]; receipt=json.loads((folder/'receipt.json').read_text(encoding='utf8'))
        raw=(folder/'response.html').read_bytes(); digest=hashlib.sha256(raw).hexdigest()
        if digest!=receipt.get('raw_sha256') or receipt.get('index')!=index:return []
        text=raw.decode('utf8','replace'); match=re.search(r'<meta name="description" content="([^\"]+)',text)
        if not match or not match.group(1).startswith(travel_date+origin+'到'+dest+'机票'):return []
        p=Cards();p.feed(text);expected=re.search(r'共(\d+)个航班',match.group(1))
        if not expected or int(expected.group(1))!=len(p.cards):return []
        output=[]
        for card in p.cards:
            item,_=parse_card(card,origin,dest,receipt['observed_at_utc'],digest,receipt['url'])
            if item:
                item['status']='date_scoped_single_source_reference'
                item['source_path']=str(folder/'response.html')
                output.append(item)
        return output
    except (OSError,KeyError,ValueError,TypeError):return []
