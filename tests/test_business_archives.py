import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from shorttrip.business_archives import *
class ArchiveTests(unittest.TestCase):
    def test_free_is_explicit(self):
        self.assertEqual(parse_ticket('免费')[0],{'price':0.0});self.assertEqual(parse_ticket('')[0],{})
    def test_plain_price(self):self.assertEqual(parse_ticket('120元')[0],{'price':120.0})
    def test_starting_package_price_not_ticket(self):
        native,options,flags=parse_ticket("{'儿童票+索道': ['¥80起'], '成人门票': ['¥120']}")
        self.assertEqual(native,{});self.assertEqual(len(options),2);self.assertTrue(options[0]['lower_bound'])
    def test_literal_eval_does_not_execute(self):
        self.assertEqual(parse_ticket("{'x': __import__('os').getcwd()}")[0],{})
    def test_simple_hours(self):self.assertEqual(parse_hours('全年 08:30-17:30')[0],{'opentime':'08:30','endtime':'17:30'})
    def test_split_or_season_hours_not_collapsed(self):
        self.assertEqual(parse_hours('08:30-12:00 14:00-17:30')[0],{})
        self.assertEqual(parse_hours('周一闭馆；08:30-17:30')[0],{})
    def test_bad_hours(self):self.assertEqual(parse_hours('25:00-26:00')[0],{})
    def test_duration_range(self):self.assertEqual(parse_duration('建议游览时间：1小时 - 2小时')[0],{'recommendmintime':1.0,'recommendmaxtime':2.0})
    def test_days_not_invented_hours(self):self.assertEqual(parse_duration('1天')[0],{})
    def test_inverted_duration_rejected(self):self.assertEqual(parse_duration('3小时-1小时')[0],{})
    def test_english_suffix_alias_only(self):
        self.assertIn(normalize_name('西岛'),name_aliases('西岛West Island'))
        self.assertNotIn(normalize_name('西岛'),name_aliases('西岛公园'))
if __name__=='__main__':unittest.main(verbosity=2)
