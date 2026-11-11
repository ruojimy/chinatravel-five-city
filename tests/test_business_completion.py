import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_completion import validate_room_offer,api_restaurant,complete_native,validate_operator_field,details
from shorttrip.expansion_contract import validate_record
def offer():
    return {'offer_id':'x','entity_id':'x','room_type_name':'双床','bed_count':2,'rooms_reserved':1,
      'adults':2,'children':0,'checkin':'2026-10-24','checkout':'2026-10-25','nights':1,'currency':'CNY',
      'room_type_id':'twin','rate_plan_id':'flex','rate_plan_name':'弹性','membership_required':False,
      'price_breakdown':{'room_base':548,'service_charge':54.8,'tax_and_government_charge':36.17,'displayed_stay_total':638.97},
      'observed_at':'2026-10-22T11:00:00Z','retrieved_at':'2026-10-22T11:00:00Z','valid_until':'2026-10-22T11:05:00Z',
      'source_id':'operator','source_url':'https://example.org','screenshot_evidence':[{'sha256':'a'*64}]}
class CompletionTests(unittest.TestCase):
    def test_price_matches_room_night_context(self):
        self.assertEqual(validate_room_offer(offer())['native_price_per_room_night'],638.97)
    def test_expired_price_is_not_fresh(self):
        self.assertFalse(validate_room_offer(offer(),now='2026-10-22T11:06:00Z')['current_quote_fresh'])
    def test_ttl_cannot_be_extended_on_import(self):
        o=offer();o['valid_until']='2026-10-23T11:00:00Z';self.assertFalse(validate_room_offer(o)['ok'])
    def test_membership_not_joined_to_public_rate(self):
        o=offer();o['membership_required']=True;self.assertIsNone(validate_room_offer(o)['native_price_per_room_night'])
    def test_components_must_sum_to_total(self):
        o=offer();o['price_breakdown']['displayed_stay_total']=567;self.assertFalse(validate_room_offer(o)['ok'])
    def test_conditional_price_without_components_is_not_native(self):
        o=offer();o['price_breakdown']={'displayed_stay_total':1553};self.assertTrue(validate_room_offer(o)['ok'])
        self.assertIsNone(validate_room_offer(o)['native_price_per_room_night'])
    def test_room_counts_and_beds_not_conflated(self):
        o=offer();o['bed_count']=0;self.assertFalse(validate_room_offer(o)['ok'])
    def test_stay_dates_consistent(self):
        o=offer();o['checkout']='2026-10-26';self.assertFalse(validate_room_offer(o)['ok'])
    def restaurant(self,**b):
        return api_restaurant({'id':'A','name':'测试餐厅','type':'餐饮服务;中餐厅;闽菜','cityname':'厦门市',
          'location':'118.12,24.48','business':{'cost':'68.00','keytag':'闽菜','opentime_today':'11:00-21:00',**b}},
          {'endpoint':'https://restapi.amap.com/v5/place/text','retrieved_at':'2026-10-22T11:00:00Z'})
    def test_concrete_restaurant_fields_load_but_unknown_clock_not_renewed(self):
        r=self.restaurant();gate=validate_record(r,now='2026-10-22T11:00:00Z')
        self.assertTrue(gate['discovery_ok'],gate);self.assertTrue(complete_native(r));self.assertFalse(gate['planning_ready'])
        self.assertEqual(r['data']['price'],68);self.assertIsNone(r['observed_at'])
    def test_hotel_cost_is_not_restaurant_price(self):
        self.assertIsNone(api_restaurant({'type':'住宿服务;宾馆酒店','business':{'cost':'500'}},{}))
    def test_split_hours_not_one_continuous_native_window(self):
        r=self.restaurant(opentime_today='11:00-14:00 17:00-21:00');self.assertIsNone(r['data']['opentime'])
        self.assertIn('11:00-14:00',r['business_rules']['opentime_today'])
    def test_24_hour_endpoint_not_invalid_24_clock(self):
        r=self.restaurant(opentime_today='08:00-24:00');self.assertTrue(validate_record(r)['discovery_ok'])
        self.assertIsNone(r['data']['endtime'])
    def test_optional_english_hotel_name_not_required_for_business_completeness(self):
        self.assertTrue(complete_native({'kind':'accommodation','data':{'id':1,'name':'酒店','hotelname_en':None,
             'featurehoteltype':'室外泳池','lat':24.48,'lon':118.12,'price':638.97,'numbed':2}}))
    def test_operator_field_requires_scope_clock_and_raw_digest(self):
        self.assertFalse(validate_operator_field({'field':'price','value':120})['ok'])
if __name__=='__main__':unittest.main(verbosity=2)
