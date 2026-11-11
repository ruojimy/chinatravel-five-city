"""Offline, byte-grounded restaurant taxonomy recovery; no provider requests."""
import collections,gzip,hashlib,json,sqlite3,sys
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/p17_continuous/restaurants'
MAPPING={
 'chinese_restaurant':'中餐（大类）','cantonese_restaurant':'粤菜',
 'italian_restaurant':'意大利菜','japanese_restaurant':'日本料理',
 'korean_restaurant':'韩国料理','thai_restaurant':'泰国菜','german_restaurant':'德国菜',
 'french_restaurant':'法国菜','indian_restaurant':'印度菜','taiwanese_restaurant':'台湾菜',
 'american_restaurant':'美国菜（大类）','southern_american_restaurant':'美国南方菜',
 'mexican_restaurant':'墨西哥菜','european_restaurant':'欧洲菜（大类）',
 'malaysian_restaurant':'马来西亚菜','vietnamese_restaurant':'越南菜',
 'mediterranean_restaurant':'地中海菜（大类）','mongolian_restaurant':'蒙古菜',
 'greek_restaurant':'希腊菜','russian_restaurant':'俄罗斯菜','turkish_restaurant':'土耳其菜',
 'indonesian_restaurant':'印度尼西亚菜','afghani_restaurant':'阿富汗菜',
 'lebanese_restaurant':'黎巴嫩菜','eastern_european_restaurant':'东欧菜（大类）',
 'latin_american_restaurant':'拉丁美洲菜（大类）',
 'middle_eastern_restaurant':'中东菜（大类）','portuguese_restaurant':'葡萄牙菜',
 'african_restaurant':'非洲菜（大类）','pakistani_restaurant':'巴基斯坦菜',
 'brazilian_restaurant':'巴西菜','spanish_restaurant':'西班牙菜',
 'british_restaurant':'英国菜','basque_restaurant':'巴斯克菜','arabian_restaurant':'阿拉伯菜（大类）',
}
VERSION='p17-explicit-geographic-cuisine-v1'
def sha(b):return hashlib.sha256(b).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def main():
 OUT.mkdir(parents=True,exist_ok=True);(OUT/'raw_rows').mkdir(exist_ok=True);(OUT/'taxonomy_batches').mkdir(exist_ok=True)
 now=datetime.now(timezone.utc).isoformat();pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text())
 db=sqlite3.connect((ROOT/pointer['catalog']).resolve().as_uri()+'?mode=ro',uri=True)
 records={json.loads(p)['record_id']:json.loads(p) for p, in db.execute("SELECT payload FROM records WHERE kind='restaurant'")};db.close()
 sources=[];assertions=[];audit=[];skipped=collections.Counter();seen=set();matched=0
 for f in sorted((ROOT/'data/expansion_v1_20261022/raw').glob('*.jsonl.gz')):
  with gzip.open(f,'rb') as stream:
   for line_no,line in enumerate(stream,1):
    raw=json.loads(line);rid='overture:'+raw['id'];r=records.get(rid)
    if r is None:continue
    origin=r['source_locator']
    if Path(origin.get('raw_file',''))!=f.relative_to(ROOT):continue
    matched+=1;taxonomy=raw.get('taxonomy') or {};code=taxonomy.get('primary');hierarchy=taxonomy.get('hierarchy') or []
    raw_hash=sha(line.rstrip(b'\r\n'))
    binding={'entity_id':rid,'entity_name':r['name'],'city':r['city'],'raw_file':str(f.relative_to(ROOT)),
      'raw_line':line_no,'raw_line_sha256':raw_hash,'category':code,'existing_cuisine':r['data'].get('cuisine'),
      'catalogue_entity_same_gers_id':origin.get('gers_id')==raw['id'],'catalogue_raw_line_matches':origin.get('raw_line')==line_no,
      'catalogue_raw_file_matches':Path(origin.get('raw_file',''))==f.relative_to(ROOT),'provider_city_match':origin.get('provider_city_match',False)}
    if not all(binding[k] for k in ('catalogue_entity_same_gers_id','catalogue_raw_line_matches','catalogue_raw_file_matches')):
     raise ValueError('Immutable source locator mismatch: '+rid)
    if rid in seen:raise ValueError('Duplicate raw entity ID: '+rid)
    seen.add(rid)
    if not hierarchy or hierarchy[-1]!=code or len(hierarchy)!=len(set(hierarchy)):
     binding['result']='invalid_taxonomy_hierarchy';skipped[binding['result']]+=1;audit.append(binding);continue
    if code not in MAPPING:
     binding['result']='category_not_geographic_cuisine';skipped[code or 'missing']+=1;audit.append(binding);continue
    label=MAPPING[code];raw_name=raw.get('names',{}).get('primary')
    if raw_name!=r['name']:raise ValueError('Unexpected name mismatch: '+rid)
    sid='p17_taxonomy_'+raw['id'];file='raw_rows/'+raw['id']+'.json';content=line.rstrip(b'\r\n')
    path=OUT/file
    if path.exists() and path.read_bytes()!=content:raise ValueError('Existing evidence changed')
    path.write_bytes(content)
    quote=json.dumps({'primary':code},ensure_ascii=False,separators=(',',':'))[1:-1]
    if quote not in content.decode('utf-8'):raise ValueError('Quote not byte grounded')
    source={'source_id':sid,'source_url':r['source_url'],'publisher':'Overture Maps Foundation / upstream providers as listed in saved row',
      'independent_source_group':'saved_overture_places_same_original_provider_not_new_independent_evidence',
      'authority':'structured_provider','representation':'saved_original_json_row','content_file':file,'content_sha256':sha(content),
      'retrieved_at':r['retrieved_at'],'source_published_at':r.get('source_published_at'),'source_updated_at':None,'observed_at':None,
      'valid_from':None,'valid_until':None,'licence_status':r['licence_status'],
      'upstream_source_metadata':raw.get('sources',[]),'source_locator':binding,
      'retrieval_clock_basis':'original preserved extraction clock; local review never refreshes original facts',
      'source_clock_note':'No timestamp attributed specifically to taxonomy; row source/confidence update times are not taxonomy observations.'}
    assertion={'assertion_id':sid+'_cuisine','entity_id':rid,'entity_name':r['name'],'city':r['city'],'field':'cuisine','value':label,'unit':None,
      'source_id':sid,'source_url':r['source_url'],'evidence_sha256':source['content_sha256'],'evidence_file':file,
      'retrieved_at':r['retrieved_at'],'source_published_at':r.get('source_published_at'),'source_updated_at':None,'observed_at':None,
      'valid_from':None,'valid_until':None,'applicability':{'scope_type':'provider_taxonomy_reference','taxonomy_category':code},
      'scope':'Saved provider geographic cuisine classification only; no menu, branch status, authenticity, allergen, halal or dietary guarantee.',
      'quote':quote,'status':'derived_reference','entity_verified':False,'identity_match_basis':'Same immutable GERS ID, raw source locator, exact raw name; no independent reality verification.',
      'native_projection_permitted':False,'planning_ready':False,'ttl_seconds':15552000,
      'freshness_status':'unknown_taxonomy_fact_clock','cuisine_granularity':'coarse','mapping_version':VERSION,
      'mapping_input':code,'mapping_basis':'explicit_geographic_primary_category_not_name_inference',
      'native_values_suggestion':{'cuisine':label},'native_provenance_status_suggestion':'derived',
      'notes':['Coarse source category cannot establish a finer Chinese regional cuisine.','City identity, uncertainty, real-time and planning gates remain unchanged.'],
      'evidence_locator':{'method':'exact_substring','quote':quote,'json_pointer':'/taxonomy/primary'},
      'tags':[{'tag':'cuisine','value':label,'scope':'source taxonomy geographic classification only','source_id':sid,
        'evidence_sha256':source['content_sha256'],'status':'derived_source_reference','observed_at':None,'valid_until':None}]}
    binding.update(result='derived_cuisine_reference',mapped_value=label,mapping_version=VERSION)
    sources.append(source);assertions.append(assertion);audit.append(binding)
    if len(assertions)%10==0:
     n=len(assertions)//10;dump(OUT/'taxonomy_batches'/f'batch_{n:04}.json',{'schema_version':'p16-field-assertions-v1','created_at':now,'sources':sources[-10:],'assertions':assertions[-10:]})
 if len(assertions)%10:
  n=len(assertions)//10+1;k=len(assertions)%10;dump(OUT/'taxonomy_batches'/f'batch_{n:04}.json',{'schema_version':'p16-field-assertions-v1','created_at':now,'sources':sources[-k:],'assertions':assertions[-k:]})
 dump(OUT/'taxonomy_mapping.json',{'version':VERSION,'mapping':MAPPING,'excluded':'Non-geographic restaurant type / generic restaurant / dietary labels are not cuisine projections.'})
 dump(OUT/'taxonomy_assertions.json',{'schema_version':'p16-field-assertions-v1','created_at':now,'catalogue_basis':pointer,
  'entity_verified':False,'formal_database_modified':False,'raw_html_obtained':False,'sources':sources,'assertions':assertions})
 with (OUT/'taxonomy_audit.jsonl').open('w',encoding='utf-8') as out:
  for a in audit:out.write(json.dumps(a,ensure_ascii=False)+'\n')
 summary={'at':now,'records_examined':len(records),'overture_rows_bound':matched,'assertions':len(assertions),
  'entities_with_cuisine_reference':len(assertions),'existing_nonempty_cuisine':sum(a['existing_cuisine'] is not None and a['result']=='derived_cuisine_reference' for a in audit),
  'new_null_cuisine_reference':sum(a['existing_cuisine'] is None and a['result']=='derived_cuisine_reference' for a in audit),
  'city_supported':sum(a['provider_city_match'] and a['result']=='derived_cuisine_reference' for a in audit),
  'skipped_categories':dict(skipped),'network_requests':0,'formal_database_modified':False,'independent_reality_checks':0,
  'source_clocks_refreshed':0,'mapping_version':VERSION,'validation':{'every_raw_locator_matched':True,'every_raw_id_and_name_matched':True,'every_quote_is_exact':True,'no_generic_or_dietary_mapping':True}}
 dump(OUT/'taxonomy_summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
