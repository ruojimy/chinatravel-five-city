"""Immutable detail assertions with source-address and original-row audit."""
import argparse,gzip,hashlib,json,re,sqlite3,sys
from datetime import datetime,timezone
from pathlib import Path
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.scoped_business import matching_aliases
OUT=ROOT/'results/p17_continuous/restaurants'
def norm(x):return re.sub(r'[^\w\u4e00-\u9fff]','',x).casefold()
def digest(x):return hashlib.sha256(x).hexdigest()
def main(label):
 folder=OUT/label
 if folder.exists():raise FileExistsError('Immutable packet already exists')
 pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text());db=sqlite3.connect((ROOT/pointer['catalog']).resolve().as_uri()+'?mode=ro',uri=True)
 ix=sqlite3.connect(OUT/'hongchumao_candidates.sqlite3');crawl=sqlite3.connect(OUT/'hongchumao_crawler/queue.sqlite3');sources=[];assertions=[];audit=[];seen=set();folder.mkdir()
 # Avoid re-issuing facts already present in any previous immutable HCM packet.
 previous=set()
 for packet in OUT.glob('hongchumao_review_*/field_assertions.json'):
  for a in json.loads(packet.read_text(encoding='utf-8'))['assertions']:previous.add((a['entity_id'],a['source_id'],a['field']))
 for detail,rid,source_name,source_city,list_url in ix.execute('SELECT * FROM candidates ORDER BY detail_url,entity_id'):
  result=crawl.execute("SELECT result FROM jobs WHERE url=? AND status='captured'",(detail,)).fetchone()
  if not result:continue
  capture=json.loads(result[0]);html=gzip.open(capture['raw_file'],'rb').read()
  if digest(html)!=capture['sha256']:raise ValueError('HTML source changed')
  soup=BeautifulSoup(html.decode('utf-8'),'html.parser')
  for node in soup(['script','style','noscript','nav','footer']):node.decompose()
  text=soup.get_text(' ',strip=True);h1=soup.find('h1');name=h1.get_text(' ',strip=True) if h1 else None
  record=json.loads(db.execute('SELECT payload FROM records WHERE id=?',(rid,)).fetchone()[0]);loc=record['source_locator'];original=None
  if not rid.startswith('overture:'):continue
  with gzip.open(ROOT/loc['raw_file'],'rb') as stream:
   for n,line in enumerate(stream,1):
    if n==loc['raw_line']:original=line.rstrip(b'\r\n');break
  if original is None or digest(original)!=loc['raw_sha256']:raise ValueError('Original row changed')
  provider=json.loads(original);addresses=[a.get('freeform') for a in provider.get('addresses') or [] if a.get('freeform')]
  # A list name is a discovery lead. Actual detail label and full original address must bind.
  exact=bool(matching_aliases(name or '')&matching_aliases(record['name']));address=next((a for a in addresses if len(norm(a))>=8 and re.search(r'\d',a) and norm(a) in norm(text)),None)
  lexical_overlap=any(a in b or b in a for a in matching_aliases(name or '') for b in matching_aliases(record['name']) if len(a)>=4 and len(b)>=4)
  binding={'method':'same_city_source_detail_exact_or_branch_name_full_original_address','entity_name':record['name'],'source_detail_name':name,'same_city':source_city==record['city'],'exact_name_alias':exact,'lexical_name_overlap':lexical_overlap,'original_addresses':addresses,'matched_address':address,'entity_verified':False}
  audit.append({'entity_id':rid,'source_url':detail,**binding})
  if source_city!=record['city'] or not (exact or lexical_overlap):continue
  binding['binding_status']='exact_original_address_candidate' if address else 'unresolved_homonymous_name_city_lead_not_bound_entity_fact'
  sid='p17-hongchumao:'+detail.rsplit('/',1)[-1].removesuffix('.html')+':'+rid;stem=rid.replace(':','_')+'_'+detail.rsplit('/',1)[-1].replace('.html','');facts=[]
  price=re.search(r'人均消费\s*[¥￥]\s*(\d+(?:\.\d+)?)',text)
  if price:facts.append(('average_price',float(price[1]),'CNY/person',price[0],'Publisher aggregate average-spend reference from legacy certified restaurant catalogue; taxes, bill contents, validity and updated date unknown.'))
  # Explicit cuisine labels only; never infer from dishes, ranking tags or establishment name.
  for key in ['菜系','Cuisine']:
   match=re.search(re.escape(key)+r'\s*[:：]\s*([^。;；]{1,40})',text)
   if match:facts.append(('cuisine',match[1],None,match[0],'Explicit detail cuisine field, broad provider reference; no dietary guarantee.'));break
  for match in re.finditer(r'(?:营业时间|营业时段)\s*[:：]?\s*((?:周[^\s]{0,10}\s*)?\d{1,2}:\d{2}\s*[-–—至]\s*\d{1,2}:\d{2}(?:\s*[,，;；/]\s*\d{1,2}:\d{2}\s*[-–—至]\s*\d{1,2}:\d{2})?)',text):
   facts.append(('opening_rules',match[1],'local_clock',match[0],'Explicit labelled opening rule; retain split intervals and unknown day exceptions.'))
  if not address:
   # Preserve a review lead without counting it as the original entity's price.
   facts=[('unbound_'+field,value,unit,quote,'Unresolved homonymous name/city lead; source gives no target address. NOT a bound fact for this existing entity. '+scope) for field,value,unit,quote,scope in facts]
  fresh=[f for f in facts if (rid,sid,f[0]) not in previous]
  if not fresh:continue
  view=folder/(stem+'.txt');view.write_bytes(text.encode('utf-8'));rowfile=folder/(stem+'.json');rowfile.write_bytes(original);binding.update(raw_row_file=str(rowfile.relative_to(ROOT)),raw_row_sha256=loc['raw_sha256'])
  if sid not in seen:
   sources.append({'source_id':sid,'source_url':detail,'publisher':'红厨帽餐厅榜单 / 北京东方美食研究院','independent_source_group':'hongchumao_easteat_legacy_catalogue','authority':'specialist_restaurant_catalogue','licence_status':'public_web_reuse_unverified_bounded_research','representation':'public_html_dom_text','content_file':view.name,'content_sha256':digest(view.read_bytes()),'retrieved_at':capture['retrieved_at'],'observed_at':None,'source_updated_at':None,'source_published_at':None,'valid_from':None,'valid_until':None,'source_locator':{'original_html_file':str(Path(capture['raw_file']).resolve()),'original_response_sha256':capture['sha256'],'listing_url':list_url,'listing_scope':'Legacy certifications2006–2025; current page copyright is not a fact timestamp','dom_transformation':'scripts/style/noscript/nav/footer removed; visible text'}});seen.add(sid)
  for field,value,unit,quote,scope in fresh:
   assertions.append({'assertion_id':sid+'_'+field,'entity_id':rid,'entity_name':record['name'],'city':record['city'],'field':field,'value':value,'unit':unit,'scope':scope,'quote':quote,'source_id':sid,'identity_match_basis':binding,'status':'source_reference_unknown_fact_age' if address else 'unbound_discovery_lead_not_business_completion','entity_verified':False,'planning_ready':False,'native_projection_permitted':False,'root_projection_review_suggestion':'hongchumao_exact_address_reference' if address else None,'notes':['Legacy list years do not identify this field update time. No current price or opening guarantee.','Structured rating/reviewCount appears templated on some source pages; never used as confidence evidence.']})
 report={'created_at':datetime.now(timezone.utc).isoformat(),'sources':sources,'assertions':assertions,'identity_audit':audit,'formal_database_modified':False,'network_requests':0}
 (folder/'field_assertions.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'label':label,'captured_detail_candidate_pairs_examined':len(audit),'bound_existing_entities':len({a['entity_id'] for a in assertions if not a['field'].startswith('unbound_')}),'unresolved_homonymous_lead_entities':len({a['entity_id'] for a in assertions if a['field'].startswith('unbound_')}),'assertions':len(assertions),'field_counts':{f:sum(a['field']==f for a in assertions) for f in ['average_price','cuisine','opening_rules','unbound_average_price']}}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('label');a=p.parse_args();main(a.label)
