"""Acceptance checks for the published, redacted eleven-city export."""
from pathlib import Path
import json,os,subprocess,sys,unittest
ROOT=Path(__file__).resolve().parents[1]

class PublicExportTests(unittest.TestCase):
 def test_profile_and_station_alias_in_fresh_process(self):
  code='''from pathlib import Path\nimport sys\nr=Path.cwd();sys.path[:0]=[str(r/'scripts'),str(r/'src/sandbox_runtime'),str(r/'ShortTrip-upstream')]\nfrom g3_sandbox import configure\nconfigure(r/'data/sandbox_profiles/xian_n16v2')\nfrom chinatravel.environment.station_aliases import compare\nassert compare(r/'ShortTrip-upstream','南京','南京南','南京南站',station_context=True)['state']=='pass'\nassert compare(r/'ShortTrip-upstream','南京','南京','南京南站',station_context=True)['state']!='pass'\n'''
  p=subprocess.run([sys.executable,'-X','utf8','-c',code],cwd=ROOT,capture_output=True,text=True,encoding='utf8')
  self.assertEqual(p.returncode,0,p.stderr)
 def test_train_summary_is_reference_and_scoped(self):
  d=json.loads((ROOT/'data/observations/train_20261116/xian_11city_reference.json').read_text(encoding='utf8'))
  self.assertEqual((len(d['directions']),len(d['accepted']),len(d['excluded'])),(20,776,4))
  self.assertTrue(all(x['source_response'] is None for x in d['accepted']))
  self.assertTrue(all('西安' in (x['from_city'],x['to_city']) for x in d['accepted']))
 def test_flight_pages_are_date_scoped(self):
  sys.path.insert(0,str(ROOT/'src/sandbox_runtime'))
  from flight_reference import lookup
  path=ROOT/'data/observations/flight_20261116'
  self.assertEqual(len(lookup(path,'西安','北京','2026-11-16')),86)
  self.assertEqual(lookup(path,'西安','北京','2026-11-17'),[])
if __name__=='__main__':unittest.main()
