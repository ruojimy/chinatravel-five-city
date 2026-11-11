"""Invariant tests: clocks, attribution, context, conflicts, budgets, TAG recall."""
from pathlib import Path
import copy,hashlib,json,sys,tempfile,unittest
from datetime import datetime,timedelta,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.freshness import (fresh_state,check_claim,reconcile,uncertainty_question,user_decision,field_policy)
from shorttrip.travel_catalog import TravelCatalog,annotate_dataset,static_tags,preflight,digest_file
from shorttrip.candidate_matching import Demand
from shorttrip.live_amap import LiveAmapClient,LiveAmapError

NOW='2026-10-22T09:00:00+00:00'
REG={
 'a':{'authority':'primary_operator','independence_group':'owner','supports':['theme','opening_hours'],'allowed_hosts':['official.example']},
 'b':{'authority':'structured_provider','independence_group':'independent','supports':['theme','opening_hours']},
 'mirror':{'authority':'structured_provider','independence_group':'owner','supports':['theme']},
 'amap':{'authority':'official_api','independence_group':'amap','supports':['route_duration','route_fare','weather_now','weather_forecast'],'allowed_hosts':['restapi.amap.com']},
}
def claim(source='a',value=True,field='theme',**kw):
    raw=json.dumps({'value':value},ensure_ascii=False)
    return {'claim_id':source+str(value),'entity_id':'poi:1','entity_verified':True,'field':field,
      'source_id':source,'source_url':'https://restapi.amap.com/api' if source=='amap' else 'https://official.example/item',
      'value':value,'raw_text':raw,'quote':raw,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),
      'licence_status':'allowed','extraction_verified':True,'observed_at':'2026-10-22T08:55:00+00:00',
      'retrieved_at':'2026-10-22T08:59:00+00:00','context':{},**kw}

