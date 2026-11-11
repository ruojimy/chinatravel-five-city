import unittest

from shorttrip.strict_scope import identifier_is_known, scope_is_complete, scope_identifiers_are_known


class StrictScopeTests(unittest.TestCase):
    def test_unknown_markers_cannot_satisfy_required_scope(self):
        for value in ('unknown', ' UNKNOWN ', 'ｕｎｋｎｏｗｎ', 'unspecified', 'not_known', 'not known', 'n/a', '未知', '不明', '未提供'):
            with self.subTest(value=value):
                self.assertFalse(scope_is_complete({'room': {'type': value}}))

    def test_explicit_false_and_zero_are_valid(self):
        self.assertTrue(scope_is_complete({'breakfast': False, 'fee': 0}))
        self.assertTrue(scope_identifiers_are_known({'breakfast': False, 'fee': 0, 'meal_option': 'none'}))
        self.assertTrue(scope_identifiers_are_known({'entity': {'id': 'poi-1', 'city': '西安'}}))
        self.assertFalse(scope_identifiers_are_known({'trip': {'origin_id': 'unresolved_id'}}))

    def test_identity_sentinel_variants_are_not_known(self):
        for value in ('unknown_entity', 'unresolved_id', 'missing_id', 'unknown_id',
                      'unverified', 'not verified', 'pending', 'pending_verification',
                      '未核实', '未验证', '待核验', '待确认', 'tbd',
                      'to be determined', 'not available', 'placeholder'):
            with self.subTest(value=value):
                self.assertFalse(identifier_is_known(value))
        self.assertFalse(identifier_is_known('\ud800'))

    def test_cyclic_and_overdeep_scopes_fail_closed(self):
        cycle = []
        cycle.append(cycle)
        self.assertFalse(scope_is_complete({'value': cycle}))
        value = 'ok'
        for _ in range(140):
            value = {'nested': value}
        self.assertFalse(scope_is_complete({'value': value}))
