import copy,hashlib,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.retrieval_benchmark import evaluate,serve,assess_evidence,VERSION
def qty(value=None,status='unknown',ids=()):return {'value':value,'status':status,'evidence_ids':list(ids)}
class DynamicTests(unittest.TestCase):
    def setUp(self):
        self.r={'target_id':'a','city':'新城','field':'price','context':{'travel_date':'2026-10-24'},'entity_required':True}
        self.q={'uid':'q','people_number':2,'city_sequence':['新城'],'dates':['2026-10-24'],'requirements':[self.r],
            'candidates':[{'entity_id':'a','city':'新城','name':'景点','dataset':'expansion_discovery'}],'retrieval_budget':1}
        self.p={'schema_version':VERSION,'uid':'q','stage':'static','status':'conditional','people_number':2,'start_city':'新城','city_sequence':['新城'],
            'itinerary':[{'day':1,'date':'2026-10-24','city':'新城','activities':[{'activity_id':'a1','type':'attraction','city':'新城','entity_id':'a','position':'景点',
                'start_time':'10:00','end_time':'11:00','price':qty(),'cost':qty(),'transports':[],'evidence_ids':[]}]}],
            'gaps':[{'target_id':'a','field':'price','reason':'missing','state':'pending','evidence_ids':[]}],
            'retrieval_requests':[{'request_id':'r1','target_id':'a','city':'新城','fields':['price'],'provider':'operator','context':{'travel_date':'2026-10-24'},'reason':'missing'}],'feedback':[]}
        self.e={'evidence_id':'e1','target_id':'a','city':'新城','field':'price','context':{'travel_date':'2026-10-24'},'value':40,'level':'reference','source_id':'operator',
            'quote':'40元','raw_text':'票价40元','raw_sha256':hashlib.sha256('票价40元'.encode()).hexdigest()}
    def result(self,p=None,e=None):return evaluate(self.q,p or self.p,e or [])
    def resolve(self,status='reference'):
        p=copy.deepcopy(self.p);p['gaps'][0].update(state=status,evidence_ids=['e1']);a=p['itinerary'][0]['activities'][0]
        a.update(price=qty(40,status,['e1']),cost=qty(80,status,['e1']));return p
    def test_unknown_is_valid_not_complete(self):
        r=self.result();self.assertTrue(r['schema_ok'] and r['safe']);self.assertFalse(r['complete'])
    def test_unknown_not_zero(self):
        p=copy.deepcopy(self.p);p['itinerary'][0]['activities'][0]['price']=qty(0)
        self.assertFalse(self.result(p)['schema_ok'])
    def test_unreferenced_number_rejected(self):
        p=self.resolve();p['itinerary'][0]['activities'][0]['price']['evidence_ids']=[]
        self.assertFalse(self.result(p,[self.e])['safe'])
    def test_fabricated_evidence_rejected(self):self.assertFalse(self.result(self.resolve())['safe'])
    def test_reference_usable_but_not_hard_complete(self):
        r=self.result(self.resolve(),[self.e]);self.assertTrue(r['safe']);self.assertEqual(r['metrics']['resolved_fields'],1);self.assertFalse(r['complete'])
    def test_reference_cannot_self_upgrade(self):self.assertFalse(self.result(self.resolve('verified'),[self.e])['safe'])
    def test_wrong_date_rejected(self):
        e=copy.deepcopy(self.e);e['context']['travel_date']='2026-10-25';self.assertFalse(self.result(self.resolve(),[e])['safe'])
    def test_wrong_city_rejected(self):
        e=copy.deepcopy(self.e);e['city']='旧城';self.assertFalse(self.result(self.resolve(),[e])['safe'])
    def test_quote_digest_tamper_rejected(self):
        e=copy.deepcopy(self.e);e['raw_text']='票价10元';self.assertFalse(assess_evidence(e,self.r)['usable'])
    def test_cached_quarantine_not_resolved(self):
        e=copy.deepcopy(self.e);e['rejected_reason']='entity_unverified';self.assertFalse(self.result(self.resolve(),[e])['safe'])
    def test_expiry_checked_at_frozen_time(self):
        e=copy.deepcopy(self.e);e['valid_until']='2026-10-23T07:00:00+00:00'
        self.assertFalse(assess_evidence(e,self.r,'2026-10-23T07:01:00+00:00')['usable'])
    def test_cost_multiplicity(self):
        p=self.resolve();p['itinerary'][0]['activities'][0]['cost']['value']=40;self.assertFalse(self.result(p,[self.e])['safe'])
    def test_wrong_city_entity(self):
        p=copy.deepcopy(self.p);p['itinerary'][0]['activities'][0]['city']='旧城';self.assertFalse(self.result(p)['protocol_ok'])
    def test_missing_city_link(self):
        q=copy.deepcopy(self.q);q['city_sequence']=['旧城','新城'];p=copy.deepcopy(self.p);p.update(start_city='旧城',city_sequence=q['city_sequence'])
        self.assertIn('missing_city_link:旧城>新城',evaluate(q,p)['issues'])
    def test_same_direction_not_reverse_route(self):
        r={'target_id':'route:A>B','city':'新城','field':'route_duration','context':{}};e=copy.deepcopy(self.e);e.update(target_id='route:B>A',field='route_duration',source_id='amap')
        self.assertFalse(assess_evidence(e,r)['usable'])
    def test_web_cannot_replace_amap_route(self):
        r=copy.deepcopy(self.r);r['field']='route_fare';e=copy.deepcopy(self.e);e['field']='route_fare';self.assertFalse(assess_evidence(e,r)['usable'])
    def test_gateway_filters_actual_requests(self):
        self.assertEqual(serve(self.q,[],[self.e]),[])
        req=copy.deepcopy(self.p['retrieval_requests']);req[0]['target_id']='b'
        self.assertEqual(serve(self.q,req,[self.e])[0]['status'],'unavailable')
    def test_gateway_budget_counts_unavailable(self):
        requests=self.p['retrieval_requests']*2;events=serve(self.q,requests,[self.e]);self.assertEqual(events[1]['status'],'budget_exhausted')
    def test_gateway_descriptive_metadata_does_not_hide_valid_evidence(self):
        requests=copy.deepcopy(self.p['retrieval_requests']);requests[0]['context'].update(name='景点',city='新城',people_number=2)
        self.assertEqual(serve(self.q,requests,[self.e])[0]['status'],'returned')
    def test_gateway_wrong_date_remains_unavailable(self):
        requests=copy.deepcopy(self.p['retrieval_requests']);requests[0]['context']['travel_date']='2026-10-25'
        self.assertEqual(serve(self.q,requests,[self.e])[0]['status'],'unavailable')
    def test_intercity_city_may_be_origin_but_direction_is_exact(self):
        r={'target_id':'leg:A>B','city':'B','field':'intercity_schedule','context':{'origin':'A','destination':'B','travel_date':'2026-10-24'}}
        q=copy.deepcopy(self.q);q['requirements']=[r];p=copy.deepcopy(self.p)
        p['retrieval_requests'][0].update(target_id='leg:A>B',city='A',fields=['intercity_schedule'],context=r['context'])
        self.assertEqual(evaluate(q,p)['metrics']['request_field_coverage'],1)
        p['retrieval_requests'][0]['context']={'origin':'B','destination':'A','travel_date':'2026-10-24'}
        self.assertEqual(evaluate(q,p)['metrics']['request_field_coverage'],0)
    def test_hours_reference_must_be_applied(self):
        q=copy.deepcopy(self.q);q['requirements'][0]['field']='opening_hours';p=copy.deepcopy(self.p);p['gaps'][0].update(field='opening_hours',state='reference',evidence_ids=['e1'])
        e=copy.deepcopy(self.e);e.update(field='opening_hours',value={'open':'12:00','close':'17:00'})
        self.assertIn('hours_not_applied:a1',evaluate(q,p,[e])['issues'])
    def test_false_complete_rejected(self):
        p=copy.deepcopy(self.p);p['status']='complete';self.assertFalse(self.result(p)['protocol_ok'])
if __name__=='__main__':unittest.main(verbosity=2)
