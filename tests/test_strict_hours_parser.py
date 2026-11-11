import unittest
from datetime import datetime
from shorttrip.strict_hours import check_interval
from shorttrip.strict_hours_parser import parse_explicit_intervals


class StrictHoursParserTests(unittest.TestCase):
    def test_lunch_gap_is_not_collapsed(self):
        parsed = parse_explicit_intervals('09:00-12:00;13:00-17:00', weekdays=[0])
        self.assertFalse(parsed['evidence_qualified'])
        self.assertEqual(check_interval(parsed['windows'], datetime(2026, 11, 2, 11, 30),
                                       datetime(2026, 11, 2, 12, 30), schedule_complete=True), 'closed')

    def test_overnight_is_anchored_to_opening_day(self):
        parsed = parse_explicit_intervals('22:00-02:00', weekdays=[0])
        self.assertEqual(check_interval(parsed['windows'], datetime(2026, 11, 3, 0, 0),
                                       datetime(2026, 11, 3, 1, 0), schedule_complete=True), 'open')
        self.assertFalse(parsed['schedule_complete'])

    def test_unrecognized_text_missing_scope_and_ambiguous_day_reject(self):
        for text, weekdays in [('周一 09:00-17:00', [0]), ('09:00-17:00 假日另计', [0]),
                               ('00:00-00:00', [0]), ('24:00-25:00', [0]), ('09:00-17:00', [])]:
            with self.subTest(text=text):
                self.assertEqual(parse_explicit_intervals(text, weekdays=weekdays)['parse_status'], 'unsupported')


if __name__ == '__main__':
    unittest.main()
