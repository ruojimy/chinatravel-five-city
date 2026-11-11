import unittest
from shorttrip.strict_fields import total_required_cost, room_beds_for_scope, intercity_duration_minutes


class StrictFieldsTests(unittest.TestCase):
    def test_nonfinite_total_is_unknown_not_budget_failure(self):
        self.assertIsNone(total_required_cost([1e308,1e308]))
        self.assertIsNone(total_required_cost([10 ** 5000]))
    def test_unknown_fare_never_becomes_zero(self):
        self.assertIsNone(total_required_cost([100, None]))
        self.assertIsNone(total_required_cost([]))
        self.assertIsNone(total_required_cost([True, 5]))
        self.assertEqual(total_required_cost([100, 0]), 100)
        self.assertEqual(total_required_cost(['0.1', '0.2']), '0.3')

    def test_room_type_and_units_are_bound(self):
        self.assertIsNone(room_beds_for_scope({'room_type': 'unknown', 'beds': 2}, 'unknown'))
        self.assertIsNone(room_beds_for_scope({'room_type': 'unresolved_id', 'beds': 2}, 'unresolved_id'))
        self.assertIsNone(room_beds_for_scope({'room_type': 'twin', 'beds': 2}, 'king'))
        self.assertIsNone(room_beds_for_scope({'room_type': 'twin', 'beds': True}, 'twin'))
        self.assertEqual(room_beds_for_scope({'room_type': 'twin', 'beds': 2}, 'twin'), 2)
        self.assertEqual(intercity_duration_minutes('2.5', 'hours'), 150)
        self.assertIsNone(intercity_duration_minutes(2.5, 'hours'))
        self.assertIsNone(intercity_duration_minutes(150, 'minutes'))
        self.assertIsNone(intercity_duration_minutes(2.5, None))


if __name__ == '__main__':
    unittest.main()
