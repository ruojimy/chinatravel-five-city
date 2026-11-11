import unittest
import copy
import json
import sys
from unittest.mock import patch
from pathlib import Path
from shorttrip.strict_p31_bridge import diagnose_p31_plan, _p31_cost_context_matches_task

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from p31_static import build_plan


class StrictP31BridgeTests(unittest.TestCase):
    def test_meal_verifier_cannot_change_original_plan_by_closure(self):
        plan = self.plan()
        plan['days'][0]['timeline'] = [{'type':'lunch','entity_id':'restaurant-1',
            'start':'12:00','end':'13:00'}]
        task = {'uid':'E01','additional_constraints':[], 'meal_policy':{
            'required_slots':[{'date':'2026-10-28','slot':'lunch'}]}}
        slots = copy.deepcopy(task['meal_policy']['required_slots'])
        events = [{'date':'2026-10-28','item_index':0,'type':'lunch',
                   'entity_id':'restaurant-1','event_id':'e1','slot':'lunch'}]
        def mutate(*_args):
            plan['days'][0]['timeline'][0]['entity_id'] = 'other'
            return True
        result = diagnose_p31_plan(plan, task=task, now='2026-10-30T00:00:00Z',
            registry={}, meal_coverage={'required_slots':slots,'events':events},
            meal_policy_verifier=lambda *_: True,
            meal_inventory_verifier=mutate, meal_event_verifier=lambda *_: True)
        self.assertEqual(result['outcome'], 'pipeline_error')
        self.assertFalse(result.get('passed_checks'))

    def test_cost_context_date_horizon_overflow_is_not_a_match(self):
        task = {'uid': 'u', 'target_city': 'A', 'start_date': '9999-12-31', 'days': 2}
        days = [{'date': '9999-12-31', 'city': 'A'}, {'date': '9999-12-31', 'city': 'A'}]
        self.assertFalse(_p31_cost_context_matches_task(task, 'u', days))

    def test_meal_policy_and_events_are_bound_through_p31_bridge(self):
        plan = self.plan()
        plan['days'][0]['timeline'] = [{'type':'lunch','entity_id':'restaurant-1',
            'start':'12:00','end':'13:00'}]
        task = {'uid':'E01','additional_constraints':[], 'meal_policy':{
            'required_slots':[{'date':'2026-10-28','slot':'lunch'}]}}
        slots = copy.deepcopy(task['meal_policy']['required_slots'])
        events = [{'date':'2026-10-28','item_index':0,'type':'lunch',
                   'entity_id':'restaurant-1','event_id':'e1','slot':'lunch'}]
        result = diagnose_p31_plan(plan, task=task, now='2026-10-30T00:00:00Z',
            registry={}, meal_coverage={'required_slots':slots,'events':events},
            meal_policy_verifier=lambda bound_task, required: (
                bound_task.get('uid') == 'E01' and
                required == bound_task.get('meal_policy',{}).get('required_slots')),
            meal_inventory_verifier=lambda *_:True,
            meal_event_verifier=lambda _:True)
        self.assertEqual(result['meal_coverage_check']['state'],'pass')
        self.assertTrue(any(g.get('reason') == 'chronology_and_coverage_unverified'
                            for g in result['axes']['adapter']))

        no_policy = diagnose_p31_plan(plan, now='2026-10-30T00:00:00Z', registry={},
            meal_coverage={'required_slots':slots,'events':events},
            meal_policy_verifier=lambda *_:True,
            meal_inventory_verifier=lambda *_:True, meal_event_verifier=lambda _:True)
        self.assertEqual(no_policy['meal_coverage_check']['state'],'unknown')
        self.assertEqual(no_policy['meal_coverage_check']['reason'],
                         'meal_required_slots_not_bound_to_task_policy')

    def test_overnight_scope_is_forwarded_and_bound_to_plan_timeline(self):
        plan = self.plan()
        day1, day2 = copy.deepcopy(plan['days'][0]), copy.deepcopy(plan['days'][0])
        day1['date'], day2['date'] = '2026-10-28', '2026-10-29'
        day1['timeline'] = [{'type':'visit', 'entity_id':'hotel', 'entrance_id':'lobby',
                             'start':'20:00:00+08:00', 'end':'22:00:00+08:00'}]
        day2['timeline'] = [{'type':'visit', 'entity_id':'hotel', 'entrance_id':'lobby',
                             'start':'08:00:00+08:00', 'end':'09:00:00+08:00'}]
        plan['days'] = [day1, day2]
        req = {'entity_id':'hotel','room_type':'twin','check_in':'2026-10-28',
            'check_out':'2026-10-29','rooms':1,'guests_per_room':2,'minimum_beds':2,
            'eligibility':'standard','meal_plan':'none','taxes_included':True,
            'mandatory_fees_included':True}
        claim = {'entity_id':'hotel','room_type':'twin','check_in':'2026-10-28',
            'check_out':'2026-10-29','guests_per_room':2,'currency':'CNY',
            'unit':'CNY/room/night','rate':200,'beds':2,'max_guests_per_room':2,
            'eligibility':'standard','meal_plan':'none','taxes_included':True,
            'mandatory_fees_included':True}
        boundary = {'previous_day':'2026-10-28','next_day':'2026-10-29',
            'last_endpoint':{'entity_id':'hotel','entrance_id':'lobby',
                             'datetime':'2026-10-28T22:00:00+08:00'},
            'first_endpoint':{'entity_id':'hotel','entrance_id':'lobby',
                              'datetime':'2026-10-29T08:00:00+08:00'},
            'lodging_entrance_id':'lobby','lodging_requirement':req,
            'lodging_claim':claim}
        result = diagnose_p31_plan(plan, now='2026-10-30T00:00:00Z', registry={},
            overnight_boundaries=[boundary], overnight_fact_verifier=lambda *_: True,
            overnight_lodging_verifier=lambda *_: True)
        self.assertEqual(result['overnight_checks']['state'], 'pass')
        self.assertIn('itinerary_overnight_continuity',
                      [x['field'] for x in result['passed_checks']])
        self.assertTrue(any(g.get('reason') == 'chronology_and_coverage_unverified'
                            for g in result['axes']['adapter']))

        forged = copy.deepcopy(boundary)
        forged['first_endpoint']['datetime'] = '2026-10-29T07:00:00+08:00'
        result = diagnose_p31_plan(plan, now='2026-10-30T00:00:00Z', registry={},
            overnight_boundaries=[forged], overnight_fact_verifier=lambda *_: True,
            overnight_lodging_verifier=lambda *_: True)
        self.assertEqual(result['overnight_checks']['state'], 'unknown')
        self.assertEqual(result['overnight_checks']['reason'],
                         'overnight_boundary_not_bound_to_itinerary')

    def test_compiled_tag_constraint_keeps_scope_in_task_mapping(self):
        plan = self.plan()
        tag = {'id':'night','strength':'hard','scope':{'domain':'trip','quantifier':'all'},
               'compiler_status':'supported','expression':{'op':'exclude_tag','args':{'tag':'restricted_tag'}}}
        task={'uid':'E01','additional_constraints':[tag]}
        evidence={'night':{'scope_items':['one'], 'tag_facts':[{'item_id':'one',
                  'tag':'restricted_tag','present':True,'scope':{'domain':'trip'}}]}}
        result=diagnose_p31_plan(plan,task=task,now='2026-10-30T00:00:00Z',registry={},
            tag_evidence=evidence,tag_scope_verifier=lambda *_:True,constraint_fact_verifier=lambda *_:True)
        self.assertIn('constraint:night',[x['field'] for x in result['hard_failures']])
        self.assertFalse(result['execution_confirmed'])
    @classmethod
    def setUpClass(cls):
        cls.real_task = json.loads((ROOT / 'results/p31_five_city_96/tasks/easy.json')
                                   .read_text(encoding='utf-8'))[0]

    def plan(self):
        return {
            'uid': 'E01', 'level': 'easy',
            'days': [{'date': '2026-10-28', 'city': '西安',
                      'timeline': [
                          {'type': 'travel', 'from': '西安北站', 'to': '景点',
                           'start': '09:00', 'end': '09:33', 'minutes': 33,
                           'status': 'estimate'},
                          {'type': 'visit', 'entity': '景点', 'start': '09:33',
                           'end': '11:33', 'minutes': 120,
                           'opening_status': 'known'}]}],
            'static': {'known_cost': 1, 'transit_estimate': 10,
                       'budget_limit': 100, 'budget_ok_static': True},
        }

    def test_p31_estimated_route_known_open_and_static_budget_stay_unknown(self):
        plan = self.plan()
        result = diagnose_p31_plan(plan, now='2026-10-30T00:00:00Z', registry={})
        self.assertEqual(result['outcome'], 'data_block')
        checks = {x['field']: x['state'] for x in result['unknown_checks']}
        self.assertEqual(checks['opening_hours'], 'unknown')
        self.assertEqual(checks['route'], 'unknown')
        self.assertEqual(checks['budget'], 'unknown')
        self.assertFalse(result['truth_certified'])
        self.assertFalse(result['execution_confirmed'])

    def test_legacy_feasible_flags_do_not_change_diagnostic(self):
        first = self.plan()
        second = self.plan()
        second['days'][0]['feasible'] = True
        second['static']['budget_ok_static'] = True
        second['days'][0]['timeline'][0]['status'] = 'verified'
        a = diagnose_p31_plan(first, now='2026-10-30T00:00:00Z', registry={})
        b = diagnose_p31_plan(second, now='2026-10-30T00:00:00Z', registry={})
        self.assertEqual([(x['field'], x['state']) for x in a['unknown_checks']],
                         [(x['field'], x['state']) for x in b['unknown_checks']])

    def test_malformed_plan_is_pipeline_error(self):
        result = diagnose_p31_plan({'uid': 'bad', 'level': 'easy'},
                                   now='2026-10-30T00:00:00Z', registry={})
        self.assertTrue(result['axes']['pipeline'])
        self.assertEqual(result['axes']['pipeline'][0]['reason'], 'plan_days_missing')
        self.assertFalse(result['execution_confirmed'])

    def test_all_activities_meals_and_routes_are_diagnosed(self):
        plan = self.plan()
        timeline = plan['days'][0]['timeline']
        timeline.insert(2, {'type': 'lunch', 'start': '12:00', 'end': '13:00',
                            'cost': 0, 'status': 'verified'})
        result = diagnose_p31_plan(plan, now='2026-10-30T00:00:00Z', registry={})
        checks = result['unknown_checks']
        # One activity check per place, one route check per travel leg, and
        # one aggregate budget check for the plan.
        self.assertEqual(sum(x['field'] == 'opening_hours' for x in checks), 2)
        self.assertEqual(sum(x['field'] == 'route' for x in checks), 1)
        self.assertEqual(sum(x['field'] == 'budget' for x in checks), 1)
        self.assertIn('itinerary_chronology_and_coverage', [x['field'] for x in checks])
        self.assertFalse(result['truth_certified'])
        self.assertFalse(result['execution_confirmed'])

    def test_malformed_later_meal_does_not_hide_behind_first_visit(self):
        plan = self.plan()
        plan['days'][0]['timeline'].append({'type': 'dinner', 'start': 'bad', 'end': '20:00'})
        result = diagnose_p31_plan(plan, now='2026-10-30T00:00:00Z', registry={})
        self.assertEqual(result['axes']['pipeline'][0]['reason'], 'activity_interval_malformed')

    def test_unknown_timeline_type_fails_closed(self):
        plan = self.plan()
        plan['days'][0]['timeline'].append({'type': 'museum_transfer', 'start': '12:00', 'end': '13:00'})
        result = diagnose_p31_plan(plan, now='2026-10-30T00:00:00Z', registry={})
        self.assertEqual(result['axes']['adapter'][0]['reason'], 'timeline_type_unsupported')

    def test_backwards_activity_interval_fails_closed(self):
        plan = self.plan()
        plan['days'][0]['timeline'][1]['start'] = '12:00'
        plan['days'][0]['timeline'][1]['end'] = '11:00'
        result = diagnose_p31_plan(plan, now='2026-10-30T00:00:00Z', registry={})
        self.assertEqual(result['axes']['pipeline'][0]['reason'], 'activity_interval_malformed')

    def test_nonstandard_second_day_shape_is_adapter_block(self):
        plan = self.plan()
        plan['days'].append({'date': '2026-10-29', 'city': '厦门',
                             'visit_start': '14:00', 'visit_end': '15:00'})
        result = diagnose_p31_plan(plan, now='2026-10-30T00:00:00Z', registry={})
        self.assertIn('day_timeline_unsupported', [g['reason'] for g in result['axes']['adapter']])

    def test_native_multiday_fields_keep_day_one_checks_and_add_adapter_gaps(self):
        plan = self.plan()
        plan['level'] = 'medium'
        plan['days'].append({'date': '2026-10-29', 'city': '厦门',
            'departure': '11:00', 'arrival': '13:00', 'intercity': '估算列车',
            'old_attraction': '旧城景点', 'visit_start': '14:00', 'visit_end': '15:00',
            'feasible': True, 'reasons': []})
        result = diagnose_p31_plan(plan, now='2026-10-30T00:00:00Z', registry={})
        reasons = [x['reason'] for x in result['axes']['adapter']]
        self.assertGreaterEqual(reasons.count('p31_multiday_field_unverified'), 5)
        departure_gap = next(g for g in result['axes']['adapter']
                             if g['reason'] == 'p31_multiday_field_unverified'
                             and g['detail']['fields'] == ['departure'])
        self.assertEqual(departure_gap['detail']['unverified_values']['departure'], '11:00')
        self.assertEqual(result['level'], 'medium')
        self.assertEqual(sum(x['field'] == 'opening_hours' for x in result['unknown_checks']), 2)
        self.assertEqual(sum(x['field'] == 'route' for x in result['unknown_checks']), 1)
        self.assertIn('itinerary_chronology_and_coverage', [x['field'] for x in result['unknown_checks']])
        self.assertFalse(result['execution_confirmed'])

    def test_evidence_auditor_forwarding_and_audit_survive_task_merge(self):
        plan = self.plan()
        plan['level'] = 'human'
        task = {'uid': 'E01', 'constraints': {'budget': 100}}
        expected = {'claim_id': 'c1', 'field': 'price', 'state': 'recorded'}
        auditor = lambda *_: {'state': 'recorded'}
        base = {'uid':'strict-p31:E01', 'city':'西安', 'level':'human', 'axes':{},
                'hard_failures':[], 'unknown_checks':[], 'soft_checks':[],
                'evidence_audits':[expected], 'outcome':'solver_incomplete'}
        with patch('shorttrip.strict_p31_bridge.diagnose_plan', return_value=base) as mocked:
            result = diagnose_p31_plan(plan, task=task, evidence_auditor=auditor,
                now='2026-10-30T00:00:00Z', registry={})
        self.assertIs(mocked.call_args.kwargs['evidence_auditor'], auditor)
        self.assertEqual(mocked.call_args.kwargs['level'], 'human')
        self.assertEqual(result['level'], 'human')
        self.assertEqual(result['evidence_audits'], [expected])

    def test_wait_is_not_an_unsupported_activity(self):
        plan = self.plan()
        plan['days'][0]['timeline'].insert(1, {'type':'wait', 'start':'09:33', 'end':'09:40'})
        result = diagnose_p31_plan(plan, now='2026-10-30T00:00:00Z', registry={})
        self.assertEqual(result['axes']['pipeline'], [])
        self.assertEqual(sum(x['field'] == 'opening_hours' for x in result['unknown_checks']), 1)

    def test_non_object_timeline_item_fails_closed(self):
        plan = self.plan()
        plan['days'][0]['timeline'].append('unparsed legacy marker')
        result = diagnose_p31_plan(plan, now='2026-10-30T00:00:00Z', registry={})
        self.assertEqual(result['axes']['pipeline'][0]['reason'], 'timeline_item_malformed')

    def test_actual_p31_task_constraints_join_candidate_diagnostic(self):
        task = copy.deepcopy(self.real_task)
        plan = build_plan(task)
        result = diagnose_p31_plan(plan, task=task, now='2026-10-30T00:00:00Z', registry={})
        self.assertEqual(result['p31_constraint_mapping']['task_uid'], task['uid'])
        checks = {x['field']: x for x in result['unknown_checks']}
        self.assertEqual(checks['constraint:p31:budget']['strength'], 'unclassified')
        self.assertEqual(checks['constraint:p31:budget']['state'], 'unknown')
        self.assertIn('itinerary_chronology_and_coverage', [x['field'] for x in result['unknown_checks']])
        self.assertEqual(result['itinerary_checks']['chronology']['state'], 'unknown')
        self.assertEqual(result['itinerary_checks']['continuity']['state'], 'unknown')
        checks = {x['field']: x['state'] for x in result['unknown_checks']}
        self.assertEqual(checks['itinerary_chronology'], 'unknown')
        self.assertEqual(checks['itinerary_continuity'], 'unknown')
        self.assertTrue(result['axes']['solver'])
        self.assertFalse(result['truth_certified'])
        self.assertFalse(result['execution_confirmed'])

    def test_independently_verified_timeline_does_not_verify_route_or_budget(self):
        plan = self.plan()
        travel = plan['days'][0]['timeline'][0]
        travel.update({'origin_id':'station-1','origin_entrance_id':'east',
                       'destination_id':'poi-1','destination_entrance_id':'main'})
        visit = plan['days'][0]['timeline'][1]
        visit.update({'entity_id':'poi-1','entrance_id':'main'})
        result = diagnose_p31_plan(plan, now='2026-10-30T00:00:00Z', registry={},
            itinerary_interval_verifier=lambda fact: True,
            itinerary_endpoint_verifier=lambda fact: True)
        checks = {x['field']: x['state'] for x in result['unknown_checks']}
        self.assertEqual(result['itinerary_checks']['chronology']['state'], 'pass')
        self.assertEqual(result['itinerary_checks']['continuity']['state'], 'pass')
        self.assertEqual(checks['route'], 'unknown')
        self.assertEqual(checks['budget'], 'unknown')
        self.assertNotEqual(result['outcome'], 'complete_under_declared_policy')

    def test_explicit_hard_and_soft_constraints_keep_distinction_in_final_report(self):
        task = copy.deepcopy(self.real_task)
        task['additional_constraints'] = [
            {'id': 'at-least-three', 'strength': 'hard', 'compiler_status': 'supported',
             'expression': {'op': 'count_at_least', 'args': {'kind': 'attraction', 'count': 3}}},
            {'id': 'local-meal', 'strength': 'soft', 'compiler_status': 'supported',
             'expression': {'op': 'count_at_least', 'args': {'kind': 'restaurant', 'count': 1}}},
        ]
        result = diagnose_p31_plan(build_plan(task), task=task,
            now='2026-10-30T00:00:00Z', registry={})
        self.assertIn('constraint:at-least-three', [x['field'] for x in result['unknown_checks']])
        self.assertIn('constraint:local-meal', [x['field'] for x in result['soft_checks']])
        self.assertNotIn('constraint:local-meal', [x['field'] for x in result['unknown_checks']])
        self.assertIn('solver', result['axes'])
        self.assertFalse(result['execution_confirmed'])

    def test_unmapped_hard_constraint_adds_adapter_gap(self):
        task = copy.deepcopy(self.real_task)
        task['additional_constraints'] = [
            {'id': 'mode', 'strength': 'hard', 'compiler_status': 'unmapped',
             'expression': {'op': 'prefer_mode', 'args': {'mode': 'public_transit'}}},
        ]
        result = diagnose_p31_plan(build_plan(task), task=task,
            now='2026-10-30T00:00:00Z', registry={})
        self.assertTrue(any(g.get('gap_id', '').endswith(':mode')
                            for g in result['axes']['adapter']))
        self.assertNotEqual(result['outcome'], 'complete_under_declared_policy')

    def test_missing_or_mismatched_task_context_fails_closed(self):
        plan = self.plan()
        missing = diagnose_p31_plan(plan, task={'constraints': {}},
            now='2026-10-30T00:00:00Z', registry={})
        self.assertEqual(missing['axes']['adapter'][0]['reason'], 'task_uid_missing')
        mismatch = diagnose_p31_plan(plan, task={'uid': 'different', 'constraints': {}},
            now='2026-10-30T00:00:00Z', registry={})
        self.assertEqual(mismatch['axes']['adapter'][0]['reason'], 'task_plan_uid_mismatch')

    def test_task_bound_cost_aggregation_is_additive_and_preserves_p31_unknown_budget(self):
        from shorttrip.strict_constraint_compiler import compile_constraint
        constraint = compile_constraint({'id':'trip-budget','strength':'hard',
            'compiler_status':'supported',
            'scope':{'currency':'CNY','people':2,'unit':'total_trip_cost'},
            'expression':{'op':'total_cost_at_most','args':{'CNY':1000,'people':2,
                                                            'includes':['tickets','transport']}}})['constraint']
        task = {'uid':'E01','target_city':'西安','start_date':'2026-10-28','days':1,
                'constraints':{},'additional_constraints':[constraint]}
        plan = self.plan()
        plan['days'][0]['timeline'][0]['entity_id'] = 'route-entity'
        plan['days'][0]['timeline'][1]['entity_id'] = 'attraction-entity'
        trip_scope = {'task_uid':'E01','plan_uid':'E01','target_city':'西安',
                      'itinerary_dates':['2026-10-28']}
        components = [
            {'category':'tickets','amount':400,'currency':'CNY','party_size':2,
             'scope':trip_scope,'evidence':{'evidence_id':'hotel'},'expense_ids':['hotel-1'],
             'occurrence_bindings':[{'expense_id':'hotel-1','day_index':0,'item_index':1,
                'date':'2026-10-28','type':'visit','entity_id':'attraction-entity'}]},
            {'category':'transport','amount':100,'currency':'CNY','party_size':2,
             'scope':trip_scope,'evidence':{'evidence_id':'fare'},'expense_ids':['fare-1'],
             'occurrence_bindings':[{'expense_id':'fare-1','day_index':0,'item_index':0,
                'date':'2026-10-28','type':'travel','entity_id':'route-entity'}]}]
        cost_input = {'constraint_id':'trip-budget','policy':{
            'required_categories':['tickets','transport'],'currency':'CNY',
            'party_size':2,'total_limit':1000,'trip_scope':trip_scope},
            'components':components,
            'scope':trip_scope}
        def verify_cost_context(context, actual_task, actual_plan, actual_constraint,
                                policy, components, scope):
            return (context['task_uid'] == actual_task['uid'] == actual_plan['uid'] and
                    context['target_city'] == actual_task['target_city'] == actual_plan['days'][-1]['city'] and
                    actual_constraint['id'] == cost_input['constraint_id'] and
                    policy['trip_scope'] == scope == context and len(components) == 2)
        result = diagnose_p31_plan(plan,task=task,now='2026-10-30T00:00:00Z',registry={},
            cost_aggregation=cost_input,cost_evidence_verifier=lambda *_:True,
            cost_inventory_verifier=lambda *_:True,cost_context_verifier=verify_cost_context,
            constraint_fact_verifier=lambda *_:True)
        self.assertEqual(result['trip_cost_aggregation_check']['state'],'pass')
        self.assertIn('budget',[x['field'] for x in result['unknown_checks']])
        self.assertIn('constraint:trip-budget',[x['field'] for x in result['unknown_checks']])
        self.assertIn('trip_cost_aggregation',[x['field'] for x in result['passed_checks']])
        self.assertFalse(result['truth_certified'])

    def test_p31_cost_input_without_unique_task_constraint_or_verifiers_is_unknown(self):
        trip_scope = {'task_uid':'E01','plan_uid':'E01','target_city':'西安',
                      'itinerary_dates':['2026-10-28']}
        cost_input = {'constraint_id':'budget','policy':{'required_categories':['hotel'],
            'currency':'CNY','party_size':1,'total_limit':20,'trip_scope':trip_scope},
            'components':[],'scope':trip_scope}
        no_constraint = diagnose_p31_plan(self.plan(),task={'uid':'E01','additional_constraints':[]},
            now='2026-10-30T00:00:00Z',registry={},cost_aggregation=cost_input)
        self.assertEqual(no_constraint['trip_cost_aggregation_check']['state'],'unknown')
        self.assertEqual(no_constraint['trip_cost_aggregation_check']['reason'],'budget_constraint_missing')

        from shorttrip.strict_constraint_compiler import compile_constraint
        constraint = compile_constraint({'id':'budget','strength':'hard','compiler_status':'supported',
            'scope':{'currency':'CNY','people':1,'unit':'total_trip_cost'},
            'expression':{'op':'total_cost_at_most','args':{'CNY':20,'people':1,'includes':['hotel']}}})['constraint']
        task = {'uid':'E01','target_city':'西安','start_date':'2026-10-28','days':1,
                'additional_constraints':[constraint]}
        valid_cost_input = {'constraint_id':'budget','policy':{'required_categories':['hotel'],
            'currency':'CNY','party_size':1,'total_limit':20,'trip_scope':trip_scope},
            'components':[{'category':'hotel','amount':10,'currency':'CNY','party_size':1,
                           'scope':trip_scope,'evidence':{'evidence_id':'hotel'},'expense_ids':['hotel-1']}], 'scope':trip_scope}
        no_verifiers = diagnose_p31_plan(self.plan(),task=task,now='2026-10-30T00:00:00Z',
            registry={},cost_aggregation=valid_cost_input)
        self.assertEqual(no_verifiers['trip_cost_aggregation_check']['state'],'unknown')
        self.assertIn('budget',[x['field'] for x in no_verifiers['unknown_checks']])

        mismatched_task = {**task, 'start_date':'2026-10-29'}
        mismatched_dates = diagnose_p31_plan(self.plan(),task=mismatched_task,
            now='2026-10-30T00:00:00Z',registry={},cost_aggregation=valid_cost_input,
            cost_evidence_verifier=lambda *_:True,cost_inventory_verifier=lambda *_:True,
            cost_context_verifier=lambda *_:True,constraint_fact_verifier=lambda *_:True)
        self.assertEqual(mismatched_dates['trip_cost_aggregation_check']['state'],'unknown')

    def test_p31_forwards_raw_intercity_manifest_and_verifiers_with_actual_task_plan(self):
        from tests.test_strict_intercity_budget_integration import make_input, callbacks
        from shorttrip.strict_constraint_compiler import compile_constraint
        task, plan, manifest, scope, component, policy = make_input()
        constraint = compile_constraint({'id':'intercity-budget','strength':'hard',
            'scope':{'currency':'CNY','people':2,'unit':'total_trip_cost'},
            'expression':{'op':'total_cost_at_most','args':{'CNY':500,'people':2,
                                                            'includes':['intercity']}}})['constraint']
        task['additional_constraints'] = [constraint]
        task['constraints'] = {}
        plan['level'] = 'easy'
        for day in plan['days']:
            for item in day['timeline']:
                if item['type'] == 'travel':
                    item['start'] = item['departure_time'] + item['clock_zone']
                    item['end'] = item['arrival_time'] + item['clock_zone']
                else:
                    item['start'], item['end'] = '10:00', '11:00'
        cost_input = {'constraint_id':'intercity-budget','policy':policy,
                      'components':[component],'scope':scope,
                      'intercity_manifest':manifest}
        result = diagnose_p31_plan(plan, task=task, now='2026-10-30T00:00:00Z',
            registry={}, cost_aggregation=cost_input,
            cost_evidence_verifier=lambda *_: True,
            cost_inventory_verifier=lambda *_: True,
            cost_context_verifier=lambda *_: True,
            constraint_fact_verifier=lambda *_: True,
            **{'cost_' + key: value for key, value in callbacks().items()})
        self.assertEqual(result['trip_cost_aggregation_check']['state'], 'pass')

        task.pop('intercity_policy')
        unknown = diagnose_p31_plan(plan, task=task, now='2026-10-30T00:00:00Z',
            registry={}, cost_aggregation=cost_input,
            cost_evidence_verifier=lambda *_: True,
            cost_inventory_verifier=lambda *_: True,
            cost_context_verifier=lambda *_: True,
            constraint_fact_verifier=lambda *_: True,
            **{'cost_' + key: value for key, value in callbacks().items()})
        self.assertEqual(unknown['trip_cost_aggregation_check']['state'], 'unknown')


if __name__ == '__main__':
    unittest.main()
