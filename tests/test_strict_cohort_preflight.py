import unittest
from shorttrip.strict_cohort_preflight import preflight, validate_freeze_readiness


class PreflightTests(unittest.TestCase):
    def test_schema_example_cannot_be_frozen_as_formal(self):
        import json
        from pathlib import Path
        path=Path(__file__).resolve().parents[1]/'collector_agent/examples/query_templates.json'
        examples=json.loads(path.read_text(encoding='utf-8'))
        with self.assertRaises(ValueError):
            validate_freeze_readiness(examples)

    def test_syntax_supported_alone_cannot_bypass_missing_full_evaluator(self):
        import json
        from pathlib import Path
        path=Path(__file__).resolve().parents[1]/'collector_agent/examples/query_templates.json'
        item=json.loads(path.read_text(encoding='utf-8'))[0]
        item['purpose']=item['split']='development'
        item['additional_constraints'][0]['scope']={'currency':'CNY','people':2,'unit':'total_trip_cost'}
        item['additional_constraints'][0]['compiler_status']='supported'
        with self.assertRaisesRegex(ValueError, 'full strict planner'):
            validate_freeze_readiness([item])
    def test_empty_sets_cannot_become_a_formal_cohort(self):
        out = preflight([], [])
        self.assertFalse(out['freeze_approved'])
        self.assertIn('complete_planner_and_independent_evidence_verifier_not_integrated',
                      [x['reason'] for x in out['blockers']])
        self.assertTrue(any(x['reason'] == 'kind_coverage_missing' for x in out['blockers']))

    def test_cross_split_reuse_and_unsupported_operators_are_reported(self):
        def task(split):
            return {'uid': split, 'level': 'human', 'target_city': '西安', 'split': split,
                    'purpose': split, 'required_kinds': ['attraction'],
                    'candidate_selection': {'required_entity_ids': ['same']},
                    'additional_constraints': [{'id':'x', 'expression':{'op':'implies'},
                                                'compiler_status':'unmapped'}]}
        out = preflight([task('development')], [task('holdout')])
        reasons = [x['reason'] for x in out['blockers']]
        self.assertIn('development_holdout_candidate_overlap', reasons)
        self.assertIn('operator_unsupported', reasons)
        self.assertIn('constraint_not_compiled', reasons)

    def test_tag_scope_must_point_to_a_required_kind(self):
        def task(split):
            return {'uid': split, 'level': 'human', 'target_city': '西安', 'split': split,
                    'purpose': split, 'required_kinds': ['attraction'],
                    'candidate_selection': {'required_entity_ids': [split]},
                    'additional_constraints': [{'id':'food', 'strength':'soft',
                        'scope': {'domain':'trip','quantifier':'any','item_kind':'restaurant'},
                        'expression': {'op':'prefer_tag','args':{'tag':'local_food'}},
                        'compiler_status':'unmapped'}]}
        out = preflight([task('development')], [task('holdout')])
        self.assertIn('tag_item_kind_not_required', [x['reason'] for x in out['blockers']])


if __name__ == '__main__':
    unittest.main()
