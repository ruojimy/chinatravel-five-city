"""Exercise the timing checker loaded by the Xiamen V16 scoring entry."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from g3_sandbox12_repaired_v16 import PROFILE, configure


def activity(kind, start, end, *, departure=None):
    route = [] if departure is None else [{'start_time': departure, 'end_time': start}]
    return {'type': kind, 'start_time': start, 'end_time': end, 'transports': route}


class XiamenOvernightCheckoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configure()
        from chinatravel.symbol_verification import commonsense_constraint
        if not Path(commonsense_constraint.__file__).resolve().is_relative_to(PROFILE / 'engine'):
            raise AssertionError('Timing evaluator escaped the V16 engine')
        cls.check = staticmethod(commonsense_constraint.Is_time_correct)

    def messages(self, *days):
        itinerary = [{'day': i, 'activities': day} for i, day in enumerate(days, 1)]
        table, messages = self.check({'target_city': '厦门'}, {'itinerary': itinerary})
        self.assertEqual(bool(table.iloc[0].any()), bool(messages))
        return messages

    def test_overnight_checkout_at_next_day_first_departure(self):
        self.assertEqual(self.messages(
            [activity('accommodation', '20:00', '08:00')],
            [activity('attraction', '08:10', '09:15', departure='08:00')],
        ), [])

    def test_next_day_transfer_before_checkout_still_fails(self):
        messages = self.messages(
            [activity('accommodation', '20:00', '08:00')],
            [activity('attraction', '08:10', '09:15', departure='07:59')],
        )
        self.assertIn('Transport must depart after the previous activity ends on day 2', messages[0])

    def test_next_day_activity_without_transfer_cannot_start_before_checkout(self):
        messages = self.messages(
            [activity('accommodation', '20:00', '08:00')],
            [activity('breakfast', '07:45', '08:30')],
        )
        self.assertIn('Activities must not overlap on day 2', messages[0])

    def test_same_day_activity_cannot_follow_overnight_check_in(self):
        messages = self.messages(
            [activity('accommodation', '20:00', '08:00'), activity('dinner', '20:30', '21:30')],
            [],
        )
        self.assertIn('Activities must not overlap on day 1', messages[0])

    def test_final_day_cannot_contain_unrepresented_checkout(self):
        messages = self.messages([activity('accommodation', '20:00', '08:00')])
        self.assertIn('Overnight accommodation needs the next itinerary day', messages[0])

    def test_legacy_same_day_hotel_slot_and_empty_checkout_day(self):
        self.assertEqual(self.messages([activity('accommodation', '20:00', '23:59')]), [])
        self.assertEqual(self.messages([activity('accommodation', '20:00', '08:00')], []), [])

    def test_equal_hotel_clocks_and_reverse_nonhotel_remain_invalid(self):
        for invalid in (activity('accommodation', '20:00', '20:00'),
                        activity('attraction', '20:00', '08:00')):
            with self.subTest(activity=invalid):
                self.assertIn('Activities must cost time', self.messages([invalid], [])[0])

    def test_overnight_train_uses_existing_rule(self):
        self.assertEqual(self.messages([activity('train', '23:00', '07:00')], []), [])


if __name__ == '__main__':
    unittest.main()
