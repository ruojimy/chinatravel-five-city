import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from shorttrip.operator_room_dom import accor_rooms
def card(name,bed,occupancy=3):
 return ('<h1>Hotel</h1><p>GPS : 30.100, 110.100</p><div class="card__infos"><h3 class="card__title">'+name+'</h3>'
  '<p>'+str(occupancy)+' guests maximum</p><li class="card__details"><span class="sr-only">床上用品</span><span class="ellipsis">'+bed+'</span></li></div>').encode()
class RoomDOMTests(unittest.TestCase):
 def test_occupancy_and_area_not_beds(self):
  p=accor_rooms(card('高级大床房','1 x 特大床',4));self.assertEqual(p['room_configurations'][0]['bed_count'],1)
 def test_two_single_beds(self):self.assertEqual(accor_rooms(card('双床房','2 x 单人床'))['room_configurations'][0]['bed_count'],2)
 def test_alternatives_not_added(self):self.assertIsNone(accor_rooms(card('客房','1 x 特大床 或者 2 x 单人床'))['room_configurations'][0]['bed_count'])
 def test_missing_counts_not_default_one(self):self.assertIsNone(accor_rooms(card('家庭房','x 特大床 和 x 双人沙发床'))['room_configurations'][0]['bed_count'])
 def test_mixed_missing_count_not_partially_projected(self):self.assertIsNone(accor_rooms(card('家庭房','1 x 特大床 和 x 双人沙发床'))['room_configurations'][0]['bed_count'])
 def test_connecting_product_keeps_room_count_unknown(self):self.assertIsNone(accor_rooms(card('家庭连通套房','2 x 特大床'))['room_configurations'][0]['room_count'])
 def test_scripts_and_prices_not_projected(self):
  p=accor_rooms(card('大床房','1 x 特大床')+b'<script>hotelPrice=200</script><p>Breakfast CNY50</p>');self.assertFalse(p['price_projection_allowed']);self.assertIsNone(p['room_configurations'][0]['price'])
 def test_missing_card_bed_not_inferred_from_title(self):self.assertEqual(accor_rooms(b'<h3 class="card__title">Two single beds</h3>')['room_configurations'],[])
if __name__=='__main__':unittest.main()
