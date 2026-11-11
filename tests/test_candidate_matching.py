"""Controlled semantic/route counterexamples, not real preference accuracy."""
from pathlib import Path
import sys,unittest
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from shorttrip.candidate_matching import Demand,Evidence,CandidateMatcher,query_demands,extract_evidence
from shorttrip.preference import UserProfile
from shorttrip.visitor_tags import extract_mentions

def review(text,poi='A',rid='synthetic',route=None,licence='synthetic'):
    return extract_evidence({'review_id':rid,'poi_hint':poi,'text':text,'route':route},licence,allow_synthetic=True)

class FakeRoutes:
    def leg_templates(self,city,origin,destination,mode):
        return [SimpleNamespace(mode='walk',seconds=(20 if mode=='metro' else 0 if mode=='taxi' else 40)/60),
                SimpleNamespace(mode=mode,seconds=0.1)]

class CandidateMatchingTests(unittest.TestCase):
    def test_legacy_negation_no_positive_interest(self):
        p=UserProfile.from_query({'nature_language':'我不喜欢爬山，不想拍照，可以排队。'})
        self.assertFalse(p.interests);self.assertEqual(p.max_queue,1.)
    def test_negated_hiking_not_a_nature_ban(self):
        ds=query_demands('不喜欢爬山，喜欢自然风光')
        self.assertIn(('hiking',False),[(d.aspect,d.desired) for d in ds])
        self.assertIn(('nature',True),[(d.aspect,d.desired) for d in ds])
    def test_soft_walk_has_no_invented_hard_threshold(self):
        ds=query_demands('尽量少走路')
        self.assertTrue(any(d.relation=='minimize' and d.desired is None for d in ds))
        self.assertFalse(any(d.hard for d in ds))
    def test_daily_and_access_caps_are_distinct(self):
        ds=query_demands('每天步行不超过40分钟，每段接驳步行最多10分钟')
        self.assertEqual({(d.scope,d.aspect,d.desired) for d in ds},{('trip','daily_walk_minutes',40),('access_route','walk_minutes',10)})
    def test_transport_mention_not_good_reachability(self):
        text='There is a shuttle bus, but we waited forty minutes.'
        self.assertFalse(any(m.tag_id=='reachability' for m in extract_mentions({'review_id':'x','text':text})))
    def test_transport_hint_not_a_specific_route(self):
        ev=review('There is a shuttle bus, but we waited forty minutes.')
        self.assertTrue(ev);self.assertTrue(all(e.scope=='access_hint' for e in ev))
        m=CandidateMatcher(ev,allow_synthetic=True)
        self.assertEqual(m.score('A','station','metro',[Demand('wait_minutes',None,'access_route','minimize')],{})['decision'],'insufficient_evidence')
    def test_internal_service_does_not_become_access(self):
        self.assertTrue(all(e.scope=='internal_transport' for e in review('Inside the park the bus waited forty minutes.')))
    def test_route_origin_and_mode_are_binding(self):
        ev=review('We waited forty minutes.',route={'origin':'station','mode':'metro'})
        m=CandidateMatcher(ev,allow_synthetic=True);d=[Demand('wait_minutes',None,'access_route','minimize')]
        self.assertEqual(m.score('A','other','metro',d,{})['decision'],'insufficient_evidence')
        self.assertEqual(m.score('A','station','taxi',d,{})['decision'],'insufficient_evidence')
        self.assertGreater(m.score('A','station','metro',d,{})['score'],0)
    def test_no_licence_and_unrequested_synthetic_are_excluded(self):
        self.assertFalse(extract_evidence({'review_id':'x','poi_hint':'A','text':'Great for photos.'},'pending'))
        self.assertFalse(CandidateMatcher(review('Great for photos.')).evidence)
    def test_quotes_are_exact_substrings(self):
        text='Great for photos. The path is flat.'
        self.assertTrue(all(e.quote in text for e in review(text)))
    def test_conflicting_reviews_remain_conflict(self):
        m=CandidateMatcher(review('Not much walking.')+review('A long walk with many stairs.',rid='second'),allow_synthetic=True)
        result=m.score('A','station','metro',[Demand('walking_intensity','low')],{})
        self.assertEqual(result['checks'][0]['status'],'conflict')
    def test_reviews_cannot_certify_hard_accessibility(self):
        m=CandidateMatcher(review('No stairs.',route={'origin':'station','mode':'taxi'}),allow_synthetic=True)
        result=m.score('A','station','taxi',[Demand('stairs',False,'access_route',hard=True)],{})
        self.assertTrue(result['blocked']);self.assertEqual(result['checks'][0]['status'],'unknown_hard')
    def test_operational_hard_limit_can_pass_and_fail(self):
        m=CandidateMatcher();d=[Demand('walk_minutes',10,'access_route','le',True)]
        self.assertFalse(m.score('A','s','metro',d,{'walk_minutes':5})['blocked'])
        self.assertTrue(m.score('A','s','metro',d,{'walk_minutes':20})['blocked'])
    def test_route_review_changes_chosen_mode(self):
        ev=review('The forest has natural beauty.')+review('We waited forty minutes.',route={'origin':'s','mode':'metro'})+review('We waited 5 minutes.',rid='taxi',route={'origin':'s','mode':'taxi'})
        rows=[{'name':'A'}];q={'nature_language':'喜欢自然，尽量少等车'}
        poi=CandidateMatcher(ev,include_routes=False,allow_synthetic=True).rank_rows(rows,city='X',origin='s',env=FakeRoutes(),query=q)
        joint=CandidateMatcher(ev,include_routes=True,allow_synthetic=True).rank_rows(rows,city='X',origin='s',env=FakeRoutes(),query=q)
        self.assertEqual(poi[0]['_tagmatch_mode'],'metro');self.assertEqual(joint[0]['_tagmatch_mode'],'taxi')
    def test_poi_review_changes_candidate_order(self):
        m=CandidateMatcher(review('The forest has natural beauty.',poi='B'),allow_synthetic=True)
        rows=m.rank_rows([{'name':'A'},{'name':'B'}],city='X',origin='s',env=FakeRoutes(),query={'nature_language':'喜欢自然'})
        self.assertEqual(rows[0]['name'],'B')
    def test_no_demands_preserves_candidate_order(self):
        rows=[{'name':'B'},{'name':'A'}];m=CandidateMatcher()
        self.assertEqual(m.rank_rows(rows,city='X',origin='s',env=FakeRoutes(),query={'nature_language':'玩一天'}),rows)
    def test_full_day_cap_counts_meal_and_return_transfers(self):
        plan={'itinerary':[{'activities':[{'type':'attraction','transports':[{'mode':'walk','start_time':'09:00','end_time':'09:08'}]},
              {'type':'lunch','transports':[{'mode':'walk','start_time':'12:00','end_time':'12:18'}]},
              {'type':'train','transports':[{'mode':'walk','start_time':'17:00','end_time':'17:20'}]}]}]}
        report=CandidateMatcher().audit_plan({'nature_language':'每天步行不超过40分钟'},plan)
        self.assertFalse(report['all_hard_satisfied']);self.assertEqual(report['checks'][0]['values'],[46.])
    def test_whole_trip_and_daily_caps_are_not_equivalent(self):
        a={'activities':[{'transports':[{'mode':'walk','start_time':'09:00','end_time':'09:30'}]}]}
        plan={'itinerary':[a,a]};m=CandidateMatcher()
        self.assertTrue(m.audit_plan({'nature_language':'每天步行不超过40分钟'},plan)['all_hard_satisfied'])
        self.assertFalse(m.audit_plan({'nature_language':'全程步行不超过40分钟'},plan)['all_hard_satisfied'])
    def test_flat_terrain_does_not_prove_short_walking(self):
        ev=review('The path is flat.')
        self.assertTrue(any(e.aspect=='terrain_flat' for e in ev))
        self.assertFalse(any(e.aspect=='walking_intensity' for e in ev))
    def test_negative_flat_not_mislabeled_positive(self):
        self.assertFalse(any(e.aspect=='terrain_flat' for e in review('The path is not flat.')))
    def test_no_hiking_required_is_not_hiking_required(self):
        self.assertEqual([e.value for e in review('No hiking required.') if e.aspect=='hiking'],[False])
    def test_route_preference_ablation_still_checks_hard_limits(self):
        rows=CandidateMatcher(include_routes=False).rank_rows([{'name':'A'}],city='X',origin='s',env=FakeRoutes(),
             query={'nature_language':'每段接驳步行最多10分钟'})
        self.assertEqual(rows[0]['_tagmatch_mode'],'taxi')

if __name__=='__main__':unittest.main()
