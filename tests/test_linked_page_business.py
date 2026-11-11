import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from shorttrip.linked_page_business import extract
class Linked(unittest.TestCase):
 def target(self,kind='restaurant'):return {'name':'餐厅','kind':kind,'longitude_wgs84':118,'latitude_wgs84':24}
 def venue(self,**kwargs):return {'data':{'@type':'Restaurant','name':'餐厅','geo':{'longitude':118,'latitude':24},**kwargs}}
 def test_explicit_cuisine(self):self.assertEqual(extract(self.target(),[self.venue(servesCuisine='粤菜')])['native_values']['cuisine'],'粤菜')
 def test_nearby_wrong_name(self):self.assertFalse(extract(self.target(),[self.venue(name='其他餐厅')])['matched'])
 def test_far_same_name(self):self.assertFalse(extract(self.target(),[self.venue(geo={'longitude':119,'latitude':24})])['matched'])
 def test_name_alone_not_enough(self):self.assertFalse(extract(self.target(),[self.venue(geo={})])['matched'])
 def test_malformed_schema_not_crash(self):self.assertFalse(extract(self.target(),[self.venue(**{'@type':None}),self.venue(geo='bad')])['matched'])
 def test_ambiguous(self):self.assertFalse(extract(self.target(),[self.venue(),self.venue()])['matched'])
 def test_dollars_are_not_average(self):self.assertNotIn('price',extract(self.target(),[self.venue(priceRange='$$$')])['native_values'])
 def test_explicit_average(self):self.assertEqual(extract(self.target(),[self.venue(priceRange='人均￥120元')])['native_values']['price'],120)
 def test_fullweek(self):self.assertEqual(extract(self.target(),[self.venue(openingHours='Mo-Su 09:00-17:00')])['native_values']['endtime'],'17:00')
 def test_split_not_flattened(self):self.assertNotIn('opentime',extract(self.target(),[self.venue(openingHours=['Mo-Su 09:00-12:00','Mo-Su 14:00-17:00'])])['native_values'])
 def test_overnight_not_flattened(self):self.assertNotIn('opentime',extract(self.target(),[self.venue(openingHours='Mo-Su 09:00-02:00')])['native_values'])
 def test_hotel_price_or_rooms_not_beds(self):self.assertEqual(extract(self.target('accommodation'),[self.venue(**{'@type':'Hotel','priceRange':'人均￥120元','numberOfRooms':2})])['native_values'],{})
 def test_free_attraction_only(self):self.assertEqual(extract(self.target('attraction'),[self.venue(**{'@type':'Museum','isAccessibleForFree':True})])['native_values']['price'],0)
if __name__=='__main__':unittest.main()
