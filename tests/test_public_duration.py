import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from shorttrip.public_duration import extract_public_duration,verify_public_duration

class PublicDuration(unittest.TestCase):
 def fixture(self,duration='1-2小时'):
  poi={'poiName':'测试景点','districtName':'天津','address':'测试路1号','businessId':7,'poiId':99,
       'openInfo':{'playSpendTime':duration,'openStatus':'未开园','needTicket':False,'travelDuration':'10分钟'}}
  data={'props':{'pageProps':{'initialState':{'poiDetail':poi}}}}
  raw=('<h1>测试景点</h1><script id="__NEXT_DATA__" type="application/json">'+json.dumps(data,ensure_ascii=False)+'</script>').encode()
  return raw,{'name':'测试景点','city':'天津'},'https://you.ctrip.com/sight/tianjin154/7.html'
 def test_only_explicit_visit_hours_project_and_dynamic_flags_do_not(self):
  raw,record,url=self.fixture();p=extract_public_duration(raw)
  self.assertEqual(verify_public_duration(raw,p,record,url),{'recommendmintime':1,'recommendmaxtime':2})
  self.assertNotIn('openStatus',p);self.assertNotIn('needTicket',p);self.assertNotIn('travelDuration',p)
 def test_half_day_days_reversed_zero_or_over_24_do_not_become_hours(self):
  for text in ('半天','1天','2-1小时','0-2小时','24-48小时'):
   raw,record,url=self.fixture(text);self.assertEqual(verify_public_duration(raw,extract_public_duration(raw),record,url),{})
 def test_wrong_branch_city_provider_namespace_or_projection_rejected(self):
  raw,record,url=self.fixture();p=extract_public_duration(raw)
  for other in ({'name':'另一个景点','city':'天津'},{'name':record['name'],'city':'北京'}):
   with self.assertRaises(ValueError):verify_public_duration(raw,p,other,url)
  with self.assertRaises(ValueError):verify_public_duration(raw,p,record,url.replace('/7.html','/99.html'))
  changed=copy.deepcopy(p);changed['playSpendTime']='10小时'
  with self.assertRaises(ValueError):verify_public_duration(raw,changed,record,url)
 def test_rendered_heading_must_match_same_public_duration_object(self):
  raw,record,url=self.fixture();raw=raw.replace('<h1>测试景点</h1>'.encode(),'<h1>其他景点</h1>'.encode())
  with self.assertRaisesRegex(ValueError,'title'):extract_public_duration(raw)
if __name__=='__main__':unittest.main()
