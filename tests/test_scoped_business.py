import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from shorttrip.scoped_business import today_hours,validate_hours,qunar_fields,match_target

class Hours(unittest.TestCase):
 def test_lunch_gap_not_open(self):
  x=today_hours('11:00-14:00 17:00-22:00');self.assertEqual(len(x['segments']),2);self.assertEqual(x['native_values'],{});self.assertTrue(validate_hours(x)['ok'])
 def test_overnight_needs_offset(self):
  x=today_hours('10:00-02:00');self.assertEqual(x['segments'][0]['end_day_offset'],1);self.assertEqual(x['native_values'],{})
 def test_midnight_is_not_2359(self):
  x=today_hours('09:00-24:00');self.assertEqual(x['segments'][0]['end_minute'],1440);self.assertEqual(x['native_values'],{})
 def test_all_day_is_not_closed_zero_pair(self):
  x=today_hours('24小时营业');self.assertEqual(x['segments'][0]['end_minute'],1440);self.assertEqual(x['native_values'],{})
 def test_duplicate_same_interval(self):self.assertEqual(today_hours('06:00-21:00 06:00-21:00')['native_values']['endtime'],'21:00')
 def test_simple_interval(self):self.assertEqual(today_hours('9:00-17:30')['native_values'],{'opentime':'09:00','endtime':'17:30'})
 def test_season_not_assumed_today(self):self.assertEqual(today_hours('5月1日至10月1日 09:00-17:30')['segments'],[])
 def test_invalid_minute(self):self.assertFalse(today_hours('09:00-24:01')['segments'])
 def test_invalid_schema(self):self.assertFalse(validate_hours({'raw':'x','scope':'provider_today_only','segments':[{'start_minute':True,'end_minute':60,'end_day_offset':0}]})['ok'])
 def test_new_structures_need_full_provenance(self):self.assertFalse(validate_hours(today_hours('09:00-17:00'),require_provenance=True)['ok'])
 def test_tampered_lunch_window_rejected(self):
  x=today_hours('11:00-14:00 17:00-22:00');x['native_values']={'opentime':'11:00','endtime':'22:00'};self.assertFalse(validate_hours(x)['ok'])
 def test_tampered_segment_rejected(self):
  x=today_hours('09:00-17:00');x['segments'][0]['end_minute']=1200;self.assertFalse(validate_hours(x)['ok'])

class Scope(unittest.TestCase):
 def test_missing_provider_id_is_quarantined(self):
  x=match_target({'city':'厦门','name':'店','longitude_wgs84':118,'latitude_wgs84':24},[{'name':'店','location':'118,24'}]);self.assertFalse(x['matched']);self.assertEqual(x['rejected'][0]['reason'],'provider_entity_id_or_name_missing')
 def test_review_free_does_not_set_admission(self):
  x=qunar_fields('<title>2026海滩门票,城市</title><li class="list"><span class="item_tit">开放时间：</span><span class="item_cout">全年 08:00-17:00</span></li><div class="review">门票免费</div><span class="ticket-price">¥0起</span>')
  self.assertNotIn('price',x['native_values']);self.assertTrue(x['ticket_options'][0]['lower_bound'])
 def test_review_hours_not_official_field(self):self.assertEqual(qunar_fields('<title>2026公园门票,城市</title><div>开放时间09:00-17:00</div>')['native_values'],{})
 def test_same_name_other_city_rejected(self):
  x=match_target({'city':'厦门','name':'同名店','longitude_wgs84':118,'latitude_wgs84':24},[{'id':'1','cityname':'泉州市','name':'同名店','location':'118,24','type':'餐饮服务;中餐厅;中餐厅'}]);self.assertFalse(x['matched'])
 def test_same_name_far_branch_rejected(self):
  x=match_target({'city':'厦门','name':'同名店','longitude_wgs84':118,'latitude_wgs84':24},[{'id':'1','cityname':'厦门市','name':'同名店','location':'118.2,24','type':'餐饮服务;中餐厅;中餐厅'}]);self.assertFalse(x['matched'])
 def test_hotel_result_not_restaurant(self):
  x=match_target({'city':'厦门','name':'酒店餐厅','longitude_wgs84':118,'latitude_wgs84':24},[{'id':'1','cityname':'厦门市','name':'酒店餐厅','location':'118,24','type':'住宿服务;宾馆酒店'}]);self.assertFalse(x['matched'])

if __name__=='__main__':unittest.main()
