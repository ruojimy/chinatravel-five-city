import copy,json,hashlib,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.retrieval_guard import gate,evaluate,enforce,monetary_check,triage,VERSION
NOW='2026-10-23T08:00:00+00:00'
def qty(v=None,s='unknown',ids=()):return {'value':v,'status':s,'evidence_ids':list(ids)}
def ev(field,value,level='verified',target='A'):
    raw=json.dumps(value,ensure_ascii=False)
    return {'evidence_id':field,'target_id':target,'city':'新城','field':field,'value':value,'level':level,'context':{},'source_id':'synthetic_fixture',
        'raw_text':raw,'quote':raw,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),'synthetic':True,'fixture_validated':True}
class GuardTests(unittest.TestCase):
    def setUp(self):
        self.e=[ev('identity',{'id':'A'}),ev('price',40),ev('opening_hours',{'open':'09:00','close':'17:00'})]
        self.q={'uid':'P','people_number':2,'city_sequence':['新城'],'dates':['2026-10-24'],'candidates':[{'entity_id':'A','city':'新城','name':'馆'}],
            'requirements':[{'target_id':'A','city':'新城','field':e['field'],'context':{}} for e in self.e],'retrieval_budget':0,'budget_cny':100}
        self.p={'schema_version':VERSION,'uid':'P','stage':'dynamic','status':'conditional','people_number':2,'start_city':'新城','city_sequence':['新城'],
            'itinerary':[{'day':1,'date':'2026-10-24','city':'新城','activities':[{'activity_id':'visit','type':'attraction','city':'新城','entity_id':'A','position':'馆','start_time':'10:00','end_time':'12:00',
                'price':qty(40,'verified',['price']),'cost':qty(80,'verified',['price']),'transports':[],'evidence_ids':[]}]}],
            'gaps':[{'target_id':'A','field':e['field'],'reason':'fixture','state':'verified','evidence_ids':[e['evidence_id']]} for e in self.e],'retrieval_requests':[],'feedback':[]}
    def check_plan(self,p=None,q=None,e=None):return evaluate(q or self.q,p or self.p,e or self.e,now=NOW)
    def test_known_feasible_fixture_accepted(self):
        r=self.check_plan();self.assertTrue(r['policy_accepted']);self.assertFalse(r['execution_confirmed']);self.assertTrue(r['synthetic_only'])
    def test_low_budget_rejected(self):
        q=copy.deepcopy(self.q);q['budget_cny']=79;self.assertIn('budget_exceeded',self.check_plan(q=q)['issues'])
    def test_unknown_component_prevents_budget_acceptance(self):
        p=copy.deepcopy(self.p);p['itinerary'][0]['activities'][0]['cost']=qty();self.assertFalse(self.check_plan(p)['policy_accepted'])
    def test_identity_estimate_rejected_even_if_labelled(self):
        e=copy.deepcopy(self.e[0]);e['level']='estimate';self.assertFalse(gate(e,self.q['requirements'][0],NOW)['usable'])
    def test_inventory_estimate_rejected(self):
        e=ev('inventory',{'confirmed_available':True},'estimate');r={**self.q['requirements'][0],'field':'inventory'};self.assertFalse(gate(e,r,NOW)['usable'])
    def test_missing_identity_blocks_instead_of_faking_complete(self):
        p=copy.deepcopy(self.p);p['gaps'][0].update(state='pending',evidence_ids=[]);self.assertFalse(self.check_plan(p)['policy_accepted'])
    def test_wrong_total_fails(self):
        p=copy.deepcopy(self.p);p['itinerary'][0]['activities'][0]['cost']['value']=40;self.assertFalse(self.check_plan(p)['safe'])
    def test_closed_weekday_fails(self):
        e=copy.deepcopy(self.e);e[2]=ev('opening_hours',{'open':'09:00','close':'17:00','closed_weekday':'Saturday'});self.assertIn('closed_weekday',self.check_plan(e=e)['issues'])
    def test_last_admission_fails(self):
        e=copy.deepcopy(self.e);e[2]=ev('opening_hours',{'open':'09:00','close':'17:00','last_admission':'09:30'});self.assertIn('outside_admission_window',self.check_plan(e=e)['issues'])
    def test_guard_never_mutates_raw(self):
        p=copy.deepcopy(self.p);e=copy.deepcopy(self.e);e[1]['rejected_reason']='expired';original=copy.deepcopy(p);out,edits=enforce(self.q,p,e,now=NOW)
        self.assertEqual(p,original);self.assertIsNone(out['itinerary'][0]['activities'][0]['price']['value']);self.assertTrue(edits)
    def test_guard_does_not_clear_wrong_city(self):
        p=copy.deepcopy(self.p);p['itinerary'][0]['activities'][0]['city']='旧城';out,_=enforce(self.q,p,self.e,now=NOW);self.assertFalse(self.check_plan(out)['protocol_ok'])
    def test_decision_not_factual_quote(self):
        p=copy.deepcopy(self.p);p['itinerary'][0]['activities'][0]['price']=qty(40,'decision');self.assertFalse(self.check_plan(p)['safe'])
    def test_incomplete_route_has_no_network_permission(self):
        req={'fields':['route_fare'],'context':{'origin':None}};self.assertEqual(triage(req)['status'],'needs_clarification');self.assertFalse(triage(req)['network_allowed'])
    def test_intercity_missing_adapter_explicit(self):self.assertEqual(triage({'fields':['intercity_schedule'],'context':{}})['status'],'adapter_required')
    def test_reference_cannot_be_hard_satisfaction_by_default(self):
        e=copy.deepcopy(self.e);e[1]['level']='reference';p=copy.deepcopy(self.p);p['gaps'][1]['state']='reference'
        a=p['itinerary'][0]['activities'][0];a['price']['status']=a['cost']['status']='reference';self.assertFalse(self.check_plan(p,e=e)['policy_accepted'])
    def test_explicit_reference_policy_is_conditional(self):
        e=copy.deepcopy(self.e);e[1]['level']='reference';p=copy.deepcopy(self.p);p['gaps'][1]['state']='reference'
        a=p['itinerary'][0]['activities'][0];a['price']['status']=a['cost']['status']='reference';q=copy.deepcopy(self.q);q['requirements'][1]['accepted_levels']=['reference']
        r=self.check_plan(p,q,e);self.assertTrue(r['policy_accepted']);self.assertTrue(r['conditions']);self.assertFalse(r['execution_confirmed'])
    def test_anchor_return_transport_counts_in_budget(self):
        p=copy.deepcopy(self.p);a=copy.deepcopy(p['itinerary'][0]['activities'][0]);a.update(activity_id='end',type='anchor',start_time='14:00',end_time='14:00',price=qty(),cost=qty())
        a['transports']=[{'cost':qty(30,'estimate')}];p['itinerary'][0]['activities'].append(a)
        self.assertEqual(monetary_check(p,100)['status'],'over_budget')
    def test_forged_real_identity_fails(self):
        e=ev('identity',{'provider_id':'fake'});e.pop('synthetic');e.pop('fixture_validated');self.assertFalse(gate(e,self.q['requirements'][0],NOW)['usable'])
    def test_route_fare_is_group_cost_and_departure_bound(self):
        p=copy.deepcopy(self.p);q=copy.deepcopy(self.q);context={'origin':'1,2','destination':'3,4','coord_system':'GCJ02','departure_at':'2026-10-24T09:00:00+08:00','mode':'metro'}
        fare=ev('route_fare',3,'estimate','route:X>A');fare.update(context=context,source_id='amap',unit='CNY/person')
        dur=ev('route_duration',30,'estimate','route:X>A');dur.update(context=context,source_id='amap',unit='minutes')
        for e in (fare,dur):q['requirements'].append({k:e[k] for k in ('target_id','city','field','context')})
        p['itinerary'][0]['activities'][0]['transports']=[{'start':'X','end':'A','mode':'metro','start_time':'08:00','end_time':'09:00',
            'price':qty(3,'estimate',['route_fare']),'cost':qty(3,'estimate',['route_fare']),'tickets':1,'duration_minutes':qty(30,'estimate',['route_duration'])}]
        r=evaluate(q,p,self.e+[fare,dur],now=NOW);self.assertIn('route_ticket_count_mismatch',r['issues']);self.assertIn('route_departure_mismatch',r['issues'])
    def test_exact_identity_display_annotation_normalizes_with_audit(self):
        p=copy.deepcopy(self.p);p['itinerary'][0]['activities'][0]['position']='馆（参观备注）';p['feedback']=[{'evidence_id':'price','action':'use','affected_ids':['A'],'reason':'use'}]
        out,edits=enforce(self.q,p,self.e,[{'evidence':self.e}],now=NOW)
        self.assertEqual(out['itinerary'][0]['activities'][0]['position'],'馆');self.assertEqual(out['feedback'][0]['affected_ids'],['visit']);self.assertTrue(edits)
    def test_other_venue_name_not_normalized_into_success(self):
        p=copy.deepcopy(self.p);p['itinerary'][0]['activities'][0]['position']='其他馆';out,_=enforce(self.q,p,self.e,now=NOW)
        self.assertEqual(out['itinerary'][0]['activities'][0]['position'],'其他馆');self.assertFalse(self.check_plan(out)['protocol_ok'])
    def test_real_bus_fallback_cannot_satisfy_metro_request(self):
        e=ev('route_fare',1,'estimate');e.pop('synthetic');e.pop('fixture_validated')
        e.update(source_id='amap',unit='CNY/person',source_observed_at=NOW,valid_until='2026-10-23T08:15:00+00:00',entity_verified=False,mode_requirement_met=False,
            context={'origin':'118.1,24.4','destination':'118.2,24.5','coord_system':'GCJ02','mode':'metro','departure_at':'2026-10-24T09:00:00+08:00'})
        r={k:e[k] for k in ('target_id','city','field','context')}
        verdict=gate(e,r,NOW);self.assertFalse(verdict['usable']);self.assertIn('route_mode_not_met',verdict['reasons']);self.assertIn('route_endpoints_not_bound',verdict['reasons'])
if __name__=='__main__':unittest.main(verbosity=2)