class FreshnessTests(unittest.TestCase):
    def test_import_does_not_renew_missing_source_clock(self):
        r={'catalogued_at':NOW,'retrieved_at':NOW,'valid_until':'2027-01-01T00:00:00Z'}
        self.assertIn('unknown_source_time',fresh_state(r,'theme',now=NOW)['reasons'])
    def test_fetch_does_not_renew_expired_observation(self):
        r=claim('amap',field='weather_now',observed_at='2026-10-22T08:40:00Z',retrieved_at=NOW)
        self.assertIn('expired',fresh_state(r,'weather_now',now=NOW)['reasons'])
    def test_expiry_boundary_is_not_fresh(self):
        r=claim(observed_at='2026-10-22T08:45:00Z')
        self.assertIn('expired',fresh_state(r,'weather_now',now=NOW)['reasons'])
    def test_future_source_time_rejected(self):
        self.assertIn('future_source_time',fresh_state(claim(observed_at='2026-10-23T09:00:00Z'),'theme',now=NOW)['reasons'])
    def test_timestamp_without_timezone_not_guessed(self):
        self.assertIn('unknown_source_time',fresh_state(claim(observed_at='2026-10-22 08:59:00'),'theme',now=NOW)['reasons'])
    def test_context_route_departure_must_match(self):
        c=claim('amap',20,'route_duration',unit='minutes',context={'origin':'a','destination':'b','mode':'metro','coord_system':'GCJ02','departure_at':NOW})
        context={**c['context'],'departure_at':'2026-10-23T09:00:00Z'}
        self.assertIn('context_mismatch:departure_at',check_claim(c,'route_duration',REG,now=NOW,context=context)['reasons'])
    def test_forecast_outside_coverage_is_not_current_weather(self):
        c=claim('amap',{},'weather_forecast',context={'adcode':'330100','travel_date':'2026-11-01'},coverage_dates=['2026-10-23'])
        self.assertIn('outside_forecast_horizon',fresh_state(c,'weather_forecast',now=NOW,context=c['context'])['reasons'])
    def test_source_host_must_match_registry(self):
        self.assertIn('source_host_mismatch',check_claim(claim(source_url='https://fake.example/'),'theme',REG,now=NOW)['reasons'])
    def test_high_authority_cannot_replace_unsupported_field(self):
        self.assertIn('source_not_authoritative_for_field',check_claim(claim(field='accessibility'),'accessibility',REG,now=NOW)['reasons'])
    def test_quote_and_digest_both_checked(self):
        gate=check_claim(claim(quote='not there',raw_sha256='bad'),'theme',REG,now=NOW)
        self.assertIn('unsupported_quote',gate['reasons']);self.assertIn('raw_digest_mismatch',gate['reasons'])
    def test_entity_unverified_is_not_fact(self):
        self.assertFalse(check_claim(claim(entity_verified=False),'theme',REG,now=NOW)['usable'])
    def test_same_owner_mirror_not_independent(self):
        self.assertEqual(reconcile([claim(),claim('mirror')],'theme',REG,now=NOW)['status'],'single_source')
    def test_independent_support_with_primary_corroborates(self):
        self.assertEqual(reconcile([claim(),claim('b')],'theme',REG,now=NOW)['status'],'corroborated')
    def test_conflict_keeps_unknown_value_and_asks(self):
        verdict=reconcile([claim(),claim('b',False)],'theme',REG,now=NOW)
        self.assertEqual(verdict['status'],'conflict');self.assertIsNone(verdict['value']);self.assertTrue(verdict['needs_user_confirmation'])
    def test_different_entity_not_fused(self):
        result=reconcile([claim(),claim('b',entity_id='poi:2')],'theme',REG,now=NOW)
        self.assertEqual(result['status'],'conflict')
    def test_older_same_source_observation_superseded_without_erasing_history(self):
        old=claim(value=False,observed_at='2026-10-22T08:00:00Z')
        result=reconcile([old,claim()],'theme',REG,now=NOW)
        self.assertEqual(result['status'],'single_source');self.assertTrue(result['value']);self.assertEqual(len(result['checks']),2)
    def test_user_confirmation_does_not_turn_conflict_into_true(self):
        v=reconcile([claim(),claim('b',False)],'theme',REG,now=NOW)
        q=uncertainty_question('poi:1','theme',v);d=user_decision(q,'accept_labelled_uncertainty',at=NOW)
        self.assertEqual(d['evidence_status_after'],'conflict');self.assertFalse(d['hard_constraints_certified'])
        self.assertEqual({c['value'] for c in q['checks']},{True,False})
        self.assertTrue(all(c['source_url'] and c['observed_at'] for c in q['checks']))
    def test_non_amap_route_time_cannot_pass(self):
        self.assertIn('amap_api_required',check_claim(claim(value=12,field='route_duration',unit='minutes'),'route_duration',REG,now=NOW)['reasons'])
    def test_units_and_nonfinite_route_time_rejected(self):
        r=claim('amap',float('inf'),'route_duration',unit='seconds')
        reasons=check_claim(r,'route_duration',REG,now=NOW)['reasons']
        self.assertIn('invalid_numeric_value',reasons);self.assertIn('invalid_unit',reasons)
    def test_price_configuration_not_inventory(self):
        self.assertEqual(field_policy('price','accommodation'),'dynamic_price')
        self.assertEqual(field_policy('numbed','accommodation'),'room_configuration')
        self.assertEqual(field_policy('position','metro_station'),'coordinates')
    def test_applicability_date_checked_in_addition_to_ttl(self):
        c=claim(field='opening_hours',context={'travel_date':'2026-10-23'},applies_until='2026-10-22')
        self.assertIn('after_applicability_window',fresh_state(c,'opening_hours',now=NOW,context=c['context'])['reasons'])
    def test_provider_estimate_is_never_a_guaranteed_hard_fact(self):
        context={'origin':'a','destination':'b','coord_system':'GCJ02','mode':'metro','departure_at':NOW}
        c=claim('amap',12,'route_duration',unit='minutes',context=context)
        verdict=reconcile([c],'route_duration',REG,now=NOW,context=context)
        self.assertTrue(verdict['usable_as_labelled_estimate']);self.assertFalse(verdict['usable_as_hard_fact'])
    def test_wrong_field_cannot_reuse_trusted_claim(self):
        self.assertIn('wrong_field',check_claim(claim(),'opening_hours',REG,now=NOW)['reasons'])
    def test_upstream_unknown_not_counted_as_independent(self):
        registry=copy.deepcopy(REG);registry['amap']['field_independence_groups']={'weather_now':None}
        c=claim('amap',{},'weather_now',context={'adcode':'330100'})
        result=reconcile([c],'weather_now',registry,now=NOW,context=c['context'])
        self.assertEqual(result['independent_source_groups'],[])
    def test_unknown_context_placeholders_cannot_pass(self):
        c=claim('amap',{},'weather_now',context={'adcode':None})
        self.assertIn('context_mismatch:adcode',check_claim(c,'weather_now',REG,now=NOW,context={'adcode':None})['reasons'])
        self.assertIn('missing_request_context',check_claim(c,'weather_now',REG,now=NOW)['reasons'])
    def test_missing_retrieval_clock_cannot_pass(self):
        self.assertIn('unknown_retrieval_time',check_claim(claim(retrieved_at=None),'theme',REG,now=NOW)['reasons'])

class AdapterTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
    def client(self,data,budget=1):return LiveAmapClient(self.tmp.name,key='TEST-SECRET',budget=budget,transport=lambda u,p:copy.deepcopy(data))
    def test_budget_failure_stops_without_rotation_and_safe_logs(self):
        c=self.client({'status':'0','infocode':'10003'})
        with self.assertRaises(LiveAmapError):c.weather('330100')
        with self.assertRaises(LiveAmapError):c.weather('330100')
        self.assertEqual(c.spent,1);self.assertNotIn('TEST-SECRET',json.dumps(c.audit))
    def test_zero_budget_makes_no_request(self):
        c=self.client({},0)
        with self.assertRaises(LiveAmapError):c.weather('330100')
        self.assertEqual(c.spent,0)
    def test_weather_provider_report_clock_is_preserved(self):
        c=self.client({'status':'1','lives':[{'adcode':'330100','reporttime':'2026-10-22 16:35:28','weather':'多云'}]})
        r=c.weather('330100');self.assertEqual(r['observed_at'],'2026-10-22T16:35:28+08:00')
    def test_weather_unknown_city_not_verified(self):
        c=self.client({'status':'1','lives':[{'adcode':'310000','reporttime':'2026-10-22 16:35:28'}]})
        self.assertFalse(c.weather('330100')['entity_verified'])
    def test_transit_units_and_metro_requirement(self):
        data={'status':'1','route':{'origin':'116.400000,39.900000','destination':'116.410000,39.910000',
              'transits':[{'cost':{'duration':'600','transit_fee':'3'},'segments':[{'bus':{'buslines':[{'type':'地铁线路'}]}}]}]}}
        c=self.client(data);dep=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()
        a,b=c.transit([116.4,39.9],[116.41,39.91],city1='010',city2='010',departure_at=dep)
        self.assertEqual(a['value'],10);self.assertEqual(b['value'],3);self.assertTrue(a['entity_verified'])
        self.assertIn('date',c.audit[0]['params']);self.assertEqual(c.audit[0]['params']['show_fields'],'cost')
    def test_bus_only_does_not_satisfy_only_metro(self):
        data={'status':'1','route':{'origin':'116.400000,39.900000','destination':'116.410000,39.910000',
              'transits':[{'cost':{'duration':'600'},'segments':[{'bus':{'buslines':[{'type':'普通公交线路'}]}}]}]}}
        c=self.client(data);dep=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()
        a,b=c.transit([116.4,39.9],[116.41,39.91],city1='010',city2='010',departure_at=dep)
        self.assertFalse(a['entity_verified']);self.assertIsNone(b['value'])
    def test_unknown_coordinate_system_refused_before_call(self):
        c=self.client({})
        with self.assertRaises(ValueError):c.transit([116.4,39.9],[116.41,39.91],city1='010',city2='010',departure_at=NOW,coord_system='unknown')
        self.assertEqual(c.spent,0)

class CatalogTests(unittest.TestCase):
    def test_full_small_annotation_does_not_mutate_or_fabricate_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base=root/'ChinaTravel/chinatravel/environment/database/attractions/hangzhou';base.mkdir(parents=True)
            raw=base/'attractions.csv';raw.write_text('name,type,lat,lon,price\n小景点,自然风光,30,120,0\n',encoding='utf-8')
            before=digest_file(raw);out=root/'catalog';s=annotate_dataset(root,out,{},languages=('zh',))
            self.assertEqual(s['records'],1);self.assertEqual(digest_file(raw),before)
            cat=TravelCatalog(out/'catalog.sqlite3')
            try:
                r=cat.candidates('杭州',[Demand('nature',True)],limit=3)[0]['record']
                self.assertIsNone(r['observed_at']);self.assertIsNone(r['valid_until']);self.assertTrue(r['needs_live_verification'])
                plan=preflight(cat,{'start_city':'上海','target_city':'杭州','nature_language':'喜欢自然风光，少排队'},travel_date='2026-10-23',limit=3)
                self.assertTrue(plan['uncovered_query_tags']);self.assertFalse(plan['ready_for_real_world_recommendation'])
                self.assertTrue(any(t['field']=='route_duration' for t in plan['retrieval_tasks']))
                route=next(t for t in plan['retrieval_tasks'] if t['field']=='route_duration')
                self.assertIsNone(route['context']['origin'])
            finally:cat.close()
    def test_unknown_candidates_survive_tag_pruning(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=TravelCatalog(Path(tmp)/'catalog.sqlite3')
            try:
                for i in range(10):
                    tags=[{'tag':'nature','value':True}] if i<9 else []
                    r={'record_id':str(i),'tags':tags,'name':str(i)}
                    c.db.execute('INSERT INTO records VALUES(?,?,?,?,?,?)',(str(i),'zh','attraction','杭州',str(i),json.dumps(r)))
                c.db.commit();chosen=c.candidates('杭州',[Demand('nature',True)],limit=6)
                self.assertEqual(len(chosen),6);self.assertTrue(any(x['unknown_aspects'] for x in chosen))
            finally:c.close()
    def test_type_is_not_review_evidence(self):
        tags=static_tags('attraction',{'name':'地铁方便排队少','type':'历史古迹'})
        self.assertFalse(any(t['tag'] in ('queue_report','reachability','family','nature') for t in tags))

if __name__=='__main__':unittest.main()
