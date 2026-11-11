import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'ChinaTravel')]
from shorttrip.intent_planner import IntentPlanner
from shorttrip.intent_planner_v2 import intent_penalty
from shorttrip.planner import SkeletonPlanner,PlanResult


class IntentTests(unittest.TestCase):
    def query(self):return {'uid':'q','start_city':'上海','target_city':'杭州','days':2,'people_number':2,'nature_language':'两人去杭州','hard_logic_py':['FORBIDDEN_ORACLE_MARKER'],'private_label':'secret'}
    def plan(self):return {'people_number':2,'start_city':'上海','target_city':'杭州','itinerary':[{'day':1,'activities':[{'type':'attraction','position':'A','cost':20,'price':10,'transports':[]},{'type':'accommodation','position':'H','rooms':2,'room_type':1,'cost':200,'price':100,'transports':[]}]}]}
    def test_hidden_fields_do_not_enter_planning_call(self):
        seen=[]
        def fake(obj,q,deep_check):seen.append(q);return PlanResult(None,None)
        with patch.object(SkeletonPlanner,'build',fake):IntentPlanner(object(),{}).build_proposal(self.query())
        self.assertNotIn('hard_logic_py',seen[0]);self.assertNotIn('private_label',seen[0])
    def test_explicit_requested_rooms_recomputes_actual_row_cost(self):
        with patch.object(SkeletonPlanner,'build',return_value=PlanResult(self.plan(),None)):
            p=IntentPlanner(object(),{'rooms':1}).build_proposal(self.query()).plan
        a=p['itinerary'][0]['activities'][1];self.assertEqual(a['rooms'],1);self.assertEqual(a['cost'],100)
    def test_airplane_record_keeps_airplane_schema(self):
        obj=IntentPlanner(object(),{});r={'_p23_mode':'airplane','From':'上海虹桥机场','To':'杭州萧山机场','BeginTime':'08:00','EndTime':'09:00','Cost':300,'FlightID':'X1'}
        a=obj._intercity_activity(r,'train',2,[])
        self.assertEqual(a['type'],'airplane');self.assertEqual(a['FlightID'],'X1');self.assertEqual(a['cost'],600)
    def test_missing_named_requirement_has_large_penalty(self):
        self.assertGreater(intent_penalty(self.plan(),{'required_attractions':['missing']}),9999)
    def test_budget_cap_penalty_is_not_just_price_preference(self):
        self.assertGreater(intent_penalty(self.plan(),{'budget':100}),1000)
        self.assertLess(intent_penalty(self.plan(),{'budget':1000}),1)
    def test_component_budget_does_not_include_other_components(self):
        self.assertLess(intent_penalty(self.plan(),{'attraction_budget':20}),1)
        self.assertGreater(intent_penalty(self.plan(),{'hotel_budget':100}),1000)
    def test_count_and_room_constraints_are_distinct(self):
        self.assertGreater(intent_penalty(self.plan(),{'attraction_count':3}),3999)
        self.assertGreater(intent_penalty(self.plan(),{'rooms':1}),4999)

if __name__=='__main__':unittest.main(verbosity=2)
