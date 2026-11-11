import unittest
from shorttrip.strict_gap_queue import build_static_gap_queue


def gap(**overrides):
    return dict({'gap_id': 'g', 'entity_id': 'e', 'field': 'price',
                 'context': {'ticket': 'adult', 'currency': 'CNY'},
                 'evidence_policy': 'p1', 'blocker_class': 'data',
                 'reason': 'missing_value', 'blocking': True, 'required': True,
                 'entity_identity_verified': True,
                 'repairable': True}, **overrides)


def report(uid, data):
    return {'uid': uid, 'axes': {'data': data, 'adapter': [{'reason': 'parser'}]},
            'hard_failures': [{'field': 'budget', 'state': 'fail'}]}


class GapQueueTests(unittest.TestCase):
    def test_unresolved_identity_placeholders_and_nonhashable_ids_do_not_dispatch(self):
        entries = [gap(entity_id=[]), gap(entity_id='unresolved_id'),
                   gap(field='missing_id'), gap(evidence_policy='placeholder'),
                   gap(context={'route': {'origin_id': 'unknown_entity'}}),
                   gap(entity_id='unknown_entity', reason='identity_unresolved')]
        result = build_static_gap_queue([report('x', entries)], identity_verifier=lambda _: True)
        self.assertEqual(result['static_jobs'], [])
        self.assertEqual(result['identity_resolution_workflow'], [])
        self.assertEqual(len(result['unresolved']), len(entries))

    def test_identity_verifier_cannot_modify_gap_to_create_source_job(self):
        entry = gap(repairable=False)
        def mutate(value):
            value['repairable'] = True
            value['entity_id'] = 'different-entity'
            return True
        out = build_static_gap_queue([report('x', [entry])], identity_verifier=mutate)
        self.assertEqual(out['static_jobs'], [])
        self.assertEqual(entry['entity_id'], 'e')
        self.assertFalse(entry['repairable'])
        self.assertEqual(out['unresolved'][0]['reason'], 'independent_identity_verification_failed')

    def test_group_same_scope_across_tasks_but_not_policy_or_scope(self):
        out = build_static_gap_queue([report('a', [gap()]), report('b', [gap(gap_id='b')]),
            report('c', [gap(context={'ticket': 'child', 'currency': 'CNY'})]),
            report('d', [gap(evidence_policy='p2')])], identity_verifier=lambda g:g.get('entity_id')=='e')
        self.assertEqual(len(out['static_jobs']), 3)
        self.assertTrue(any(x['affected_tasks'] == ['a', 'b'] for x in out['static_jobs']))
        self.assertFalse(out['source_selection_performed'])

    def test_runtime_and_incomplete_context_are_never_dispatched(self):
        out = build_static_gap_queue([report('a', [gap(lifecycle='runtime'), gap(context={}),
                                                    gap(repairable=False), gap(field=''),
                                                    gap(context={'room': {'type': None}})])],
                                     identity_verifier=lambda g:g.get('entity_id')=='e')
        self.assertEqual(out['static_jobs'], [])
        self.assertEqual(len(out['unresolved']), 5)

    def test_unknown_blank_and_nonfinite_scope_cannot_be_dispatched(self):
        scopes = [{'room': '未知'}, {'room': ' UNKNOWN '}, {'room': '   '},
                  {'price': float('nan')}, {'nested': {'bed': None}}]
        out = build_static_gap_queue([report('x', [gap(context=s) for s in scopes])],
                                     identity_verifier=lambda _: True)
        self.assertEqual(out['static_jobs'], [])
        self.assertEqual(len(out['unresolved']), len(scopes))

    def test_unknown_entity_or_policy_cannot_become_dispatchable(self):
        entries = [gap(entity_id='unknown'), gap(evidence_policy='未提供')]
        result = build_static_gap_queue([report('x', entries)], identity_verifier=lambda _: True)
        self.assertEqual(result['static_jobs'], [])
        self.assertEqual(len(result['unresolved']), 2)

    def test_malformed_diagnostic_cannot_look_empty(self):
        with self.assertRaises(ValueError):
            build_static_gap_queue([{'uid': 'x', 'axes': {}}])

    def test_missing_gap_identity_is_not_a_dispatchable_job(self):
        out = build_static_gap_queue([report('x', [gap(gap_id=None)])])
        self.assertEqual(out['static_jobs'], [])
        self.assertEqual(out['unresolved'][0]['reason'], 'gap_provenance_incomplete')

    def test_identity_self_assertion_or_missing_verifier_never_dispatches(self):
        out = build_static_gap_queue([report('x', [gap()])])
        self.assertEqual(out['static_jobs'], [])
        self.assertEqual(out['unresolved'][0]['reason'], 'independent_identity_verifier_required')
        out = build_static_gap_queue([report('x', [gap(entity_identity_verified=False)])],
                                     identity_verifier=lambda _:True)
        self.assertEqual(out['static_jobs'], [])
        self.assertEqual(out['unresolved'][0]['reason'], 'entity_identity_unverified')
        out = build_static_gap_queue([report('x', [gap()])], identity_verifier=lambda _:False)
        self.assertEqual(out['static_jobs'], [])
        self.assertEqual(out['unresolved'][0]['reason'], 'independent_identity_verification_failed')

    def test_identity_resolution_is_preserved_in_separate_non_source_workflow(self):
        unresolved_identity = gap(field='entity', reason='identity_unresolved',
                                  entity_identity_verified=False, repairable=False)
        out = build_static_gap_queue([report('x', [unresolved_identity, gap(entity_identity_verified=True)])],
                                     identity_verifier=lambda _:True)
        self.assertEqual(out['static_jobs'], [])
        self.assertEqual(out['identity_resolution_workflow'][0]['entity_id'], 'e')
        self.assertFalse(out['identity_resolution_workflow'][0]['dispatch_to_static_sources'])
        self.assertEqual(len(out['unresolved']), 2)

    def test_identity_unresolved_suppresses_same_entity_across_reports_in_any_order(self):
        unresolved_identity = gap(field='entity', reason='identity_unresolved',
                                  entity_identity_verified=False, repairable=False)
        identity_report = report('identity', [unresolved_identity])
        static_report = report('static', [gap(gap_id='static-gap')])
        for diagnostics in ([identity_report, static_report], [static_report, identity_report]):
            out = build_static_gap_queue(diagnostics, identity_verifier=lambda _: True)
            self.assertEqual(out['static_jobs'], [])
            self.assertEqual(len(out['identity_resolution_workflow']), 1)
            self.assertEqual(out['identity_resolution_workflow'][0]['entity_id'], 'e')
            self.assertFalse(out['identity_resolution_workflow'][0]['dispatch_to_static_sources'])
            self.assertTrue(any(item.get('reason') == 'entity_identity_unresolved_in_report'
                                for item in out['unresolved']))

    def test_only_independently_verified_entity_gap_can_be_grouped(self):
        out = build_static_gap_queue([report('x', [gap()])],
                                     identity_verifier=lambda g:g.get('entity_id')=='e')
        self.assertEqual(len(out['static_jobs']), 1)
        self.assertTrue(out['static_jobs'][0]['identity_verified_by_queue'])


if __name__ == '__main__':
    unittest.main()
