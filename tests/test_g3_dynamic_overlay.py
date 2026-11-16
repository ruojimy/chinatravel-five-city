"""Date scopes and estimates must not masquerade as live prices."""
from pathlib import Path
from unittest import mock
import os,sys,unittest

REPO=Path(__file__).resolve().parents[1]
profile=os.environ.get('CT_SANDBOX_TEST_PROFILE')
if not profile:raise unittest.SkipTest('set CT_SANDBOX_TEST_PROFILE to a verified profile')
sys.path.insert(0,str(REPO/'scripts'))
from g3_sandbox import configure
configure(profile)
sys.path.insert(0,str(REPO/'src/sandbox_runtime'))
import dynamic_runtime
from sandbox_adapter import Sandbox

class DynamicOverlayTests(unittest.TestCase):
    def test_date_scoped_ticket_hidden_outside_matching_dates(self):
        row={'record_id':'attraction:xian:999','city':'西安','name':'test','price':55,
             'field_validity':{'trip_start_date':'2026-11-20','trip_end_date':'2026-11-20'}}
        with mock.patch.object(dynamic_runtime,'load_snapshot',return_value={'attraction_prices':[row]}):
            with mock.patch.dict(os.environ,{'CT_TRAVEL_START_DATE':'2026-11-21','CT_TRAVEL_END_DATE':'2026-11-21'}):
                self.assertIsNone(dynamic_runtime.price_overlay(row['record_id'],'西安','test'))
            with mock.patch.dict(os.environ,{'CT_TRAVEL_START_DATE':'2026-11-20','CT_TRAVEL_END_DATE':'2026-11-20'}):
                self.assertEqual(dynamic_runtime.price_overlay(row['record_id'],'西安','test')['price'],55)
    def test_unresolved_conflict_does_not_expose_price(self):
        row={'record_id':'attraction:xian:999','city':'西安','name':'test','price':55,'conflict_unresolved':True}
        with mock.patch.object(dynamic_runtime,'load_snapshot',return_value={'attraction_prices':[row]}):
            self.assertIsNone(dynamic_runtime.price_overlay(row['record_id'],'西安','test'))
    def test_dynamic_hotel_price_replaces_estimate_not_the_other_way_round(self):
        sandbox=Sandbox('G3');path,_,rows,*_=sandbox._catalog('accommodation','西安')
        idx=next(i for i,row in enumerate(rows) if row.get('id')=='67')
        overlay={'fields':{'price':150},'field_provenance':{'price':'dated_room_occupancy_matched_source'}}
        with mock.patch.object(dynamic_runtime,'entity_overlay',return_value=overlay):
            result=sandbox._record('accommodation','西安',idx)['payload']
        self.assertEqual(result['data']['price'],150)
        self.assertEqual(result['access']['estimated_price_reference'],65.9)
        with mock.patch.object(dynamic_runtime,'entity_overlay',return_value=None):
            result=sandbox._record('accommodation','西安',idx)['payload']
        self.assertIsNone(result['data']['price'])

if __name__=='__main__':unittest.main()
