import unittest
from datetime import datetime
from shorttrip.strict_hours import check_interval
from shorttrip.strict_hours_parser import parse_explicit_intervals


class StrictHoursTests(unittest.TestCase):
    def dt(self, day, hour, minute=0):
        return datetime(2026, 10, day, hour, minute)

    def test_lunch_break_and_full_meal(self):
        schedule = [dict(weekday=0, open='09:00', close='12:00', end_day_offset=0),
                    dict(weekday=0, open='13:00', close='20:00', end_day_offset=0)]
        self.assertEqual(check_interval(schedule, self.dt(26, 11, 30), self.dt(26, 12, 30), schedule_complete=True), 'closed')
        self.assertEqual(check_interval(schedule, self.dt(26, 13), self.dt(26, 14)), 'open')

    def test_overnight_and_weekday(self):
        schedule = [dict(weekday=0, open='22:00', close='02:00', end_day_offset=1)]
        self.assertEqual(check_interval(schedule, self.dt(27, 0), self.dt(27, 1)), 'open')
        self.assertEqual(check_interval(schedule, self.dt(27, 1), self.dt(27, 3), schedule_complete=True), 'closed')
        self.assertEqual(check_interval(schedule, self.dt(28, 0), self.dt(28, 1), schedule_complete=True), 'closed')
        self.assertEqual(check_interval(schedule, self.dt(28, 0), self.dt(28, 1)), 'unknown')

    def test_unknown_bad_input_and_admission(self):
        self.assertEqual(check_interval(None, self.dt(26, 10), self.dt(26, 11)), 'unknown')
        self.assertEqual(check_interval([dict(weekday=0, open='09:00', close='02:00', end_day_offset=0)], self.dt(26, 10), self.dt(26, 11)), 'unknown')
        schedule = [dict(weekday=0, open='09:00', close='18:00', end_day_offset=0, last_admission='17:00')]
        self.assertEqual(check_interval(schedule, self.dt(26, 17, 1), self.dt(26, 17, 30), schedule_complete=True), 'closed')
        self.assertEqual(check_interval([], self.dt(26, 10), self.dt(26, 11), schedule_complete=True), 'closed')
        self.assertEqual(check_interval([], self.dt(26, 10), self.dt(26, 11), schedule_complete='yes'), 'unknown')

    def test_adjacent_same_day_windows_join_only_without_a_gap(self):
        adjacent = parse_explicit_intervals('09:00-12:00;12:00-17:00', weekdays=[0])
        self.assertEqual(check_interval(adjacent['windows'], self.dt(26, 11, 30),
                                        self.dt(26, 12, 30), schedule_complete=True), 'open')
        gap = parse_explicit_intervals('09:00-12:00;12:01-17:00', weekdays=[0])
        self.assertEqual(check_interval(gap['windows'], self.dt(26, 11, 30),
                                        self.dt(26, 12, 30), schedule_complete=True), 'closed')

    def test_adjacent_midnight_windows_join_but_gap_stays_closed(self):
        adjacent = [dict(weekday=0, open='09:00', close='24:00', end_day_offset=0),
                    dict(weekday=1, open='00:00', close='02:00', end_day_offset=0)]
        self.assertEqual(check_interval(adjacent, self.dt(26, 23, 30),
                                        self.dt(27, 0, 30), schedule_complete=True), 'open')
        gap = [dict(weekday=0, open='09:00', close='23:30', end_day_offset=0),
               dict(weekday=1, open='00:00', close='02:00', end_day_offset=0)]
        self.assertEqual(check_interval(gap, self.dt(26, 23), self.dt(27, 0, 30),
                                        schedule_complete=True), 'closed')

    def test_last_admission_is_unknown_when_window_join_is_required(self):
        schedule = [dict(weekday=0, open='09:00', close='12:00', end_day_offset=0,
                         last_admission='11:45'),
                    dict(weekday=0, open='12:00', close='17:00', end_day_offset=0)]
        self.assertEqual(check_interval(schedule, self.dt(26, 11, 30), self.dt(26, 12, 30),
                                        schedule_complete=True), 'unknown')
        # Existing single-window semantics remain defined: the cutoff limits
        # entry, not the visit's end time.
        self.assertEqual(check_interval(schedule, self.dt(26, 11, 30), self.dt(26, 11, 50),
                                        schedule_complete=True), 'open')

    def test_omitted_cutoff_cannot_override_explicit_rejection(self):
        schedule = [dict(weekday=0, open='09:00', close='17:00', end_day_offset=0,
                         last_admission='10:30'),
                    dict(weekday=0, open='11:30', close='12:00', end_day_offset=0),
                    dict(weekday=0, open='12:00', close='12:30', end_day_offset=0)]
        self.assertEqual(check_interval(schedule, self.dt(26, 11, 30), self.dt(26, 12, 30),
                                        schedule_complete=True), 'unknown')

    def test_rejecting_entry_cutoff_conflicts_even_when_its_window_does_not_span_visit(self):
        schedule = [dict(weekday=0, open='09:00', close='12:00', end_day_offset=0,
                         last_admission='10:30'),
                    dict(weekday=0, open='09:00', close='17:00', end_day_offset=0)]
        self.assertEqual(check_interval(schedule, self.dt(26, 11), self.dt(26, 13),
                                        schedule_complete=True), 'unknown')

    def test_shorter_rejecting_cutoff_conflicts_with_full_span_admitting_cutoff(self):
        schedule = [dict(weekday=0, open='09:00', close='12:00', end_day_offset=0,
                         last_admission='10:30'),
                    dict(weekday=0, open='09:00', close='17:00', end_day_offset=0,
                         last_admission='11:30')]
        self.assertEqual(check_interval(schedule, self.dt(26, 11), self.dt(26, 13),
                                        schedule_complete=True), 'unknown')

    def test_single_window_last_admission_timeout_without_alternative_stays_closed(self):
        schedule = [dict(weekday=0, open='09:00', close='18:00', end_day_offset=0,
                         last_admission='17:00')]
        self.assertEqual(check_interval(schedule, self.dt(26, 17, 1), self.dt(26, 17, 30),
                                        schedule_complete=True), 'closed')

    def test_overlapping_cutoff_conflict_is_unknown_even_with_no_cutoff_chain(self):
        schedule = [dict(weekday=0, open='09:00', close='17:00', end_day_offset=0,
                         last_admission='10:00'),
                    dict(weekday=0, open='10:00', close='16:00', end_day_offset=0,
                         last_admission='11:00'),
                    dict(weekday=0, open='10:30', close='11:00', end_day_offset=0),
                    dict(weekday=0, open='11:00', close='11:30', end_day_offset=0)]
        self.assertEqual(check_interval(schedule, self.dt(26, 10, 30), self.dt(26, 11, 30),
                                        schedule_complete=True), 'unknown')

    def test_consistent_single_window_cutoff_accepts_before_cutoff(self):
        schedule = [dict(weekday=0, open='09:00', close='17:00', end_day_offset=0,
                         last_admission='11:00')]
        self.assertEqual(check_interval(schedule, self.dt(26, 10, 30), self.dt(26, 11, 30),
                                        schedule_complete=True), 'open')

    def test_rejected_full_span_cutoff_with_alternate_cutoff_chain_is_unknown(self):
        schedule = [dict(weekday=0, open='09:00', close='17:00', end_day_offset=0,
                         last_admission='10:00'),
                    dict(weekday=0, open='10:30', close='11:00', end_day_offset=0,
                         last_admission='10:45'),
                    dict(weekday=0, open='11:00', close='11:30', end_day_offset=0,
                         last_admission='11:15')]
        self.assertEqual(check_interval(schedule, self.dt(26, 10, 30), self.dt(26, 11, 30),
                                        schedule_complete=True), 'unknown')

    def test_extreme_calendar_underflow_and_long_activity_fail_closed(self):
        full_day = [dict(weekday=0, open='00:00', close='24:00', end_day_offset=0)]
        self.assertEqual(check_interval(full_day, datetime(1, 1, 1, 10),
                                        datetime(1, 1, 1, 11), schedule_complete=True), 'unknown')
        self.assertEqual(check_interval(full_day, datetime(2026, 1, 1, 10),
                                        datetime(2026, 1, 20, 11), schedule_complete=True), 'unknown')


if __name__ == '__main__':
    unittest.main()
