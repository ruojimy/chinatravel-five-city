import json,sqlite3,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from shorttrip.bulk_business import BulkQueue,gaps,match_business
from shorttrip.scoped_business import matching_aliases,provider_aliases
from shorttrip.dynamic.opendata import gcj02_to_wgs84

class Bulk(unittest.TestCase):
 def target(self,kind='attraction'):
  lon,lat=gcj02_to_wgs84(118,24)
  return {'kind':kind,'city':'厦门','name':'植物园','longitude_wgs84':lon,'latitude_wgs84':lat}
 def poi(self,**kwargs):
  return {'id':'B1','name':'植物园','cityname':'厦门市','type':'风景名胜;植物园','location':'118,24',**kwargs}
 def test_traditional_normalization(self):self.assertTrue(matching_aliases('植物園')&matching_aliases('植物园'))
 def test_explicit_bilingual_label(self):self.assertTrue(matching_aliases('Pizza Hut 必胜客')&matching_aliases('必胜客'))
 def test_explicit_provider_alias(self):self.assertTrue(matching_aliases('Botanical Garden')&provider_aliases(self.poi(business={'alias':'Botanical Garden'})))
 def test_no_branch_dropping(self):self.assertFalse(matching_aliases('饭店(一店)')&matching_aliases('饭店(二店)'))
 def test_same_entity_candidate(self):self.assertTrue(match_business(self.target(),[self.poi()])['matched'])
 def test_not_identity_certificate(self):self.assertFalse(match_business(self.target(),[self.poi()])['entity_verified'])
 def test_wrong_city(self):self.assertFalse(match_business(self.target(),[self.poi(cityname='泉州市')])['matched'])
 def test_wrong_type(self):self.assertFalse(match_business(self.target(),[self.poi(type='住宿服务;宾馆酒店')])['matched'])
 def test_museum_supported(self):self.assertTrue(match_business(self.target(),[self.poi(type='科教文化服务;博物馆',typecode='140100')])['matched'])
 def test_school_not_attraction(self):self.assertFalse(match_business(self.target(),[self.poi(type='科教文化服务;学校',typecode='141200')])['matched'])
 def test_ambiguous(self):self.assertFalse(match_business(self.target(),[self.poi(),self.poi(id='B2')])['matched'])
 def test_far_branch(self):self.assertFalse(match_business(self.target(),[self.poi(location='119,25')])['matched'])
 def test_no_price_from_hotel_cost(self):
  x={'kind':'accommodation','data':{'price':500,'numbed':None}}
  self.assertEqual(gaps(x),['dated_room_price_reference','room_type','bed_count'])
 def test_scoped_hotel_room_label_is_a_reference_not_price_or_beds(self):
  x={'kind':'accommodation','data':{'price':None,'numbed':None},'operator_assertions':[{'field':'room_type_name','value':'Superior'}]}
  self.assertEqual(gaps(x),['dated_room_price_reference','bed_count'])
 def test_structured_split_counts_hours(self):
  x={'kind':'restaurant','data':{'price':None,'cuisine':None},'today_hours_structured':{'segments':[{}]}}
  self.assertEqual(gaps(x),['average_price','cuisine'])
 def test_provider_pause_persists(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'q.sqlite';q=BulkQueue(p);q.pause('quota');q.close();q=BulkQueue(p)
   with self.assertRaises(RuntimeError):q.assert_provider_ready()
   q.close()
 def test_pending_job_claim_is_durable(self):
  with tempfile.TemporaryDirectory() as tmp:
   q=BulkQueue(Path(tmp)/'q.sqlite')
   with q.db:
    q.db.execute('INSERT INTO entities VALUES(?,?,?,?,?,?,?)',('x','restaurant','厦门','店','[]',1,'{}'))
    q.db.execute('INSERT INTO jobs(id,entity_id,adapter,status,priority) VALUES(?,?,?,?,?)',('x|amap','x','amap_place','pending',1))
   job=q.claim_next();self.assertEqual(job['entity_id'],'x');self.assertIsNone(q.claim_next())
   self.assertEqual(q.db.execute('SELECT attempts FROM jobs').fetchone()[0],1);q.close()
if __name__=='__main__':unittest.main()
