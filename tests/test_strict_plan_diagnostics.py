import unittest
import copy
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from shorttrip.strict_plan_diagnostics import diagnose_plan


def contains_pass_state(value):
    if isinstance(value, dict):
        return (value.get('state') == 'pass' or
                any(contains_pass_state(item) for item in value.values()))
    if isinstance(value, list):
        return any(contains_pass_state(item) for item in value)
    return False


class PlanDiagnosticsTests(unittest.TestCase):
    def test_temporal_gate_blocks_case_variants_and_night_preferences(self):
        candidate = dict(activity={'start':datetime(2026,11,2,12), 'end':datetime(2026,11,2,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={'context':{}}, required_costs=[None], budget=100)
        scope = {'domain':'trip', 'quantifier':'any', 'item_kind':'attraction'}
        variants = [
            {'id':'weather', 'strength':'soft', 'scope':scope, 'compiler_status':'supported',
             'expression':{'op':'conditional_prefer_tag','args':{'if':{'Weather':'rain'},'prefer':{'setting':'indoor'}}}},
            {'id':'night', 'strength':'soft', 'scope':scope, 'compiler_status':'supported',
             'expression':{'op':'prefer_tag','args':{'tag':'Night_Activity'}}},
        ]
        result = diagnose_plan(uid='p', city='X', record_requirements=[], registry={},
                               now='2026-10-30T00:00:00Z', candidate=candidate,
                               constraints=variants, constraint_fact_verifier=lambda *_: True,
                               tag_scope_verifier=lambda *_: True)
        self.assertEqual([v['state'] for v in result['soft_checks']], ['unknown', 'unknown'])
        self.assertEqual(result['soft_checks'][0]['reason'], 'weather_temporal_scope_unresolved')
        self.assertEqual(result['soft_checks'][1]['reason'], 'night_activity_semantics_or_time_unresolved')

    def test_night_activity_tag_cannot_replace_actual_schedule_semantics(self):
        candidate = dict(activity={'start':datetime(2026,11,2,12), 'end':datetime(2026,11,2,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={'context':{}},
                         required_costs=[None], budget=100)
        constraint = {'id':'night', 'strength':'hard', 'compiler_status':'supported',
                      'scope':{'domain':'trip', 'quantifier':'all', 'item_kind':'attraction'},
                      'expression':{'op':'exclude_tag', 'args':{'tag':'night_activity'}}}
        evidence = {'night':{'scope_items':['a'], 'tag_facts':[{'item_id':'a',
                    'tag':'night_activity', 'present':False, 'item_kind':'attraction',
                    'scope':{'domain':'trip', 'item_kind':'attraction'}}]}}
        result = diagnose_plan(uid='p', city='X', record_requirements=[], registry={},
            now='2026-10-30T00:00:00Z', candidate=candidate, constraints=[constraint],
            tag_evidence=evidence, constraint_fact_verifier=lambda *_: True,
            tag_scope_verifier=lambda *_: True)
        self.assertIn('constraint:night', [c['field'] for c in result['unknown_checks']])
        self.assertNotIn('constraint:night', [c['field'] for c in result['passed_checks']])

    def test_weather_without_temporal_quantifier_remains_unknown_even_if_callback_accepts(self):
        candidate = dict(activity={'start':datetime(2026,11,2,12), 'end':datetime(2026,11,2,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={'context':{}},
                         required_costs=[None], budget=100)
        constraint = {'id':'rain', 'strength':'soft', 'compiler_status':'supported',
                      'scope':{'domain':'trip', 'quantifier':'any', 'item_kind':'attraction'},
                      'expression':{'op':'conditional_prefer_tag', 'args':{
                          'if':{'weather':'rain'}, 'prefer':{'setting':'indoor'}}}}
        result = diagnose_plan(uid='p', city='X', record_requirements=[], registry={},
            now='2026-10-30T00:00:00Z', candidate=candidate, constraints=[constraint],
            tag_evidence={'rain':{'scope_items':['a'], 'tag_facts':[],
                                  'condition_facts':[{'key':'weather', 'value':'rain',
                                                      'scope':{'domain':'trip'}}]}},
            constraint_fact_verifier=lambda *_: True, tag_scope_verifier=lambda *_: True)
        check = result['soft_checks'][0]
        self.assertEqual(check['state'], 'unknown')
        self.assertEqual(check['reason'], 'weather_temporal_scope_unresolved')

    def test_supplied_overnight_boundary_without_itinerary_is_reported_unknown(self):
        candidate = dict(activity={'start':datetime(2026,11,2,12), 'end':datetime(2026,11,2,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={'context':{}},
                         required_costs=[None], budget=100)
        result = diagnose_plan(uid='p', city='X', record_requirements=[], registry={},
            now='2026-10-30T00:00:00Z', candidate=candidate, overnight_boundaries=[{}])
        self.assertEqual(result['overnight_checks']['state'], 'unknown')
        self.assertIn('itinerary_overnight_continuity', [c['field'] for c in result['unknown_checks']])

    def test_meal_binding_rejects_duplicate_dates_and_unrecognized_items(self):
        from shorttrip.strict_plan_diagnostics import _bind_meal_events
        day = {'date': '2026-11-15', 'timeline': [{'type': 'lunch', 'entity_id': 'r'}]}
        self.assertFalse(_bind_meal_events([day, day], [])['complete'])
        unknown = {'date': '2026-11-15', 'timeline': [{'type': 'unrecognized'}]}
        self.assertFalse(_bind_meal_events([unknown], [])['complete'])

    def test_meal_events_bind_exactly_to_timeline_and_task_policy(self):
        days = [{'date':'2026-11-02','timeline':[
            {'type':'visit','entity_id':'poi','start':'09:00','end':'10:00'},
            {'type':'lunch','entity_id':'restaurant-1','start':'12:00','end':'13:00'}]}]
        candidate = dict(activity={'start':datetime(2026,11,2,12), 'end':datetime(2026,11,2,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={'context':{}},
                         required_costs=[None], budget=100)
        task = {'uid':'task-1','meal_policy':{'required_slots':[
            {'date':'2026-11-02','slot':'lunch'}]}}
        meal_coverage = {'required_slots':[{'date':'2026-11-02','slot':'lunch'}],
            'events':[{'date':'2026-11-02','item_index':1,'type':'lunch',
                       'entity_id':'restaurant-1','event_id':'meal-event-1','slot':'lunch'}]}
        args = dict(uid='p', city='X', record_requirements=[], registry={},
            now='2026-10-30T00:00:00Z', candidate=candidate, itinerary_days=days,
            meal_coverage=meal_coverage, meal_policy_context=task,
            meal_policy_verifier=lambda t, slots: slots == t['meal_policy']['required_slots'],
            meal_inventory_verifier=lambda *_: True, meal_event_verifier=lambda _: True)
        passed = diagnose_plan(**args)
        self.assertEqual(passed['meal_coverage_check']['state'], 'pass')
        self.assertFalse(passed['meal_coverage_check']['complete_itinerary_certified'])

        forged = copy.deepcopy(meal_coverage)
        forged['events'][0]['entity_id'] = 'forged-restaurant'
        args['meal_coverage'] = forged
        bad_index = diagnose_plan(**args)
        self.assertEqual(bad_index['meal_coverage_check']['state'], 'unknown')
        self.assertEqual(bad_index['meal_coverage_check']['reason'],
                         'meal_event_not_bound_to_timeline')

        args['meal_coverage'] = meal_coverage
        args['meal_policy_verifier'] = lambda *_: False
        no_policy_binding = diagnose_plan(**args)
        self.assertEqual(no_policy_binding['meal_coverage_check']['state'], 'unknown')

        def mutate_policy(_task, slots):
            slots.clear()
            return True
        args['meal_policy_verifier'] = mutate_policy
        mutated_policy = diagnose_plan(**args)
        self.assertEqual(mutated_policy['meal_coverage_check']['state'], 'unknown')

    def test_meal_coverage_requires_all_explicit_meals_and_never_infers_slots(self):
        days = [{'date':'2026-11-02','timeline':[
            {'type':'lunch','entity_id':'r1','start':'12:00','end':'13:00'},
            {'type':'dinner','entity_id':'r2','start':'18:00','end':'19:00'}]}]
        candidate = dict(activity={'start':datetime(2026,11,2,12), 'end':datetime(2026,11,2,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={'context':{}},
                         required_costs=[None], budget=100)
        task = {'meal_policy':{'required_slots':[{'date':'2026-11-02','slot':'lunch'}]}}
        meal = {'required_slots':task['meal_policy']['required_slots'],'events':[
            {'date':'2026-11-02','item_index':0,'type':'lunch','entity_id':'r1',
             'event_id':'e1','slot':'lunch'}]}
        out = diagnose_plan(uid='p',city='X',record_requirements=[],registry={},
            now='2026-10-30T00:00:00Z',candidate=candidate,itinerary_days=days,
            meal_coverage=meal,meal_policy_context=task,
            meal_policy_verifier=lambda *_:True,meal_inventory_verifier=lambda *_:True,
            meal_event_verifier=lambda _:True)
        self.assertEqual(out['meal_coverage_check']['state'],'unknown')
        self.assertEqual(out['meal_coverage_check']['reason'],
                         'meal_event_timeline_coverage_mismatch')
        no_policy = diagnose_plan(uid='p',city='X',record_requirements=[],registry={},
            now='2026-10-30T00:00:00Z',candidate=candidate,itinerary_days=days,
            meal_coverage={'required_slots':[],'events':[]},meal_policy_context=task,
            meal_policy_verifier=lambda *_:True,meal_inventory_verifier=lambda *_:True,
            meal_event_verifier=lambda _:True)
        self.assertEqual(no_policy['meal_coverage_check']['state'],'unknown')

    @staticmethod
    def _overnight_inputs():
        requirement = {'entity_id':'hotel', 'room_type':'twin',
            'check_in':'2026-11-02', 'check_out':'2026-11-03', 'rooms':1,
            'guests_per_room':2, 'minimum_beds':2, 'eligibility':'standard',
            'meal_plan':'none', 'taxes_included':True, 'mandatory_fees_included':True}
        claim = {'entity_id':'hotel', 'room_type':'twin',
            'check_in':'2026-11-02', 'check_out':'2026-11-03',
            'guests_per_room':2, 'currency':'CNY', 'unit':'CNY/room/night',
            'rate':200, 'beds':2, 'max_guests_per_room':2,
            'eligibility':'standard', 'meal_plan':'none', 'taxes_included':True,
            'mandatory_fees_included':True}
        days = [
            {'date':'2026-11-02', 'timeline':[{'type':'visit', 'entity_id':'hotel',
              'entrance_id':'lobby', 'start':'20:00:00+08:00', 'end':'22:00:00+08:00'}]},
            {'date':'2026-11-03', 'timeline':[{'type':'visit', 'entity_id':'hotel',
              'entrance_id':'lobby', 'start':'08:00:00+08:00', 'end':'09:00:00+08:00'}]},
        ]
        boundary = {'previous_day':'2026-11-02', 'next_day':'2026-11-03',
            'last_endpoint':{'entity_id':'hotel','entrance_id':'lobby',
                             'datetime':'2026-11-02T22:00:00+08:00'},
            'first_endpoint':{'entity_id':'hotel','entrance_id':'lobby',
                              'datetime':'2026-11-03T08:00:00+08:00'},
            'lodging_entrance_id':'lobby', 'lodging_requirement':requirement,
            'lodging_claim':claim}
        return days, boundary

    def test_overnight_boundary_must_match_actual_complete_day_edges(self):
        days, boundary = self._overnight_inputs()
        candidate = dict(activity={'start':datetime(2026,11,2,12), 'end':datetime(2026,11,2,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={'context':{}},
                         required_costs=[None], budget=100)
        args = dict(uid='p', city='X', record_requirements=[], registry={},
            now='2026-10-30T00:00:00Z', candidate=candidate, itinerary_days=days,
            itinerary_interval_verifier=lambda _: True,
            itinerary_endpoint_verifier=lambda _: True,
            overnight_boundaries=[boundary],
            overnight_fact_verifier=lambda *_: True,
            overnight_lodging_verifier=lambda *_: True)
        good = diagnose_plan(**args)
        self.assertEqual(good['overnight_checks']['state'], 'pass')
        self.assertFalse(good['overnight_checks']['complete_itinerary_certified'])

        forged = copy.deepcopy(boundary)
        forged['last_endpoint']['entity_id'] = 'other-hotel'
        args['overnight_boundaries'] = [forged]
        bad = diagnose_plan(**args)
        self.assertEqual(bad['overnight_checks']['state'], 'unknown')
        self.assertEqual(bad['overnight_checks']['reason'],
                         'overnight_boundary_not_bound_to_itinerary')

        args['overnight_boundaries'] = []
        missing = diagnose_plan(**args)
        self.assertEqual(missing['overnight_checks']['state'], 'unknown')
        self.assertIn('itinerary_overnight_continuity',
                      [x['field'] for x in missing['unknown_checks']])

    def test_overnight_binding_requires_every_boundary_and_aware_timeline_edges(self):
        days, boundary = self._overnight_inputs()
        days.append({'date':'2026-11-04', 'timeline':[{'type':'visit','entity_id':'hotel',
            'entrance_id':'lobby','start':'08:00:00+08:00','end':'09:00:00+08:00'}]})
        candidate = dict(activity={'start':datetime(2026,11,2,12), 'end':datetime(2026,11,2,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={'context':{}},
                         required_costs=[None], budget=100)
        result = diagnose_plan(uid='p', city='X', record_requirements=[], registry={},
            now='2026-10-30T00:00:00Z', candidate=candidate, itinerary_days=days,
            overnight_boundaries=[boundary], overnight_fact_verifier=lambda *_: True,
            overnight_lodging_verifier=lambda *_: True)
        self.assertEqual(result['overnight_checks']['reason'],
                         'overnight_boundary_coverage_mismatch')
        days[0]['timeline'][-1]['end'] = '22:00'
        result = diagnose_plan(uid='p', city='X', record_requirements=[], registry={},
            now='2026-10-30T00:00:00Z', candidate=candidate, itinerary_days=days,
            overnight_boundaries=[boundary], overnight_fact_verifier=lambda *_: True,
            overnight_lodging_verifier=lambda *_: True)
        self.assertEqual(result['overnight_checks']['reason'],
                         'overnight_timeline_endpoint_unrepresented')

    def test_cross_day_missing_overnight_does_not_become_hard_endpoint_failure(self):
        candidate = dict(activity={'start':datetime(2026,11,2,12), 'end':datetime(2026,11,2,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={'context':{}},
                         required_costs=[None], budget=100)
        days = [{'date':'2026-11-02', 'timeline':[{'type':'travel', 'start':'20:00', 'end':'20:30',
                  'origin_id':'poi', 'origin_entrance_id':'gate',
                  'destination_id':'hotel', 'destination_entrance_id':'lobby'}]},
                {'date':'2026-11-03', 'timeline':[{'type':'visit', 'start':'09:00', 'end':'10:00',
                  'entity_id':'museum', 'entrance_id':'gate'}]}]
        result = diagnose_plan(uid='p', city='X', record_requirements=[], registry={},
            now='2026-10-30T00:00:00Z', candidate=candidate, itinerary_days=days,
            itinerary_interval_verifier=lambda _: True, itinerary_endpoint_verifier=lambda _: True)
        self.assertEqual(result['itinerary_checks']['continuity']['state'], 'unknown')
        self.assertIn('itinerary_continuity', [c['field'] for c in result['unknown_checks']])
        self.assertNotIn('itinerary_continuity', [c['field'] for c in result['hard_failures']])

    def test_chain_order_failure_is_not_hidden_by_data_block(self):
        from tests.test_strict_business_chain import CHAIN
        candidate=dict(activity={'start':datetime(2026,10,30,12),'end':datetime(2026,10,30,13),'windows':None},
                       route_requirement={'context':{}},route_evidence={'context':{}},required_costs=[None],budget=100)
        result=diagnose_plan(uid='p',city='X',record_requirements=[],registry={},now='2026-10-30T00:00:00Z',
            candidate=candidate,business_chain={'chain':CHAIN,'events':list(reversed(CHAIN))},
            chain_inventory_verifier=lambda *_:True,chain_event_verifier=lambda _:True)
        self.assertTrue(result['axes']['data'])
        self.assertIn('business_chain',[x['field'] for x in result['hard_failures']])
    def test_self_claimed_supported_constraint_must_recompile(self):
        candidate=dict(activity={'start':datetime(2026,10,30,12),'end':datetime(2026,10,30,13),'windows':None},
                       route_requirement={'context':{}},route_evidence={'context':{}},required_costs=[None],budget=100)
        constraint={'id':'bad','strength':'hard','scope':{'currency':'CNY','people':3,'unit':'total_trip_cost'},
                    'compiler_status':'supported','expression':{'op':'total_cost_at_most',
                    'args':{'CNY':100,'people':2,'includes':['rooms']}}}
        result=diagnose_plan(uid='p',city='X',record_requirements=[],registry={},now='2026-10-30T00:00:00Z',
            candidate=candidate,constraints=[constraint],constraint_facts={'bad':{'value':10,'unit':'CNY',
            'context':{'people':2,'includes':['rooms']}}},constraint_fact_verifier=lambda *_:True)
        self.assertIn('constraint_compile_validation_failed',[x['reason'] for x in result['axes']['adapter']])
    def test_finite_route_proof_never_proves_whole_task(self):
        from tests.test_strict_route_proof import evidence, candidate as route_candidate, NOW
        candidate=dict(activity={'start':datetime(2026,11,2,12),'end':datetime(2026,11,2,13),'windows':None},
                       route_requirement={'context':{}},route_evidence={'context':{}},required_costs=[None],budget=100)
        result=diagnose_plan(uid='p',city='X',record_requirements=[],registry={},now=NOW,candidate=candidate,
            finite_route_domain={'dimensions':{'route':['a','b']},'candidates':[route_candidate('a',10),route_candidate('b',15)],
                                 'evidence':[evidence(20)]},finite_route_evidence_verifier=lambda *_:True)
        self.assertEqual(result['route_domain_check']['status'],'finite_route_domain_failure_verified')
        self.assertIn('whole_task_proof_not_established',[x['reason'] for x in result['axes']['solver']])
        self.assertNotEqual(result['outcome'],'infeasible_proven')
    def test_intercity_unit_conflict_is_adapter_block_not_collection_job(self):
        from tests.test_strict_intercity import inputs
        req,claim=inputs();claim['Duration_unit']='minutes'
        candidate=dict(activity={'start':datetime(2026,10,30,12),'end':datetime(2026,10,30,13),'windows':None},
                       route_requirement={'context':{}},route_evidence={'context':{}},required_costs=[None],budget=100)
        result=diagnose_plan(uid='p',city='X',record_requirements=[],registry={},now='2026-10-30T00:00:00Z',
            candidate=candidate,intercity={'requirement':req,'claim':claim},intercity_verifier=lambda *_:True)
        self.assertIn('native_duration_unit_conflict',[x['reason'] for x in result['axes']['adapter']])
        self.assertFalse(any(x.get('field') == 'intercity_timetable' for x in result['repair_queue']))
    def test_lodging_scope_is_preserved_separately_from_budget(self):
        from tests.test_strict_lodging import inputs
        req,claim=inputs();claim['beds']=1
        candidate=dict(activity={'start':datetime(2026,10,30,12),'end':datetime(2026,10,30,13),'windows':None},
                       route_requirement={'context':{}},route_evidence={'context':{}},required_costs=[None],budget=100)
        result=diagnose_plan(uid='p',city='X',record_requirements=[],registry={},now='2026-10-30T00:00:00Z',
            candidate=candidate,lodging={'requirement':req,'claim':claim},lodging_verifier=lambda *_:True)
        self.assertIn('lodging_scope_and_beds',[x['field'] for x in result['hard_failures']])
        self.assertIn('budget',[x['field'] for x in result['unknown_checks']])
        self.assertEqual(result['lodging_check']['total_cny'],1600)
    def test_identity_verifier_reaches_record_gate(self):
        rec={'id':'e','city':'X','kind':'attraction','name':'N','payload':{'data':{}},'claims':[]}
        req=[{'native_field':'price','policy_field':'price','scope':{'ticket':'adult'}}]
        candidate=dict(activity={'start':datetime(2026,10,30,12),'end':datetime(2026,10,30,13),'windows':None},
                       route_requirement={'context':{}},route_evidence={'context':{}},required_costs=[None],budget=100)
        args=dict(uid='p',city='X',record_requirements=[(rec,req)],registry={},
                  now='2026-10-30T00:00:00Z',candidate=candidate)
        a=diagnose_plan(**args)
        self.assertIn('identity_unresolved',[g['reason'] for g in a['axes']['data']])
        b=diagnose_plan(**args,identity_verifier=lambda record:record['id']=='e')
        self.assertNotIn('identity_unresolved',[g['reason'] for g in b['axes']['data']])
        self.assertTrue(any(g.get('repairable') is True and g.get('field')=='price' for g in b['axes']['data']))
    def test_tag_exclusion_requires_compiled_scope_and_verified_fact(self):
        candidate = dict(activity={'start':datetime(2026,10,30,12), 'end':datetime(2026,10,30,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={'context':{}}, required_costs=[None], budget=100)
        constraint={'id':'night','strength':'hard','scope':{'domain':'trip','quantifier':'all'},
                    'compiler_status':'supported','expression':{'op':'exclude_tag','args':{'tag':'restricted_tag'}}}
        evidence={'night':{'scope_items':['item1'],'tag_facts':[{'item_id':'item1','tag':'restricted_tag',
                   'present':True,'scope':{'domain':'trip'}}]}}
        args=dict(uid='p',city='X',record_requirements=[],registry={},now='2026-10-30T00:00:00Z',
                  candidate=candidate,constraints=[constraint],tag_evidence=evidence)
        unverified=diagnose_plan(**args)
        self.assertIn('constraint:night',[x['field'] for x in unverified['unknown_checks']])
        checked=diagnose_plan(**args,constraint_fact_verifier=lambda *_:True,tag_scope_verifier=lambda *_:True)
        self.assertIn('constraint:night',[x['field'] for x in checked['hard_failures']])
        constraint['compiler_status']='unmapped'
        unmapped=diagnose_plan(**args,constraint_fact_verifier=lambda *_:True,tag_scope_verifier=lambda *_:True)
        self.assertIn('constraint_not_compiled',[x['reason'] for x in unmapped['axes']['adapter']])
        constraint.pop('compiler_status')
        missing=diagnose_plan(**args,constraint_fact_verifier=lambda *_:True,tag_scope_verifier=lambda *_:True)
        self.assertIn('constraint_not_compiled',[x['reason'] for x in missing['axes']['adapter']])
        self.assertNotIn('constraint:night',[x['field'] for x in missing['hard_failures']])
    def test_constraint_failure_and_unsupported_operator_are_both_preserved(self):
        candidate = dict(activity={'start':datetime(2026,10,30,12), 'end':datetime(2026,10,30,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={'context':{}}, required_costs=[None], budget=100)
        constraints = [{'id':'budget','strength':'hard','compiler_status':'supported',
                        'scope':{'currency':'CNY','people':2,'unit':'total_trip_cost'},
                        'expression':{'op':'total_cost_at_most','args':{'CNY':100,'people':2,'includes':['rooms']}}},
                       {'id':'conditional','strength':'hard','compiler_status':'supported','expression':{'op':'implies','args':{}}}]
        facts = {'budget':{'value':101,'unit':'CNY','context':{'people':2,'includes':['rooms']}}}
        result = diagnose_plan(uid='p',city='X',record_requirements=[],registry={},now='2026-10-30T00:00:00Z',
                               candidate=candidate,constraints=constraints,constraint_facts=facts,
                               constraint_fact_verifier=lambda *_: True)
        self.assertIn('constraint:budget', [x['field'] for x in result['hard_failures']])
        self.assertIn('constraint_compile_validation_failed', [x['reason'] for x in result['axes']['adapter']])
        self.assertTrue(result['axes']['data'])
    def test_field_evidence_verifier_is_forwarded_to_record_adapter(self):
        rec = {'id':'r', 'city':'X', 'kind':'attraction', 'name':'N',
               'payload':{'data':{}}, 'claims':[]}
        candidate = dict(activity={'start':datetime(2026,10,30,12),
                                  'end':datetime(2026,10,30,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={'context':{}},
                         required_costs=[None], budget=100)
        verifier=lambda *args: True
        with patch('shorttrip.strict_plan_diagnostics.diagnose_record', return_value={
                'axes':{}, 'hard_failures':[], 'unknown_checks':[]}) as mocked:
            diagnose_plan(uid='p', city='X', record_requirements=[(rec,[])], registry={},
                now='2026-10-30T00:00:00Z', candidate=candidate,
                field_evidence_verifier=verifier)
        self.assertIs(mocked.call_args.kwargs['evidence_verifier'], verifier)

    def test_evidence_auditor_is_forwarded_and_audits_are_retained_with_level(self):
        rec = {'id':'r', 'city':'X', 'kind':'attraction', 'name':'N',
               'payload':{'data':{}}, 'claims':[]}
        candidate = dict(activity={'start':datetime(2026,10,30,12),
                                  'end':datetime(2026,10,30,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={'context':{}},
                         required_costs=[None], budget=100)
        auditor = lambda *args: {'claim_id':'c', 'state':'reviewed'}
        expected_audit = {'claim_id':'c', 'field':'price', 'state':'reviewed'}
        with patch('shorttrip.strict_plan_diagnostics.diagnose_record', return_value={
                'axes':{}, 'hard_failures':[], 'unknown_checks':[],
                'evidence_audits':[expected_audit]}) as mocked:
            result = diagnose_plan(uid='p', city='X', record_requirements=[(rec,[])],
                registry={}, now='2026-10-30T00:00:00Z', candidate=candidate,
                evidence_auditor=auditor, level='medium')
        self.assertIs(mocked.call_args.kwargs['evidence_auditor'], auditor)
        self.assertEqual(result['level'], 'medium')
        self.assertEqual(result['evidence_audits'], [expected_audit])

    def test_data_and_room_constraint_failures_are_preserved(self):
        rec = {'id':'r', 'city':'西安', 'kind':'attraction', 'name':'N',
               'payload':{'data':{}}, 'claims':[]}
        candidate = dict(activity={'start':datetime(2026,10,30,12),
                                  'end':datetime(2026,10,30,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={'context':{}},
                         required_costs=[None], budget=100)
        result = diagnose_plan(uid='p', city='西安',
            record_requirements=[(rec,[{'native_field':'price','policy_field':'price',
                                       'scope':{'ticket':'adult'}}])], registry={},
            now='2026-10-30T00:00:00Z', candidate=candidate,
            room={'room_type':'double','claim':{'room_type':'double','beds':1},'required_beds':2},
            room_verifier=lambda room: True)
        self.assertTrue(result['axes']['data'])
        self.assertIn('room_beds', [c['field'] for c in result['hard_failures']])
        self.assertEqual(result['outcome'], 'data_block')
        self.assertFalse(result['execution_confirmed'])

    def test_room_type_mismatch_is_unknown_not_hard_failure(self):
        candidate = dict(activity={'start':datetime(2026,10,30,12),
                                  'end':datetime(2026,10,30,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={'context':{}},
                         required_costs=[None], budget=100)
        result = diagnose_plan(uid='p', city='X', record_requirements=[], registry={},
            now='2026-10-30T00:00:00Z', candidate=candidate,
            room={'room_type':'double','claim':{'room_type':'single','beds':1},'required_beds':2},
            room_verifier=lambda room: True)
        self.assertIn('room_beds', [c['field'] for c in result['unknown_checks']])
        self.assertNotIn('room_beds', [c['field'] for c in result['hard_failures']])

    def test_room_verifier_cannot_fabricate_beds_or_lower_requirement(self):
        candidate = dict(activity={'start':datetime(2026,10,30,12),
                                  'end':datetime(2026,10,30,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={'context':{}},
                         required_costs=[None], budget=100)
        cases = [
            ({'room_type':'double','claim':{'room_type':'double','beds':1},
              'required_beds':2}, lambda room: room['claim'].update(beds=3) or True),
            ({'room_type':'double','claim':{'room_type':'double','beds':2},
              'required_beds':3}, lambda room: room.update(required_beds=2) or True),
        ]
        for room, verifier in cases:
            with self.subTest(room=room):
                original = copy.deepcopy(room)
                result = diagnose_plan(uid='p', city='X', record_requirements=[], registry={},
                    now='2026-10-30T00:00:00Z', candidate=candidate,
                    room=room, room_verifier=verifier)
                self.assertEqual(room, original)
                self.assertIn('room_beds', [c['field'] for c in result['unknown_checks']])
                self.assertNotIn('room_beds', [c['field'] for c in result['passed_checks']])
                self.assertNotIn('room_beds', [c['field'] for c in result['hard_failures']])

    def test_explicit_itinerary_without_independent_verifiers_is_solver_unknown(self):
        candidate = dict(activity={'start':datetime(2026,10,30,12),
                                  'end':datetime(2026,10,30,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={},
                         required_costs=[None], budget=None)
        days = [{'date':'2026-10-30','timeline':[
            {'type':'travel','start':'09:00','end':'09:30',
             'origin_id':'hotel','origin_entrance_id':'lobby',
             'destination_id':'poi','destination_entrance_id':'east'},
            {'type':'visit','start':'09:30','end':'10:30',
             'entity_id':'poi','entrance_id':'east','entity':'label-only'}]}]
        result = diagnose_plan(uid='p', city='X', record_requirements=[], registry={},
            now='2026-10-30T00:00:00Z', candidate=candidate, itinerary_days=days)
        self.assertEqual(result['itinerary_checks']['chronology']['state'], 'unknown')
        self.assertEqual(result['itinerary_checks']['continuity']['state'], 'unknown')
        checks = {x['field']:x for x in result['unknown_checks']}
        self.assertIn('itinerary_chronology', checks)
        self.assertIn('itinerary_continuity', checks)
        self.assertTrue(result['axes']['solver'])

    def test_verified_itinerary_checks_do_not_certify_whole_plan(self):
        candidate = dict(activity={'start':datetime(2026,10,30,12),
                                  'end':datetime(2026,10,30,13), 'windows':None},
                         route_requirement={'context':{}}, route_evidence={},
                         required_costs=[None], budget=None)
        days = [{'date':'2026-10-30','timeline':[
            {'type':'travel','start':'09:00','end':'09:30',
             'origin_id':'hotel','origin_entrance_id':'lobby',
             'destination_id':'poi','destination_entrance_id':'east'},
            {'type':'visit','start':'09:30','end':'10:30',
             'entity_id':'poi','entrance_id':'east'}]}]
        result = diagnose_plan(uid='p', city='X', record_requirements=[], registry={},
            now='2026-10-30T00:00:00Z', candidate=candidate, itinerary_days=days,
            itinerary_interval_verifier=lambda fact: True,
            itinerary_endpoint_verifier=lambda fact: True)
        self.assertEqual(result['itinerary_checks']['chronology']['state'], 'pass')
        self.assertEqual(result['itinerary_checks']['continuity']['state'], 'pass')
        self.assertNotEqual(result['outcome'], 'complete_under_declared_policy')
        self.assertFalse(result['execution_confirmed'])

    def test_additive_trip_cost_check_does_not_replace_existing_unknowns(self):
        from shorttrip.strict_constraint_compiler import compile_constraint
        candidate = dict(activity={'start':datetime(2026,11,2,12),'end':datetime(2026,11,2,13),'windows':None},
                         route_requirement={'context':{}},route_evidence={},required_costs=[None],budget=None)
        raw = {'id':'budget','strength':'hard','compiler_status':'supported',
               'scope':{'currency':'CNY','people':2,'unit':'total_trip_cost'},
               'expression':{'op':'total_cost_at_most','args':{'CNY':1000,'people':2,
                                                               'includes':['tickets','transport']}}}
        constraint = compile_constraint(raw)['constraint']
        trip_scope = {'task_uid':'p','plan_uid':'p','target_city':'X',
                      'itinerary_dates':['2026-11-02']}
        cost_days = [{'date':'2026-11-02','city':'X','timeline':[
            {'type':'visit','entity_id':'hotel-entity'},
            {'type':'travel','entity_id':'route-entity'}]}]
        components = [
            {'category':'tickets','amount':400,'currency':'CNY','party_size':2,
             'scope':trip_scope,'evidence':{'evidence_id':'hotel-price'},'expense_ids':['hotel-1'],
             'occurrence_bindings':[{'expense_id':'hotel-1','day_index':0,'item_index':0,
                'date':'2026-11-02','type':'visit','entity_id':'hotel-entity'}]},
            {'category':'transport','amount':100,'currency':'CNY','party_size':2,
             'scope':trip_scope,'evidence':{'evidence_id':'route-fare'},'expense_ids':['fare-1'],
             'occurrence_bindings':[{'expense_id':'fare-1','day_index':0,'item_index':1,
                'date':'2026-11-02','type':'travel','entity_id':'route-entity'}]},
        ]
        cost_task = {'uid':'p','target_city':'X','start_date':'2026-11-02','days':1,
                     'additional_constraints':[constraint]}
        result = diagnose_plan(uid='p',city='X',record_requirements=[],registry={},
            now='2026-10-30T00:00:00Z',candidate=candidate,constraints=[constraint],
            itinerary_days=cost_days,
            cost_aggregation={'constraint_id':'budget','policy':{
                'required_categories':['tickets','transport'],'currency':'CNY',
                'party_size':2,'total_limit':1000,'trip_scope':trip_scope},
                'components':components,'scope':trip_scope},
            cost_evidence_verifier=lambda *_:True,cost_inventory_verifier=lambda *_:True,
            cost_context_verifier=lambda *_:True,
            cost_task_input=cost_task,cost_plan_input={'uid':'p','days':cost_days},
            constraint_fact_verifier=lambda *_:True)
        self.assertEqual(result['trip_cost_aggregation_check']['state'],'pass')
        self.assertIn('budget',[x['field'] for x in result['unknown_checks']])
        self.assertIn('constraint:budget',[x['field'] for x in result['unknown_checks']])
        self.assertIn('trip_cost_aggregation',[x['field'] for x in result['passed_checks']])
        self.assertFalse(result['truth_certified'])
        mismatch = diagnose_plan(uid='p', city='X', record_requirements=[], registry={},
            now='2026-10-30T00:00:00Z', candidate=candidate, constraints=[constraint],
            itinerary_days=cost_days,
            cost_aggregation={'constraint_id':'budget','policy':{
                'required_categories':['tickets','transport'],'currency':'CNY',
                'party_size':2,'total_limit':1000,'trip_scope':trip_scope},
                'components':components,'scope':trip_scope},
            cost_evidence_verifier=lambda *_: True, cost_inventory_verifier=lambda *_: True,
            cost_context_verifier=lambda *_: True, cost_task_input=cost_task,
            cost_plan_input={'uid':'p','days':[{'date':'2026-11-02','city':'X',
                                                'timeline':[{'type':'visit','entity_id':'other'}]}]},
            constraint_fact_verifier=lambda *_: True)
        self.assertEqual(mismatch['trip_cost_aggregation_check']['state'], 'unknown')

    def test_forged_cost_policy_and_duplicate_budget_constraints_stay_unknown(self):
        from shorttrip.strict_constraint_compiler import compile_constraint
        candidate = dict(activity={'start':datetime(2026,11,2,12),'end':datetime(2026,11,2,13),'windows':None},
                         route_requirement={'context':{}},route_evidence={},required_costs=[None],budget=None)
        raw = {'id':'budget','strength':'hard','compiler_status':'supported',
               'scope':{'currency':'CNY','people':2,'unit':'total_trip_cost'},
               'expression':{'op':'total_cost_at_most','args':{'CNY':1000,'people':2,
                                                               'includes':['hotel']}}}
        constraint = compile_constraint(raw)['constraint']
        trip_scope = {'task_uid':'p','plan_uid':'p','target_city':'X',
                      'itinerary_dates':['2026-11-02']}
        payload = {'constraint_id':'budget','policy':{'required_categories':['hotel'],
            'currency':'CNY','party_size':2,'total_limit':1,'trip_scope':trip_scope},
            'components':[{'category':'hotel','amount':0,'currency':'CNY','party_size':2,
                           'scope':trip_scope,'evidence':{'evidence_id':'e'},'expense_ids':['e1']}], 'scope':trip_scope}
        args = dict(uid='p',city='X',record_requirements=[],registry={},now='2026-10-30T00:00:00Z',
                    candidate=candidate,itinerary_days=[{'date':'2026-11-02','city':'X','timeline':[]}],
                    constraints=[constraint],cost_aggregation=payload,
                    cost_evidence_verifier=lambda *_:True,cost_inventory_verifier=lambda *_:True,
                    cost_context_verifier=lambda *_:True,
                    cost_task_input={'uid':'p','target_city':'X','start_date':'2026-11-02','days':1,
                                     'additional_constraints':[constraint]},
                    cost_plan_input={'uid':'p','days':[{'date':'2026-11-02','city':'X','timeline':[]}]},
                    constraint_fact_verifier=lambda *_:True)
        forged = diagnose_plan(**args)
        self.assertEqual(forged['trip_cost_aggregation_check']['state'],'unknown')
        self.assertIn('constraint:budget',[x['field'] for x in forged['unknown_checks']])
        duplicate = compile_constraint({**raw,'id':'budget2'})['constraint']
        ambiguous = diagnose_plan(**{**args,'constraints':[constraint,duplicate]})
        self.assertEqual(ambiguous['trip_cost_aggregation_check']['state'],'unknown')
        self.assertEqual(ambiguous['trip_cost_aggregation_check']['reason'],'budget_constraint_ambiguous')

    def test_cost_context_closure_task_mutation_is_pipeline_error_without_pass(self):
        from shorttrip.strict_constraint_compiler import compile_constraint
        raw = {'id':'budget','strength':'hard','compiler_status':'supported',
               'scope':{'currency':'CNY','people':2,'unit':'total_trip_cost'},
               'expression':{'op':'total_cost_at_most','args':{
                   'CNY':1000,'people':2,'includes':['tickets','transport']}}}
        constraint = compile_constraint(raw)['constraint']
        scope = {'task_uid':'p','plan_uid':'p','target_city':'X',
                 'itinerary_dates':['2026-11-02']}
        days = [{'date':'2026-11-02','city':'X','timeline':[
            {'type':'visit','entity_id':'hotel-entity'},
            {'type':'travel','entity_id':'route-entity'}]}]
        components = [
            {'category':'tickets','amount':400,'currency':'CNY','party_size':2,
             'scope':scope,'evidence':{'evidence_id':'ticket'},'expense_ids':['ticket-1'],
             'occurrence_bindings':[{'expense_id':'ticket-1','day_index':0,'item_index':0,
                 'date':'2026-11-02','type':'visit','entity_id':'hotel-entity'}]},
            {'category':'transport','amount':100,'currency':'CNY','party_size':2,
             'scope':scope,'evidence':{'evidence_id':'fare'},'expense_ids':['fare-1'],
             'occurrence_bindings':[{'expense_id':'fare-1','day_index':0,'item_index':1,
                 'date':'2026-11-02','type':'travel','entity_id':'route-entity'}]},
        ]
        task = {'uid':'p','target_city':'X','start_date':'2026-11-02','days':1,
                'additional_constraints':[constraint]}
        plan = {'uid':'p','days':days}
        cost = {'constraint_id':'budget','policy':{
            'required_categories':['tickets','transport'],'currency':'CNY',
            'party_size':2,'total_limit':1000,'trip_scope':scope},
            'components':components,'scope':scope}
        candidate = dict(activity={'start':datetime(2026,11,2,12),
                                   'end':datetime(2026,11,2,13),'windows':None},
                         route_requirement={'context':{}},route_evidence={},
                         required_costs=[None],budget=None)
        mutation_attempted = []

        def mutate_original_task(*_args):
            mutation_attempted.append(True)
            task['target_city'] = 'Y'
            return True

        result = diagnose_plan(uid='p',city='X',record_requirements=[],registry={},
            now='2026-10-30T00:00:00Z',candidate=candidate,constraints=[constraint],
            itinerary_days=days,cost_aggregation=cost,
            cost_evidence_verifier=lambda *_:True,cost_inventory_verifier=lambda *_:True,
            cost_context_verifier=mutate_original_task,cost_task_input=task,
            cost_plan_input=plan,constraint_fact_verifier=lambda *_:True)

        self.assertTrue(mutation_attempted)
        self.assertEqual(result['outcome'],'pipeline_error')
        self.assertFalse(contains_pass_state(result))

    def test_candidate_schedule_closure_mutation_is_pipeline_error_without_pass(self):
        from tests.test_strict_v4_adapter import bind_schedule_scope
        zone = timezone(timedelta(hours=8))
        activity = bind_schedule_scope({
            'start':datetime(2026,11,2,12,tzinfo=zone),
            'end':datetime(2026,11,2,13,tzinfo=zone),
            'windows':[{'weekday':0,'open':'09:00','close':'10:00',
                        'end_day_offset':0}],
            'weekdays':[0], 'schedule_complete':True})
        mutation_attempted = []

        def widen_original_schedule(*_args):
            mutation_attempted.append(True)
            activity['windows'] = [{'weekday':0,'open':'00:00','close':'23:59',
                                    'end_day_offset':0}]
            return True

        candidate = {
            'activity':activity, 'route_requirement':{'context':{}},
            'route_evidence':{}, 'required_costs':[1], 'budget':10,
            'schedule_verifier':widen_original_schedule, 'cost_verifier':lambda *_:True,
        }
        result = diagnose_plan(uid='schedule-closure',city='X',record_requirements=[],
            registry={},now='2026-10-30T00:00:00Z',candidate=candidate)

        self.assertTrue(mutation_attempted)
        self.assertEqual(result['outcome'],'pipeline_error')
        self.assertFalse(contains_pass_state(result))

if __name__ == '__main__': unittest.main()
