"""Extract only explicit detail labels; retain unmatched/old branches for review."""
import gzip,hashlib,json,re,sqlite3,sys
from pathlib import Path
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p17_continuous/restaurants'
sys.path.insert(0,str(ROOT/'src'));from shorttrip.freshness import utcnow
def norm(t):return re.sub(r'[^\w\u4e00-\u9fff]','',t).casefold()
def main():
 index=sqlite3.connect(OUT/'feinfood_entities.sqlite3');crawler=sqlite3.connect(OUT/'crawler/queue.sqlite3')
 pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'));catalog=sqlite3.connect(ROOT/pointer['catalog'])
 folder=OUT/'feinfood_review_001';folder.mkdir(exist_ok=True);sources=[];assertions=[];audit=[]
 for rid,city,name,detail in index.execute('SELECT DISTINCT entity_id,city,name,detail_url FROM listings'):
  row=crawler.execute("SELECT result FROM jobs WHERE url=? AND status='captured'",(detail,)).fetchone()
  if not row:continue
  ev=json.loads(row[0]);raw=gzip.open(ev['raw_file'],'rb').read()
  if hashlib.sha256(raw).hexdigest()!=ev['sha256']:raise ValueError('Source HTML changed')
  soup=BeautifulSoup(raw.decode('utf-8','replace'),'html.parser')
  for tag in soup(['script','style','noscript']):tag.decompose()
  text=soup.get_text(' ',strip=True);record=json.loads(catalog.execute('SELECT payload FROM records WHERE id=?',(rid,)).fetchone()[0]);loc=record['source_locator']
  original=None
  with gzip.open(ROOT/loc['raw_file'],'rb') as stream:
   for number,line in enumerate(stream,1):
    if number==loc['raw_line']:
     original=line.rstrip(b'\r\n');break
  if original is None or hashlib.sha256(original).hexdigest()!=loc['raw_sha256']:raise ValueError('Original row locator mismatch')
  provider=json.loads(original);addresses=[a.get('freeform') for a in provider.get('addresses') or [] if a.get('freeform')]
  address=next((a for a in addresses if len(norm(a))>=8 and re.search(r'\d',a) and norm(a) in norm(text)),None)
  rawrow=folder/(rid.replace(':','_')+'.json');rawrow.write_bytes(original)
  identity={'method':'exact_original_freeform_address_in_source_dom' if address else 'exact_name_city_candidate_address_unresolved',
   'matched_address':address,'raw_row_file':str(rawrow.relative_to(ROOT)),'raw_row_sha256':loc['raw_sha256'],
   'source_property_name':name,'city':city,'entity_verified':False}
  audit.append({'entity_id':rid,'name':record['name'],'source_name':name,'original_addresses':addresses,**identity})
  view=folder/(rid.replace(':','_')+'.txt');view.write_bytes(text.encode());sid='p17-feinfood:'+rid
  sources.append({'source_id':sid,'source_url':detail,'retrieved_at':ev['retrieved_at'],'observed_at':None,
   'source_updated_at':None,'source_published_at':None,'authority':'specialist_restaurant_catalogue','licence_status':'public_web_reuse_unverified',
   'content_file':view.name,'content_sha256':hashlib.sha256(view.read_bytes()).hexdigest(),'representation':'public_html_dom_text',
   'source_locator':{'original_html_file':ev['raw_file'],'original_response_sha256':ev['sha256'],'dom_transformation':'scripts removed; visible text'}})
  def add(field,value,quote,unit,scope,specific=False):
   if quote not in text:raise ValueError('DOM quotation not exact')
   assertions.append({'entity_id':rid,'field':field,'value':value,'unit':unit,'scope':scope,'quote':quote,'source_id':sid,
    'identity_match_basis':identity,'root_projection_review':'feinfood_exact_address_reference' if address and field in ('avg_price','cuisine') else None,
    'cuisine_granularity':'specific' if specific else 'coarse','status':'source_reference_unknown_fact_age','entity_verified':False})
  for li in soup.find_all('li'):
   label=li.find('label');b=li.find('b')
   if label and b and label.get_text(strip=True).startswith('人均'):
    quote=b.get_text(' ',strip=True);m=re.fullmatch(r'RMB\s+(\d+(?:\.\d+)?)',quote)
    if m:add('avg_price',float(m[1]),quote,'CNY_per_person_reference','Publisher average spend reference, bill and current operating status not guaranteed; no publication or update clock available.')
  cuisines={}
  for line in soup.select('div.line'):
   label=line.select_one('.left');value=line.select_one('.right')
   if not label or not value:continue
   key=label.get_text(' ',strip=True).rstrip(':：')
   if key in ('中餐类型','菜系类型') and value.get_text(' ',strip=True):cuisines[key]=value.get_text(' ',strip=True)
  if cuisines:
   value=cuisines.get('中餐类型') or cuisines['菜系类型'];add('cuisine',value,value,None,'Explicit publisher cuisine label; not a dietary or authenticity certificate.',bool(cuisines.get('中餐类型')))
  hours={}
  for th in soup.find_all('th'):
   key=th.get_text(' ',strip=True);td=th.find_next_sibling('td')
   if key in ('营业时间(工作日)','营业时间(周末)','休息日') and td and td.get_text(' ',strip=True):hours[key]=td.get_text(' ',strip=True)
  for key,value in hours.items():add('opening_rules',{'label':key,'rule':value},value,'local_clock_Asia/Shanghai','Only the explicitly labelled weekday/weekend/rest-day scope; do not fill blank weekend hours or bridge meal breaks.')
 report={'created_at':utcnow(),'sources':sources,'assertions':assertions,'identity_audit':audit,'network_requests':0}
 out=folder/'field_assertions.json'
 if out.exists():raise FileExistsError('Review packet immutable')
 out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'entities':len(audit),'exact_original_address_matches':sum(bool(x['matched_address']) for x in audit),'assertions':len(assertions)}))
if __name__=='__main__':main()
