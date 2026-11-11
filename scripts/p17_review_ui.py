"""Register two manually observed date/room scoped Tongcheng research captures."""
import hashlib,json,sys
from datetime import datetime,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from p17_review_batch import review
from shorttrip.business_completion import validate_room_offer
from shorttrip.freshness import utcnow
OUT=ROOT/'results/p17_continuous';BROWSER=OUT/'browser'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 sources=[];assertions=[];offers=[]
 for slug in ('marco','pullman'):
  p=json.loads((BROWSER/(slug+'_ui_packet.json')).read_text(encoding='utf-8'))
  cards=BROWSER/(slug+'_cards.txt');modal=BROWSER/(slug+'_king_confirmed.txt');image=BROWSER/(slug+'_king_confirmed.png')
  raw=cards.read_bytes()+b'\n--- retained room modal ---\n'+modal.read_bytes();view=BROWSER/(slug+'_review_view.txt')
  view.write_bytes(raw);text=raw.decode('utf-8');assert '1张1.8米大床' in text
  stamp=p['observed_at'];sid='p17-ui:'+slug;file=slug+'_review_view.txt'
  source={'source_id':sid,'source_url':p['source_url'],'content_file':file,'content_sha256':digest(view),
   'representation':'rendered_ui_text','authority':'online_travel_agency','licence_status':'private_research_capture_no_open_redistribution_claim',
   'observed_at':stamp,'retrieved_at':stamp,'source_published_at':None,'source_updated_at':None,
   'source_locator':{'cards':{'file':str(cards.relative_to(ROOT)),'sha256':digest(cards)},'modal':{'file':str(modal.relative_to(ROOT)),'sha256':digest(modal)},'screenshot':{'file':str(image.relative_to(ROOT)),'sha256':digest(image)}}}
  sources.append(source)
  room=p['room_type_name'];scope=json.dumps({'room_type_name':room,'bed_description':'1张1.8米大床','hotel_address':p['address'],'physical_beds_per_reserved_room':1},ensure_ascii=False)
  for field,value,quote,unit in [('room_type_name',room,room,None),('bed_configuration',1,'1张1.8米大床','physical_beds_per_reserved_room')]:
   assertions.append({'entity_id':p['entity_id'],'field':field,'value':value,'unit':unit,'scope':scope,'quote':quote,'source_id':sid,'native_projection_review':'root_seen_room_modal' if field=='bed_configuration' else None,'identity_match_basis':'Root inspected named hotel, address, date selection, recommended-room modal and explicit bed number; geography not independently certified'})
  checkin=p.get('checkin',p.get('check_in'));checkout=p.get('checkout',p.get('check_out'));price=p.get('displayed_price',p.get('conditional_display_price'))
  condition=p.get('price_conditions') or '返现后；'+p['payment_quote']+'；'+p['cancellation_quote']+'；无餐食；'+p['rate_plan_quote']
  end=(datetime.fromisoformat(stamp.replace('Z','+00:00'))+timedelta(seconds=300)).isoformat()
  offer={'offer_id':'tongcheng:p17:'+slug+':20261024:20261025:1r2a','entity_id':p['entity_id'],
   'room_type_name':room,'room_type_id':None,'bed_count':1,'rooms_reserved':1,'adults':2,'children':0,'checkin':checkin,'checkout':checkout,'nights':1,
   'currency':'CNY','rate_plan_name':condition,'rate_plan_id':p.get('rate_plan_id'),
   'price_breakdown':{'displayed_stay_total':price,'room_base':None,'service_charge':None,'tax_and_government_charge':None,
     'amount_semantics':'conditional cashback display; one night one room, not guaranteed payable total'},
   'quote_status':'conditional_cashback_and_eligibility_unverified','membership_required':None,'observed_at':stamp,'retrieved_at':stamp,
   'valid_until':end,'source_published_at':None,'source_updated_at':None,'source_id':sid,'source_url':p['source_url'],
   'screenshot_evidence':[source['source_locator']['screenshot']],'actual_user_trip':False,'not_an_inventory_guarantee':True}
  assert validate_room_offer(offer,now=utcnow())['ok'];assert validate_room_offer(offer,now=utcnow())['native_price_per_room_night'] is None
  offers.append(offer)
 packet=BROWSER/'reviewed_ui_fields.json'
 if packet.exists():raise FileExistsError('UI review immutable')
 packet.write_text(json.dumps({'sources':sources,'assertions':assertions},ensure_ascii=False,indent=2),encoding='utf-8')
 review(packet,'browser_ui_001')
 batch=json.loads((OUT/'approved_batches/browser_ui_001.json').read_text(encoding='utf-8'))
 for offer in offers:offer['evidence_id']=next(a['evidence_id'] for a in batch['assertions'] if a['entity_id']==offer['entity_id'])
 out=OUT/'approved_batches/browser_offers_001.json';out.write_text(json.dumps({'reviewed_at':utcnow(),'offers':offers},ensure_ascii=False,indent=2),encoding='utf-8')
 index=out.parent/'room_offers_index.json';index.write_text(json.dumps({'batches':[{'file':str(out.relative_to(ROOT)),'sha256':digest(out)}]},indent=2),encoding='utf-8')
 print(json.dumps({'reviewed_room_offers':len(offers),'native_budget_prices':0}))
if __name__=='__main__':main()
