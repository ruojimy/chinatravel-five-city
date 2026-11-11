"""Focused negative tests for the standalone cross-date event contract."""
import unittest

from shorttrip.strict_cross_date_event import (
    CONTRACT_VERSION,
    validate_cross_date_event,
)


def valid_event():
    return {
        "contract_version": CONTRACT_VERSION,
        "segment_id": "segment-1",
        "origin_city": "city-a",
        "destination_city": "city-b",
        "origin_station": "station-a",
        "destination_station": "station-b",
        "travel_date": "2026-10-31",
        "departure_time": "23:30",
        "arrival_time": "01:30",
        "clock_zone": "+08:00",
        "arrival_day_offset": 1,
        "departure_at": "2026-10-31T23:30:00+08:00",
        "arrival_at": "2026-11-01T01:30:00+08:00",
        "duration_minutes": 120,
        "permission_status": "allowed",
        "permission_evidence": {"source": "synthetic", "scope": "segment-1"},
    }


def accept(_event):
    return True


class StrictCrossDateEventTests(unittest.TestCase):
    def assert_unknown(self, event, *, verifier=accept):
        result = validate_cross_date_event(event, permission_verifier=verifier)
        self.assertEqual(result["state"], "unknown", result)
        self.assertIsNone(result["real_trip_feasibility"])
        self.assertFalse(result["source_truth_certified"])
        self.assertFalse(result["permission_certified"])
        self.assertFalse(result["execution_confirmed"])

    def test_explicit_overnight_event_passes_without_claiming_real_world_truth(self):
        result = validate_cross_date_event(valid_event(), permission_verifier=accept)
        self.assertEqual(result["state"], "pass", result)
        self.assertEqual(result["duration_minutes"], 120)
        self.assertIsNone(result["real_trip_feasibility"])
        self.assertFalse(result["source_truth_certified"])
        self.assertFalse(result["permission_certified"])
        self.assertFalse(result["execution_confirmed"])

    def test_rejects_missing_extra_or_wrong_version_fields(self):
        for mutate in (
            lambda value: value.pop("arrival_at"),
            lambda value: value.update(unreviewed=True),
            lambda value: value.update(contract_version="cross_date_event_v2"),
        ):
            with self.subTest(mutate=mutate):
                event = valid_event()
                mutate(event)
                self.assert_unknown(event)

    def test_rejects_invalid_day_offset_and_duration_types(self):
        for key, value in (("arrival_day_offset", True), ("arrival_day_offset", 2),
                           ("duration_minutes", True), ("duration_minutes", 0),
                           ("duration_minutes", 120.0)):
            with self.subTest(key=key, value=value):
                event = valid_event()
                event[key] = value
                self.assert_unknown(event)

    def test_rejects_invalid_calendar_clock_and_utc_offset(self):
        for key, value in (("travel_date", "2026-02-30"),
                           ("departure_time", "24:00"),
                           ("arrival_time", "01:60"),
                           ("clock_zone", "+14:01"),
                           ("clock_zone", "-00:00"),
                           ("clock_zone", "Asia/Shanghai")):
            with self.subTest(key=key, value=value):
                event = valid_event()
                event[key] = value
                self.assert_unknown(event)

    def test_rejects_instant_date_clock_offset_and_duration_mismatches(self):
        for key, value in (("departure_at", "2026-11-01T23:30:00+08:00"),
                           ("arrival_at", "2026-11-02T01:30:00+08:00"),
                           ("departure_at", "2026-10-31T15:30:00Z"),
                           ("arrival_at", "2026-11-01T01:30:00+07:00"),
                           ("duration_minutes", 119)):
            with self.subTest(key=key, value=value):
                event = valid_event()
                event[key] = value
                self.assert_unknown(event)

    def test_rejects_noncanonical_iso_instant_separators_and_compact_forms(self):
        for value in (
            "2026-10-31X23:30:00+08:00",
            "2026-10-31 23:30:00+08:00",
            "20261031T233000+0800",
            "2026-10-31T233000+08:00",
            "2026-10-31t23:30:00+08:00",
            "2026-10-31T23:30:00Z",
            "２０２６-10-31T23:30:00+08:00",
        ):
            with self.subTest(value=value):
                event = valid_event()
                event["departure_at"] = value
                self.assert_unknown(event)

    def test_rejects_same_city_unknown_identity_and_permission_gaps(self):
        for key, value in (("destination_city", "city-a"),
                           ("origin_station", "unknown"),
                           ("permission_status", "pending"),
                           ("permission_evidence", {}),
                           ("permission_evidence", {"source": "unknown"})):
            with self.subTest(key=key, value=value):
                event = valid_event()
                event[key] = value
                self.assert_unknown(event)

    def test_requires_callable_literal_true_nonmutating_permission_verifier(self):
        event = valid_event()
        self.assert_unknown(event, verifier=None)
        self.assert_unknown(event, verifier=lambda _event: 1)
        self.assert_unknown(event, verifier=lambda _event: False)

        def mutates_copy(value):
            value["permission_status"] = "denied"
            return True

        self.assert_unknown(event, verifier=mutates_copy)
        self.assertEqual(event, valid_event())

    def test_rejects_non_mapping_and_unstable_recursive_input(self):
        self.assert_unknown(None)
        event = valid_event()
        cycle = {}
        cycle["self"] = cycle
        event["permission_evidence"] = {"source": "synthetic", "cycle": cycle}
        self.assert_unknown(event)


if __name__ == "__main__":
    unittest.main()
