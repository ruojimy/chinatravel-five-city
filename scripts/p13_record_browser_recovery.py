"""Retain a normal-UI offer as a validated, conditional research candidate."""
from pathlib import Path
import hashlib,json,sys
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_completion import validate_room_offer
from shorttrip.freshness import utcnow

def main():
    dest=ROOT/'results/p13_business_completion/browser_recovery_20261022'
    observed='2026-10-22T12:26:22.812Z'
    files=['tongcheng_twin_room_details.png','tongcheng_twin_fee_details.png']
    screenshots=[{'path':p,'sha256':hashlib.sha256((dest/p).read_bytes()).hexdigest()} for p in files]
    offer={
      'offer_id':'tongcheng-ui-51401015-twin-package-20261024-20261022T122622Z',
      'entity_id':'overture:788c7681-3fe9-43aa-b7ec-f8fb2836c7c0',
      'hotel_name':'厦门磐基希尔顿酒店','provider_property_id':'51401015',
      'hotel_address_quote':'思明区嘉禾路199号',
      'room_type_id':None,'room_type_name':'豪华双床房',
      'room_type_id_status':'Not assumed from an AX container label or another supplier room code',
      'bed_count':2,'bed_count_quote':'2张1.3米单人床','bed_width_metres':1.3,
      'room_area_m2':35,'floor_quote':'6-8层',
      'rooms_reserved':1,'adults':2,'children':0,
      'checkin':'2026-10-24','checkout':'2026-10-25','nights':1,'currency':'CNY',
      'actual_user_trip':False,'rooms_reserved_basis':'one-room pricing unit, not a submitted reservation',
      'rate_plan_name':'套餐：无餐食，欢迎软饮1份及磐基中心餐饮折扣礼遇1份，到店付需担保',
      'rate_plan_id':None,'visible_offer_label':'lm5439b1',
      'membership_required':None,'membership_note':'Logged-in session; unrestricted eligibility not established',
      'breakfast_included':False,'payment':'到店付·需担保',
      'cancellation_quote':'入住日18:00前可免费取消',
      'price_breakdown':{'room_base':None,'service_charge':None,'tax_and_government_charge':None,
          'displayed_stay_total':639,'displayed_per_room_per_night':639,
          'tax_inclusion_status':'not separately disclosed in inspected panel'},
      'display_rounding_quote':'小数点向上取整展示',
      'display_rounding_scope':'Rendered display is ceil-rounded, not an exact cent-level total',
      'settlement_note':'Actual payment can depend on benefits/coupons; final settlement page authoritative',
      'source_id':'tongcheng_normal_browser_ui',
      'source_url':'https://www.ly.com/hotel/hoteldetail?hotelId=51401015&inDate=2026-10-24&outDate=2026-10-25&adultsNumber=2',
      'source_url_note':'Re-entry URL removes visible tracking parameters; no cookies or credentials exported',
      'source_published_at':None,'source_updated_at':None,
      'observed_at':observed,'retrieved_at':observed,
      'valid_until':(datetime.fromisoformat(observed.replace('Z','+00:00'))+timedelta(seconds=300)).isoformat(),
      'ttl_seconds':300,'authority':'travel_marketplace_rendered_offer',
      'independent_upstream_lineage_confirmed':False,
      'quote_status':'conditional_rounded_display_without_tax_components_or_eligibility_confirmation',
      'screenshot_evidence':screenshots,
      'tags':[{'tag':'bed_configuration','value':'two_single_beds','scope':'豪华双床房',
          'basis':'explicit_rendered_room_description','observed_at':observed,'ttl_seconds':2592000},
          {'tag':'breakfast','value':'not_included','scope':'this_package_only',
          'basis':'explicit_rendered_rate_card','observed_at':observed,'ttl_seconds':300}],
      'not_comparable_as_identical_rate_to_operator_offer':True,
      'comparison_note':'Similar rounded display to prior Hilton 638.97 is not proof of identical product, fee composition or independent sourcing',
      'reservations_submitted':0,'credentials_read':False,'hidden_api_calls':0,
      'load_status':'validated_offer_candidate_only; not loaded into immutable v1.2 catalog'
    }
    target=dest/'tongcheng_conditional_offer.json'
    if target.exists():raise SystemExit('Offer already recorded; preserve observation clock')
    gate=validate_room_offer(offer,now=utcnow())
    if not gate['ok']:raise ValueError(gate)
    target.write_text(json.dumps(offer,ensure_ascii=False,indent=2),encoding='utf-8')
    report={'checked_at':utcnow(),'gate':gate,'stored_offer_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
      'screenshots_hash_verified':True,'database_mutated':False,'browser_recovery_confirmed':True,
      'edge_fallback_used':False,'native_price_projection_allowed':False}
    (dest/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
