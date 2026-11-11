"""Review preserved transport pages; no names-only price/branch joins."""
import gzip,hashlib,json,sqlite3,sys,re
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p17_continuous/restaurants'
CONFLICTS={
 'https://www.worldfoodtrailer.com/':('non_dining_manufacturer','Food Truck Supplier'),
 'https://www.aelga.com/':('non_dining_manufacturer','Kitchenware Manufacturer'),
 'https://www.okicook.com/':('non_dining_manufacturer','Electric Pressure Cooker'),
 'https://www.llhfoods.com/':('non_dining_manufacturer','Biscuits Manufacturer'),
 'https://www.goalongliquor.com/':('liquor_manufacturer_not_local_dining_proof','Whiskey Distillery'),
 'https://www.cn-foodmachinery.com/':('non_dining_manufacturer','food processing machinery manufacturer'),
 'https://www.hrblink.com/':('non_dining_manufacturer','包装机械有限公司'),
 'https://guangzhou.park.huatt.com/en/hotel/dining/yur-jing-xuan.html':('domain_for_sale_not_dining_source','This domain may be for sale'),
 'https://www.greglouraichi.com/':('current_ai_enterprise_site_not_dining_source','企业级Agent中台'),
 'https://amberpalace.org/':('default_website_not_dining_evidence','Welcome to WordPress'),
 'https://www.hutong.com.tw/':('editorial_food_guide_not_local_venue_evidence','亞洲精緻餐飲及烹飪指南'),
 'https://picanhabbq.com/':('launching_soon_page_not_operating_hours_or_closure_proof','Launching Soon'),
 'https://www.songhelou.net/':('page_title_brand_conflict_needs_manual_review','新盛公司官网'),
}
def sha(b):return hashlib.sha256(b).hexdigest()
def main(label):
 folder=OUT/label
 if folder.exists():raise FileExistsError('Immutable output exists')
 folder.mkdir();pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'));db=sqlite3.connect((ROOT/pointer['catalog']).resolve().as_uri()+'?mode=ro',uri=True)
 c=sqlite3.connect(OUT/'http_transport_crawler/queue.sqlite3');sources=[];assertions=[];audit=[]
 targets=[*CONFLICTS,'https://www.thainarak.com/']
 for url in targets:
  evrow=c.execute("select result from jobs where url=? and status='captured'",(url,)).fetchone()
  if not evrow:continue
  ev=json.loads(evrow[0]);html=gzip.open(ev['raw_file'],'rb').read()
  if sha(html)!=ev['sha256']:raise ValueError('HTTP raw capture changed')
  extraction=json.loads(Path(ev['extraction_file']).read_text(encoding='utf-8'))['extraction'];text=extraction['visible_text'];sid='p17-http-review:'+sha(url.encode())[:20];file=sha(url.encode())[:20]+'.txt';(folder/file).write_bytes(text.encode('utf-8'))
  sources.append({'source_id':sid,'source_url':url,'publisher':'Public publisher at preserved transport candidate URL; operator identity separately reviewed','authority':'public_site_operator_unverified','independent_source_group':__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(url).hostname,'representation':'public_html_dom_text','content_file':file,'content_sha256':sha(text.encode()),'retrieved_at':ev['retrieved_at'],'source_published_at':None,'source_updated_at':None,'observed_at':None,'valid_from':None,'valid_until':None,'licence_status':'public_web_reuse_unverified_private_research_only','source_locator':{'original_html_file':str(Path(ev['raw_file']).resolve()),'original_response_sha256':ev['sha256'],'transport_role':'same-host/same-path HTTPS candidate derived from original observed HTTP link; not an original HTTPS assertion or website identity certificate'}})
  hints=c.execute('select entity_id,original_url,city from transport_hints where candidate_url=?',(url,)).fetchall()
  for rid,original_url,city in hints:
   record=json.loads(db.execute('select payload from records where id=?',(rid,)).fetchone()[0]);loc=record['source_locator'];raw=None
   with gzip.open(ROOT/loc['raw_file'],'rb') as stream:
    for n,line in enumerate(stream,1):
     if n==loc['raw_line']:raw=line.rstrip(b'\r\n');break
   if raw is None or sha(raw)!=loc['raw_sha256']:raise ValueError('Original row changed')
   origin=json.loads(raw)
   if original_url not in (origin.get('websites') or []):raise ValueError('Original website hint mismatch')
   rowname=rid.replace(':','_')+'.json';(folder/rowname).write_bytes(raw);basis={'method':'exact_original_gers_row_website_hint_preserved_https_transport_not_identity_certificate','raw_row_file':str((folder/rowname).relative_to(ROOT)),'raw_row_sha256':sha(raw),'original_http_url':original_url,'catalogue_name':record['name'],'catalogue_city':record['city'],'entity_verified':False}
   def add(field,value,unit,quote,scope,extra=None):
    if quote not in text:raise ValueError('Quote not grounded '+quote)
    a={'assertion_id':sid+':'+rid+':'+field,'entity_id':rid,'entity_name':record['name'],'city':city,'field':field,'value':value,'unit':unit,'quote':quote,'scope':scope,'source_id':sid,'identity_match_basis':basis,'status':'source_website_requires_review','entity_verified':False,'planning_ready':False,'native_projection_permitted':False}
    if extra:a.update(extra)
    assertions.append(a)
   if url in CONFLICTS:
    reason,quote=CONFLICTS[url];add('source_website_relevance_conflict',{'reason':reason,'observed_title':extraction['title']},None,quote,'Original website hint now serves this visible content. This is a source relevance/record classification review candidate only: do not delete, reclassify the entity or infer closure automatically.');audit.append({'entity_id':rid,'source_url':url,'reason':reason,'business_fields_added':0})
   else:
    addresses=[a.get('freeform','') for a in origin.get('addresses') or []];phones=[re.sub(r'\D','',a) for a in origin.get('phones') or []]
    addr='中山七路48号西门口广场137-1、139铺';phone='8618122769875'
    if record['name']!='Thai Narak' or addr not in addresses or phone not in phones or addr not in text:raise ValueError('Thai operator address/phone/name not bound')
    basis.update(method='exact_name_original_freeform_address_original_phone_original_linked_operator_page',matched_address=addr,matched_phone=phone,source_city='广州',catalogue_city_supported=False)
    quote='Lunch : 10:00 - 15:00 | Dinner : 17:00 - 22:00'
    add('opening_rules',{'lunch':'10:00-15:00','dinner':'17:00-22:00','timezone':'Asia/Shanghai','day_applicability':None},'local_clock',quote,'Operator explicit lunch and dinner intervals for Guangzhou shop. Weekdays/closure exceptions unspecified. This original entity was assigned to the Foshan research window; do not apply this evidence to a Foshan itinerary or bridge the lunch break.',{'status':'operator_reference_unknown_fact_age','source_city':'广州','native_values_suggestion':{}})
    add('source_city_relevance_conflict',{'catalogue_window':'佛山','operator_location':'广州','provider_locality':'Guangzhou'},None,'广州市荔湾区中山七路48号西门口广场137-1、139铺','Exact address and phone corroborate the original Guangzhou location; catalogue research-window city remains unverified. Root city-assignment review required; no automatic coordinate or city rewrite.')
 (folder/'field_assertions.json').write_text(json.dumps({'created_at':datetime.now(timezone.utc).isoformat(),'sources':sources,'assertions':assertions,'relevance_audit':audit,'formal_database_modified':False,'network_requests':0},ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'label':label,'sources':len(sources),'entities':len({a['entity_id'] for a in assertions}),'assertions':len(assertions),'opening_rules':sum(a['field']=='opening_rules' for a in assertions),'relevance_conflicts':len(audit)}))
if __name__=='__main__':main(sys.argv[1])
