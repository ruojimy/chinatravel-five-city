"""Operator brand positioning plus separately retained exact shop contact proof."""
import gzip,hashlib,json,sqlite3,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p17_continuous/restaurants'
TARGETS=[('overture:08377639-068c-4242-bf46-22e352c7aee8','https://www.bingsheng.com/mapOffice_Detail_3/14.html','phone','+862034286911','020-34286911'),('overture:d568410b-4536-4560-8dbc-d3c9f9f7dbb7','https://www.bingsheng.com/mapOffice_Detail_3/15.html','address','天河区天河东路168号','天河区天河东路168号'),('overture:c27c40e6-8be7-4be0-afdd-c9d2a01aee49','https://www.bingsheng.com/mapOffice_Detail_3/16.html','phone','+862038035888','020-38035888')]
def sha(b):return hashlib.sha256(b).hexdigest()
def main(label):
 folder=OUT/label;folder.mkdir(exist_ok=False);q=sqlite3.connect(OUT/'http_transport_crawler/queue.sqlite3');ptr=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'));db=sqlite3.connect(ROOT/ptr['catalog']);sources=[];assertions=[];audit=[]
 def source(url):
  ev=json.loads(q.execute("SELECT result FROM jobs WHERE url=? AND status='captured'",(url,)).fetchone()[0]);raw=gzip.open(ev['raw_file'],'rb').read()
  if sha(raw)!=ev['sha256']:raise ValueError('Captured HTML changed')
  text=json.loads(Path(ev['extraction_file']).read_text(encoding='utf-8'))['extraction']['visible_text'];stem=sha(url.encode())[:20];(folder/(stem+'.txt')).write_bytes(text.encode());s={'source_id':'p17-bingsheng:'+stem,'source_url':url,'publisher':'广州市炳胜饮食管理有限公司','authority':'operator_website_self_description','independent_source_group':'bingsheng_operator_group','representation':'public_html_dom_text','content_file':stem+'.txt','content_sha256':sha(text.encode()),'retrieved_at':ev['retrieved_at'],'observed_at':None,'source_published_at':None,'source_updated_at':None,'valid_from':None,'valid_until':None,'licence_status':'public_web_reuse_unverified_private_research_only','source_locator':{'original_html_file':ev['raw_file'],'original_response_sha256':ev['sha256']}};sources.append(s);return s,text
 homepage,brandtext=source('https://www.bingsheng.com/');quote='实现了单一爆品到自成一家粤菜体系的跨越式进步。'
 if quote not in brandtext:raise ValueError('Brand cuisine self-description not explicit')
 for rid,url,kind,original_value,source_quote in TARGETS:
  source_detail,text=source(url)
  if source_quote not in text:raise ValueError('Detail quote not exact')
  r=json.loads(db.execute('SELECT payload FROM records WHERE id=?',(rid,)).fetchone()[0]);loc=r['source_locator'];original=None
  with gzip.open(ROOT/loc['raw_file'],'rb') as f:
   for n,line in enumerate(f,1):
    if n==loc['raw_line']:original=line.rstrip(b'\r\n');break
  if original is None or sha(original)!=loc['raw_sha256']:raise ValueError('Original entity changed')
  obj=json.loads(original)
  if kind=='phone':
   if original_value not in obj.get('phones',[]):raise ValueError('Phone not original')
   if original_value.removeprefix('+86')!=source_quote.replace('-','').removeprefix('0'):raise ValueError('National/international exact digits mismatch')
  elif original_value not in [a.get('freeform') for a in obj.get('addresses') or []]:raise ValueError('Address not original')
  name=rid.replace(':','_')+'.json';(folder/name).write_bytes(original);basis={'method':'explicit_original_contact_or_address_bound_to_operator_shop_detail_brand_scope_only','contact_type':kind,'original_value':original_value,'shop_detail_quote':source_quote,'shop_detail_source_id':source_detail['source_id'],'shop_detail_content_file':source_detail['content_file'],'shop_detail_content_sha256':source_detail['content_sha256'],'raw_row_file':str((folder/name).relative_to(ROOT)),'raw_row_sha256':sha(original),'original_source_locator':loc,'catalogue_city_window':r['city'],'provider_locality':'Guangzhou','operator_city':'广州','catalogue_city_supported':False,'entity_verified':False}
  assertions.append({'entity_id':rid,'entity_name':r['name'],'city':r['city'],'field':'cuisine_reference','value':'粤菜（运营方品牌自述）','unit':None,'quote':quote,'source_id':homepage['source_id'],'scope':'Official group culinary positioning only, linked to this shop through retained exact contact/address detail. This does not verify a current shop menu, dietary requirements, or current operating status; city-window mismatch remains.','identity_match_basis':basis,'status':'operator_brand_scope_reference_unknown_fact_age','cuisine_granularity':'brand_scope','native_projection_permitted':False,'entity_verified':False,'planning_ready':False})
  if rid.startswith('overture:c27'):
   conflict_quote='广东省广州市天河区珠江新城冼村路2号1-4楼(省博物馆对面)'
   if conflict_quote not in text:raise ValueError('Floor conflict quote not exact')
   assertions.append({'entity_id':rid,'field':'source_property_address_conflict','value':{'original_freeform':'广州市天河区冼村路2号5楼，','operator_freeform':conflict_quote,'conflict_dimension':'floor_level_5_vs_1_4'},'quote':conflict_quote,'source_id':source_detail['source_id'],'identity_match_basis':basis,'scope':'Phone matches but floor scope differs; do not automatically move, delete or rewrite this entity.','status':'conflicting_property_scope_requires_review','native_projection_permitted':False,'entity_verified':False})
  audit.append({'entity_id':rid,**basis})
 (folder/'field_assertions.json').write_text(json.dumps({'created_at':datetime.now(timezone.utc).isoformat(),'sources':sources,'assertions':assertions,'identity_audit':audit,'new_average_price_assertions':0,'new_opening_hours_assertions':0,'network_requests':0,'formal_database_modified':False},ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'sources':len(sources),'entities':len(audit),'assertions':len(assertions)}))
if __name__=='__main__':main(sys.argv[1])
