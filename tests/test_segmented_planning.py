from __future__ import annotations
import unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
PACKAGE=ROOT/'chinatravel-five-city-luna-20261115'
PROFILE=ROOT/'output/xiamen_source_recovery_20261117/sandbox_segments_candidate_v2'
sys.path.insert(0,str(PACKAGE/'scripts'))
from g3_sandbox12_xiamen import configure
configure(PROFILE)
sys.path.insert(0,str(PROFILE/'engine'))
from shorttrip.opening_hours import earliest_visit, fits
from shorttrip.plan import DayBuilder
from shorttrip.planner import _window_allows

ROW={'name':'分段测试点','opentime':'17:00','endtime':'22:00','price':80,
     'opening_segments_json':'[[660,840],[1020,1320]]'}

class NoTravel:
    def best_mode(self,*args):return None

class SegmentedPlanning(unittest.TestCase):
    def test_gap_not_open_and_wait_for_next(self):
        self.assertTrue(fits(ROW,690,60))
        self.assertFalse(fits(ROW,900,60))
        self.assertEqual(earliest_visit(ROW,900,60,1320),(1020,1080))
        self.assertFalse(_window_allows(ROW,900,60))
    def test_actual_day_builder_uses_each_shift(self):
        b=DayBuilder(NoTravel(),'厦门',1,0);b.set_start('11:30',ROW['name'])
        self.assertTrue(b.add_meal('lunch',ROW));self.assertEqual(b.time,'12:30')
        b.set_start('15:00',ROW['name'])
        self.assertTrue(b.add_meal('dinner',ROW));self.assertEqual(b.activities[-1]['start_time'],'17:00')
        b.set_start('22:00',ROW['name']);self.assertFalse(b.add_meal('dinner',ROW))
    def test_invalid_segments_fail_closed(self):
        bad=dict(ROW,opening_segments_json='invalid')
        self.assertFalse(_window_allows(bad,900,60))
        b=DayBuilder(NoTravel(),'厦门',1,0);b.set_start('15:00',ROW['name'])
        self.assertFalse(b.add_meal('dinner',bad))
    def test_legacy_continuous_and_overnight(self):
        self.assertTrue(fits({'opentime':'09:00','endtime':'18:00'},600,60))
        self.assertTrue(fits({'opentime':'20:00','endtime':'02:00'},1260,60))

if __name__=='__main__':unittest.main()
