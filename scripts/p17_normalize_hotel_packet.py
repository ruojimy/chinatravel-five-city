"""Verify retained HTML bytes and DOM quotations before normalizing hotel packets."""
import argparse,gzip,hashlib,json,re,sys
from pathlib import Path
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p17_continuous'
sys.path[:0]=[str(ROOT/'src'),str(OUT/'hotels')]
from shorttrip.freshness import utcnow
from trip_detail_parser import parse_trip_html
def normalize(path):
 packet=json.loads(path.read_text(encoding='utf-8'));sources={};assertions=[];rejected=[]
 folder=path.parent/'review_dom_views';folder.mkdir(exist_ok=True)
 hotel_by_id={h['entity_id']:h for h in packet['hotels']}
 cache={}
 for a in packet['assertions']:
  hotel=hotel_by_id[a['entity_id']];match=a.get('entity_match',{})
  if not match.get('provider_city_match') or any('rebrand' in t.casefold() or 'differs from old' in t.casefold() for t in hotel.get('findings',[])):
   rejected.append({'entity_id':a['entity_id'],'reason':'unresolved_city_or_rebrand_identity','field':a['field']});continue
  e=a['evidence'];original=Path(e['path']);original=original if original.is_absolute() else path.parent/original
  if not original.resolve().is_relative_to(OUT.resolve()):raise ValueError('Source outside P17')
  if str(original) not in cache:
   compressed=original.read_bytes();raw=gzip.decompress(compressed) if original.suffix=='.gz' else compressed
   if hashlib.sha256(raw).hexdigest()!=e['sha256']:raise ValueError('Original HTML changed')
   if e.get('storage_sha256') and hashlib.sha256(compressed).hexdigest()!=e['storage_sha256']:raise ValueError('Storage hash changed')
   if 'trip.com' in e['source_url']:
    parsed=parse_trip_html(raw);text='\n'.join(r['minimum_dom_excerpt'] for r in parsed['room_configurations'])
   else:
    soup=BeautifulSoup(raw.decode('utf-8','replace'),'html.parser')
    for tag in soup(['script','style','noscript']):tag.decompose()
    text=soup.get_text(' ',strip=True)
   file=folder/(hashlib.sha256(raw).hexdigest()+'.txt');file.write_bytes(text.encode())
   cache[str(original)]=(text,file,hashlib.sha256(text.encode()).hexdigest())
  text,file,digest=cache[str(original)]
  if e['excerpt'] not in text:
   rejected.append({'entity_id':a['entity_id'],'field':a['field'],'reason':'quotation_not_exact_in_reparsed_dom'});continue
  sid='p17-dom:'+hashlib.sha256((e['source_url']+e['retrieved_at']).encode()).hexdigest()
  sources[sid]={'source_id':sid,'source_url':e['source_url'],'content_file':str(file.relative_to(path.parent)),
   'content_sha256':digest,'representation':'public_html_dom_text','retrieved_at':e['retrieved_at'],
   'observed_at':None,'source_updated_at':None,'source_published_at':None,
   'authority':e.get('authority','public_hotel_publisher'),'licence_status':e.get('licence_status','web_reuse_unverified'),
   'source_locator':{'original_html_file':str(original.relative_to(ROOT)),'original_response_sha256':e['sha256'],
    'original_storage_sha256':e.get('storage_sha256'),'transformation':'scripts removed; visible room-card DOM text only for Trip; body text otherwise'}}
  context={'entity_match':match,'original_source_capture':sources[sid]['source_locator'],'identity_verified':False}
  def add(field,value,scope):
   assertions.append({'entity_id':a['entity_id'],'field':field,'value':value,'unit':None if field=='room_type_name' else a.get('unit'),'scope':json.dumps(scope,ensure_ascii=False),
    'quote':e['excerpt'],'source_id':sid,'identity_match_basis':context,'status':'candidate_scoped_reference','native_projection_permitted':False})
  add(a['field'],a['value'],a['scope'])
  if a['field']=='room_bed_configuration' and a['scope'].get('room_type_name'):
   add('room_type_name',a['scope']['room_type_name'],a['scope'])
 report={'created_at':utcnow(),'sources':list(sources.values()),'assertions':assertions,'rejections':rejected,
  'note':'DOM text is a derived quotation view; original compressed HTML and both hashes retained. No source clock renewed.'}
 out=path.parent/'normalized_fields_v2.json'
 if out.exists():raise FileExistsError('Normalization batch immutable')
 out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'packet':str(out),'assertions':len(assertions),'rejections':len(rejected)}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('packet',type=Path);a=p.parse_args();normalize(a.packet)
