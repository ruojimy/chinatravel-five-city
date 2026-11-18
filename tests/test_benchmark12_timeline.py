"""Test the V17 evaluator on frozen intercity rows and lodging timelines."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from g3_sandbox12_repaired_v17 import configure


def train(ident, origin, destination, begin, end, arrival_day=None):
    row = {'type': 'train', 'TrainID': ident, 'start': origin, 'end': destination,
           'start_time': begin, 'end_time': end, 'transports': []}
    if arrival_day is not None:
        row['arrival_day'] = arrival_day
    return row


class TimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configure()
        from chinatravel.symbol_verification.commonsense_constraint import Is_time_correct
        cls.check = staticmethod(Is_time_correct)

    def evaluate(self, *buckets, origin='西安', destination='厦门'):
        plan = {'itinerary': [{'day': index, 'activities': rows} for index, rows in enumerate(buckets, 1)]}
        table, issues = self.check({'start_city': origin, 'target_city': destination, 'days': len(buckets)}, plan)
        return table.attrs['time_state'], {item['code'] for item in issues}

    def test_over_24h_later_end_clock_exceeds_last_day(self):
        state, issues = self.evaluate([], [train('K244', '厦门北站', '西安站', '19:36', '22:17')])
        self.assertEqual(state, 'fail')
        self.assertIn('activity_exceeds_trip_days', issues)

    def test_matching_overnight_duration_allows_next_day(self):
        self.assertEqual(self.evaluate([train('K244', '厦门北站', '西安站', '19:36', '22:17')], []),
                         ('pass', set()))

    def test_explicit_wrong_arrival_day_is_rejected(self):
        state, issues = self.evaluate([train('K244', '厦门北站', '西安站', '19:36', '22:17', 1)], [])
        self.assertEqual(state, 'fail')
        self.assertIn('arrival_day_conflicts_with_source_duration', issues)

    def test_hotel_before_night_train_arrival_is_rejected(self):
        after = {'type': 'accommodation', 'start_time': '22:07', 'end_time': '24:00', 'transports': []}
        state, issues = self.evaluate([train('Z128', '西安站', '厦门北站', '23:44', '21:23'), after], [])
        self.assertEqual(state, 'fail')
        self.assertIn('activity_overlaps_previous', issues)

    def test_untied_duration_is_unknown_even_with_declared_day(self):
        state, issues = self.evaluate([train('UNKNOWN', '厦门北站', '西安站', '19:36', '22:17', 1)], [])
        self.assertEqual(state, 'unknown')
        self.assertIn('intercity_duration_evidence_missing', issues)

    def test_valid_checkout_and_early_departure(self):
        hotel = {'type': 'accommodation', 'start_time': '20:00', 'end_time': '08:00', 'transports': []}
        spot = {'type': 'attraction', 'start_time': '08:20', 'end_time': '10:30',
                'transports': [{'start_time': '08:00', 'end_time': '08:19'}]}
        self.assertEqual(self.evaluate([hotel], [spot]), ('pass', set()))
        spot['transports'][0]['start_time'] = '07:59'
        self.assertIn('transport_overlaps_previous', self.evaluate([hotel], [spot])[1])

    def test_same_check_for_xian_as_destination(self):
        self.assertEqual(self.evaluate([train('Z179', '北京西', '西安', '18:20', '06:51')], [],
                                       origin='北京', destination='西安'), ('pass', set()))


if __name__ == '__main__':
    unittest.main()
