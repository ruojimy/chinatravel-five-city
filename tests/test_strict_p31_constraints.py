import copy
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from p31_static import build_plan
from shorttrip.strict_p31_constraints import (
    diagnose_p31_task_constraints, map_p31_task_constraints,
)


class StrictP31ConstraintBridgeTests(unittest.TestCase):
    def test_additional_constraint_fields_are_not_silently_dropped(self):
        task = {'uid':'task-1', 'nature_language':'禁止米其林餐厅',
            'additional_constraints':[{'id':'x', 'strength':'hard',
                'scope':{'domain':'trip','quantifier':'all'}, 'compiler_status':'supported',
                'expression':{'op':'exclude_tag','args':{'tag':'night'}},
                'qualifier':'must_not_be_discarded'}]}
        result = map_p31_task_constraints(task)
        self.assertFalse(result['constraints'])
        self.assertEqual(result['unresolved'][0]['reason'], 'constraint_has_unsupported_fields')
        self.assertFalse(result['natural_language_equivalence_verified'])

    def test_mutated_candidate_returns_pipeline_error_with_soft_checks_shape(self):
        candidate = self.candidate()
        def mutate(*_args):
            candidate['required_costs'][0] = 1
            return True
        candidate['cost_verifier'] = mutate
        task = {'uid':'task-1', 'constraints':{'preference':{'strength':'soft'}}}
        result = diagnose_p31_task_constraints(task, city='X', record_requirements=[], registry={},
            now='2026-10-30T00:00:00Z', candidate=candidate)
        self.assertEqual(result['outcome'], 'pipeline_error')
        self.assertEqual(len(result['soft_checks']), 1)
        self.assertFalse(result['passed_checks'])

    def test_unknown_uid_and_mixed_native_keys_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'task_uid_missing'):
            map_p31_task_constraints({'uid':'unknown'})
        bundle = map_p31_task_constraints({'uid':'task-1', 'constraints':{'budget':100, 1:'bad'}})
        self.assertFalse(bundle['constraints'])
        self.assertEqual(bundle['unresolved'][0]['reason'], 'native_constraints_key_invalid')

    @classmethod
    def setUpClass(cls):
        path = ROOT / 'results/p31_five_city_96/tasks/easy.json'
        cls.task = json.loads(path.read_text(encoding='utf-8'))[0]

    def candidate(self):
        return {
            'activity': {'start': datetime(2026, 10, 30, 10),
                         'end': datetime(2026, 10, 30, 11), 'windows': None},
            'route_requirement': {'context': {}}, 'route_evidence': {},
            'required_costs': [None], 'budget': None,
        }

    def test_real_p31_task_constraints_remain_unknown_without_scope(self):
        task = copy.deepcopy(self.task)
        plan = build_plan(task)  # Actual static P31 generator input/output path.
        bundle = map_p31_task_constraints(task)
        self.assertEqual(bundle['task_uid'], plan['uid'])
        self.assertEqual(bundle['constraints'], [])
        native = {item['id'].removeprefix('p31:'): item for item in bundle['unresolved']}
        self.assertIn('budget', native)
        self.assertEqual(native['budget']['value'], task['constraints']['budget'])
        self.assertEqual(native['budget']['strength'], 'unclassified')
        self.assertEqual(native['budget']['state'], 'unknown')

        result = diagnose_p31_task_constraints(task, city=task['city_sequence'][0],
            record_requirements=[], registry={}, now='2026-10-30T00:00:00Z',
            candidate=self.candidate())
        budget = next(x for x in result['unknown_checks'] if x['field'] == 'constraint:p31:budget')
        self.assertEqual(budget['state'], 'unknown')
        self.assertEqual(budget['strength'], 'unclassified')
        self.assertTrue(any(g['reason'] == 'native_p31_constraint_not_compiled' and
                            g['constraint_strength'] == 'unclassified'
                            for g in result['axes']['adapter']))
        self.assertFalse(result['execution_confirmed'])
        self.assertEqual(result['p31_constraint_mapping']['task_uid'], task['uid'])

    def test_explicit_hard_and_soft_constraints_keep_distinction(self):
        task = copy.deepcopy(self.task)
        task['additional_constraints'] = [
            {'id': 'hard-count', 'strength': 'hard', 'compiler_status': 'supported',
             'expression': {'op': 'count_at_least', 'args': {'kind': 'attraction', 'count': 3}}},
            {'id': 'soft-count', 'strength': 'soft', 'compiler_status': 'supported',
             'expression': {'op': 'count_at_least', 'args': {'kind': 'restaurant', 'count': 1}}},
        ]
        result = diagnose_p31_task_constraints(task, city=task['city_sequence'][0],
            record_requirements=[], registry={}, now='2026-10-30T00:00:00Z',
            candidate=self.candidate())
        hard = [x for x in result['unknown_checks'] if x['field'] == 'constraint:hard-count']
        soft = [x for x in result['soft_checks'] if x['field'] == 'constraint:soft-count']
        self.assertEqual(len(hard), 1)
        self.assertEqual(len(soft), 1)
        self.assertTrue(any(g['reason'] == 'constraint_compile_validation_failed'
                            for g in result['axes']['adapter']))

    def test_unmapped_hard_operator_is_not_promoted_to_strict_check(self):
        task = copy.deepcopy(self.task)
        task['additional_constraints'] = [
            {'id': 'arrival', 'strength': 'hard', 'compiler_status': 'unmapped',
             'expression': {'op': 'return_before_train', 'args': {'time': '18:00'}}},
        ]
        result = diagnose_p31_task_constraints(task, city=task['city_sequence'][0],
            record_requirements=[], registry={}, now='2026-10-30T00:00:00Z',
            candidate=self.candidate())
        entry = next(x for x in result['p31_constraint_mapping']['unresolved']
                     if x['id'] == 'arrival')
        self.assertEqual(entry['strength'], 'hard')
        self.assertEqual(entry['state'], 'unknown')
        check = next(x for x in result['unknown_checks'] if x['field'] == 'constraint:arrival')
        self.assertEqual(check['state'], 'unknown')
        self.assertEqual(check['strength'], 'hard')

    def test_unmapped_soft_constraint_stays_out_of_hard_unknown_checks(self):
        task = copy.deepcopy(self.task)
        task['additional_constraints'] = [
            {'id': 'soft-route', 'strength': 'soft', 'compiler_status': 'unmapped',
             'expression': {'op': 'prefer_mode', 'args': {'mode': 'public_transit'}}},
        ]
        result = diagnose_p31_task_constraints(task, city=task['city_sequence'][0],
            record_requirements=[], registry={}, now='2026-10-30T00:00:00Z',
            candidate=self.candidate())
        check = next(x for x in result['soft_checks'] if x['field'] == 'constraint:soft-route')
        self.assertEqual(check['strength'], 'soft')
        self.assertNotIn('constraint:soft-route', [x['field'] for x in result['unknown_checks']])

    def test_malformed_native_constraint_container_is_retained_as_unknown(self):
        task = copy.deepcopy(self.task)
        task['constraints'] = ['not-a-supported-object']
        bundle = map_p31_task_constraints(task)
        self.assertEqual(bundle['unresolved'][-1]['reason'], 'native_constraints_shape_unsupported')
        self.assertEqual(bundle['unresolved'][-1]['value'], ['not-a-supported-object'])

    def test_missing_task_uid_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'task_uid_missing'):
            map_p31_task_constraints({'constraints': {'budget': 100}})


if __name__ == '__main__':
    unittest.main()
