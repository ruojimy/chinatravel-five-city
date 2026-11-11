"""Strict-address-only business evidence; unresolved branches stay discovery."""
import gzip,hashlib,json,re,sqlite3,sys,collections
from pathlib import Path
from bs4 import BeautifulSoup
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p17_continuous/restaurants'
sys.path.insert(0,str(ROOT/'src'));from shorttrip.business_archives import normalize_name as norm
def sha(b):return hashlib.sha256(b).hexdigest()
def main(label):
 folder=OUT/label;folder.mkdir(exist_ok=False);index=sqlite3.connect(OUT/'feinfood_provider_entities.sqlite3');c=sqlite3.connect(OUT/'crawler/queue.sqlite3');pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'));db=sqlite3.connect(ROOT/pointer['catalog']);sources=[];assertions=[];audit=[]
 seen=set()
 for old in OUT.glob('feinfood_provider_review_*/field_assertions.json'):
  prior=json.loads(old.read_text(encoding='utf-8'));urls={s['source_id']:s['source_url'] for s in prior.get('sources',[])}
  for a in prior.get('assertions',[]):seen.add((a['entity_id'],a['field'],json.dumps(a['value'],sort_keys=True,ensure_ascii=False),a['quote'],urls.get(a['source_id'])))
 for rid,city,name,url,parent,parent_sha in index.execute('SELECT * FROM listings'):
  row=c.execute("SELECT result FROM jobs WHERE url=? AND status='captured'",(url,)).fetchone()
  if not row:continue
  ev=json.loads(row[0]);raw=gzip.open(ev['raw_file'],'rb').read()
  if sha(raw)!=ev['sha256']:raise ValueError('Capture hash changed')
  soup=BeautifulSoup(raw,'html.parser')
  for tag in soup(['script','style','noscript']):tag.decompose()
  text=soup.get_text(' ',strip=True);r=json.loads(db.execute('SELECT payload FROM records WHERE id=?',(rid,)).fetchone()[0]);loc=r['source_locator'];original=None
  with gzip.open(ROOT/loc['raw_file'],'rb') as stream:
   for n,line in enumerate(stream,1):
    if n==loc['raw_line']:original=line.rstrip(b'\r\n');break
  if original is None or sha(original)!=loc['raw_sha256']:raise ValueError('Entity row changed')
  obj=json.loads(original);addresses=[a['freeform'] for a in obj.get('addresses') or [] if a.get('freeform')];address=next((a for a in addresses if len(norm(a))>=7 and re.search(r'\d',a) and norm(a) in norm(text)),None);address_component=None
  if not address:
   for a in addresses:
    # A literal Chinese address explicitly separated after an ASCII address,
    # never an invented translation or a stripped floor/unit suffix.
    m=re.fullmatch(r'[\dA-Za-z .,\'-]+\s{2,}([\u4e00-\u9fff][\u4e00-\u9fff0-9-]+)',a)
    if m and len(norm(m[1]))>=7 and re.search(r'\d',m[1]) and norm(m[1]) in norm(text):address_component=m[1];break
  # Explicit international prefix formatting only, never guessed street translation.
  def phone_norm(value):
   digits=re.sub(r'\D','',value)
   return digits[2:] if digits.startswith('0086') else digits
  original_phones={phone_norm(p) for p in obj.get('phones') or [] if re.fullmatch(r'\+86\d{10,11}',p)}
  phone_match=next((h.get_text(' ',strip=True) for h in soup.find_all('h3') if re.fullmatch(r'(?:\+86|0086)[\d\s-]+',h.get_text(' ',strip=True)) and phone_norm(h.get_text(' ',strip=True)) in original_phones),None)
  method='exact_original_freeform_address_in_source_discovery_candidate' if address else ('literal_explicit_bilingual_address_component_in_source_dom' if address_component else ('exact_original_international_phone_in_source_discovery_candidate' if phone_match else 'source_name_alias_or_brand_discovery_branch_unresolved'))
  stem=rid.replace(':','_');view_stem=stem+'_'+sha(url.encode())[:12];(folder/(stem+'.json')).write_bytes(original);(folder/(view_stem+'.txt')).write_bytes(text.encode());basis={'method':method,'matched_address':address,'matched_explicit_bilingual_address_component':address_component,'matched_phone_quote':phone_match,'matched_phone_normalized':phone_norm(phone_match) if phone_match else None,'original_source_locator':loc,'raw_row_file':str((folder/(stem+'.json')).relative_to(ROOT)),'raw_row_sha256':sha(original),'source_property_name':name,'source_city':city,'catalogue_city_window':r['city'],'catalogue_city_supported':r['city']==city,'directory_parent_url':parent,'directory_parent_sha256':parent_sha,'entity_verified':False};audit.append({'entity_id':rid,'entity_name':r['name'],'original_addresses':addresses,'source_url':url,'captured_dom_file':view_stem+'.txt','captured_dom_sha256':sha(text.encode()),**basis})
  if not (address or address_component or phone_match):continue
  sid='p17-feinfood-provider:'+rid+':'+sha(url.encode())[:12];sources.append({'source_id':sid,'source_url':url,'retrieved_at':ev['retrieved_at'],'observed_at':None,'source_published_at':None,'source_updated_at':None,'valid_from':None,'valid_until':None,'authority':'specialist_restaurant_catalogue','independent_source_group':'feinfood','licence_status':'public_web_reuse_unverified_private_research','representation':'public_html_dom_text','content_file':view_stem+'.txt','content_sha256':sha(text.encode()),'source_locator':{'original_html_file':ev['raw_file'],'original_response_sha256':ev['sha256'],'dom_transformation':'scripts/styles/noscript removed; DOM text'}})
  def add(field,value,quote,unit=None,scope=''):
   if quote not in text:raise ValueError('Quote not exact')
   if (rid,field,json.dumps(value,sort_keys=True,ensure_ascii=False),quote,url) in seen:return
   assertions.append({'entity_id':rid,'entity_name':r['name'],'city':r['city'],'field':field,'value':value,'unit':unit,'quote':quote,'source_id':sid,'scope':scope+' Unknown source fact observation/update/publication time. City-window mismatch retained; no native projection or present-day applicability asserted.','status':'source_reference_unknown_fact_age','identity_match_basis':basis,'native_projection_permitted':False,'entity_verified':False,'planning_ready':False})
  for li in soup.find_all('li'):
   label=li.find('label');b=li.find('b')
   if label and b and label.get_text(strip=True).startswith('人均'):
    quote=b.get_text(' ',strip=True);m=re.fullmatch(r'RMB\s+(\d+(?:\.\d+)?)',quote)
    if m:add('average_price',float(m[1]),quote,'CNY_per_person_reference','Publisher reference average spend, not a current bill or guaranteed budget.')
  cuisines={}
  for line in soup.select('div.line'):
   left=line.select_one('.left');right=line.select_one('.right')
   if left and right and left.get_text(' ',strip=True).rstrip(':：') in ('中餐类型','菜系类型'):cuisines[left.get_text(' ',strip=True).rstrip(':：')]=right.get_text(' ',strip=True)
  value=cuisines.get('中餐类型') or cuisines.get('菜系类型')
  if value:add('cuisine',value,value,None,'Explicit publisher cuisine category, not dietary certification.')
  for th in soup.find_all('th'):
   label=th.get_text(' ',strip=True);td=th.find_next_sibling('td')
   if label in ('营业时间(工作日)','营业时间(周末)','休息日') and td and td.get_text(' ',strip=True):
    value=td.get_text(' ',strip=True);add('opening_rules',{'label':label,'rule':value},value,'local_clock_Asia/Shanghai','Only the explicit weekday/weekend/rest-day rule; do not fill omitted periods or bridge breaks.')
 # A source property binding multiple distinct original IDs is an ambiguity,
 # not two newly completed restaurants.
 ids_by_url=collections.defaultdict(set)
 for a in audit:
  if a['matched_address'] or a.get('matched_explicit_bilingual_address_component') or a['matched_phone_quote']:ids_by_url[a['source_url']].add(a['entity_id'])
 ambiguous={u for u,ids in ids_by_url.items() if len(ids)>1};ambiguous_sids={s['source_id'] for s in sources if s['source_url'] in ambiguous};assertions=[a for a in assertions if a['source_id'] not in ambiguous_sids]
 for a in audit:
  if a['source_url'] in ambiguous:a['binding_rejection']='multiple_existing_ids_share_this_source_property_address_or_phone'
 sources=[s for s in sources if s['source_id'] in {a['source_id'] for a in assertions}]
 report={'created_at':datetime.now(timezone.utc).isoformat(),'sources':sources,'assertions':assertions,'identity_audit':audit,'network_requests':0,'new_entities':0,'source_clocks_refreshed':0,'unresolved_price_assertions_in_formal_packet':0,'full_completion':False};(folder/'field_assertions.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'detail_candidates_reviewed':len(audit),'new_business_source_entities':len(sources),'assertions':len(assertions)}))
if __name__=='__main__':main(sys.argv[1])
