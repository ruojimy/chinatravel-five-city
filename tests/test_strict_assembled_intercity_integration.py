"""Synthetic structural integration; callbacks here do not establish facts."""
import copy
import unittest

from shorttrip.strict_plan_assembler import assemble_strict_plan
from shorttrip.strict_trip_cost_aggregation import aggregate_trip_costs
from shorttrip.strict_constraint_compiler import compile_constraint
from shorttrip.strict_p31_bridge import diagnose_p31_plan
from tests.test_strict_plan_assembler import inputs
from tests.test_strict_intercity_budget_integration import callbacks, make_input


class AssembledIntercityIntegrationTests(unittest.TestCase):
    def test_explicit_segments_reach_cost_check_with_aware_timeline(self):
        task, _, manifest, scope, component, policy = make_input()
        context, days, kinds, repeat = inputs()
        context.update(uid=task['uid'], target_city=task['target_city'])
        for day in days:
            day['city'] = task['target_city']
            for event in day['timeline']:
                if event['type'] == 'travel':
                    event['entity_id'] = 'synthetic-' + event['occurrence_id']
        _, sidecar, _, _, _, _ = make_input()
        for index, segment in ((0, sidecar['intercity_segments'][0]),
                               (2, sidecar['intercity_segments'][1])):
            timeline = days[index]['timeline']
            timeline[0].update(start='09:00:00+08:00', end='11:00:00+08:00',
                               intercity_segment=copy.deepcopy(segment))
            timeline[1].update(start='11:00:00+08:00', end='11:30:00+08:00')
            timeline[2].update(start='11:30:00+08:00', end='12:00:00+08:00')
            timeline[3].update(start='12:00:00+08:00', end='12:30:00+08:00')
        assembled = assemble_strict_plan(context, days, entity_kinds=kinds, repeat_policy=repeat)
        self.assertEqual(assembled['status'], 'synthetic_plan_assembled_unverified')
        result = aggregate_trip_costs(policy, [component], scope=scope, task=task,
            plan=assembled['plan'], evidence_verifier=lambda *_: True,
            inventory_verifier=lambda *_: True, intercity_manifest=manifest,
            **callbacks())
        self.assertEqual(result['status'], 'arithmetic_evaluated', result)
        self.assertEqual(result['total_decimal'], '401.00')
        self.assertFalse(assembled['facts_verified'])
        task['additional_constraints'] = [compile_constraint({
            'id': 'intercity-budget', 'strength': 'hard',
            'scope': {'currency': 'CNY', 'people': 2, 'unit': 'total_trip_cost'},
            'expression': {'op': 'total_cost_at_most',
                           'args': {'CNY': 500, 'people': 2, 'includes': ['intercity']}}})['constraint']]
        task['constraints'] = {}
        p31 = diagnose_p31_plan(assembled['plan'], task=task, now='2026-10-30T00:00:00Z',
            registry={}, cost_aggregation={'constraint_id': 'intercity-budget', 'policy': policy,
                'components': [component], 'scope': scope, 'intercity_manifest': manifest},
            cost_evidence_verifier=lambda *_: True, cost_inventory_verifier=lambda *_: True,
            cost_context_verifier=lambda *_: True, constraint_fact_verifier=lambda *_: True,
            **{'cost_' + key: value for key, value in callbacks().items()})
        self.assertEqual(p31['trip_cost_aggregation_check']['state'], 'pass')
        self.assertTrue(p31['axes']['solver'] or p31['axes']['adapter'])

