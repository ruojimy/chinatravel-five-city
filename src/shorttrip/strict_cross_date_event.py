"""Validate an explicit v1 cross-date event contract.

This standalone validator checks date/time and scope consistency for one
explicitly supplied overnight event. It does not resolve time zones, infer
the day offset, authorize network access, establish schedule truth, or prove
that a trip is feasible. It is intentionally not wired into any planner.
"""
from __future__ import annotations

import copy
import re
from datetime import date, datetime, timedelta, timezone
from collections.abc import Mapping

from .strict_scope import identifier_is_known, scope_is_complete
from .strict_snapshot import strict_snapshot_equal


CONTRACT_VERSION = "cross_date_event_v1"
_KEYS = frozenset({
    "contract_version", "segment_id", "origin_city", "destination_city",
    "origin_station", "destination_station", "travel_date",
    "departure_time", "arrival_time", "clock_zone", "arrival_day_offset",
    "departure_at", "arrival_at", "duration_minutes", "permission_status",
    "permission_evidence",
})
_ZONE = re.compile(r"^([+-])([0-9]{2}):([0-9]{2})$")
_CLOCK = re.compile(r"^([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:\.([0-9]{1,6}))?)?$")
_INSTANT = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?"
    r"[+-][0-9]{2}:[0-9]{2}$"
)


def _unknown(reason: str) -> dict:
    return {
        "state": "unknown",
        "reason": reason,
        "contract_version": CONTRACT_VERSION,
        "duration_minutes": None,
        "real_trip_feasibility": None,
        "source_truth_certified": False,
        "permission_certified": False,
        "execution_confirmed": False,
    }


def _offset(value):
    if not isinstance(value, str):
        return None
    if value == '-00:00':
        return None
    match = _ZONE.fullmatch(value)
    if not match:
        return None
    sign = 1 if match.group(1) == "+" else -1
    hours, minutes = int(match.group(2)), int(match.group(3))
    if hours > 14 or minutes > 59 or (hours == 14 and minutes != 0):
        return None
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def _local_datetime(day, clock, zone):
    if not isinstance(clock, str):
        return None
    match = _CLOCK.fullmatch(clock)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    second = int(match.group(3) or 0)
    fraction = (match.group(4) or "").ljust(6, "0")
    microsecond = int(fraction or 0)
    try:
        return datetime(day.year, day.month, day.day, hour, minute, second,
                        microsecond, tzinfo=zone)
    except (OverflowError, TypeError, ValueError):
        return None


def _explicit_instant(value, expected_zone):
    if not isinstance(value, str) or not _INSTANT.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        offset = parsed.utcoffset()
        if parsed.tzinfo is None or offset is None or offset != expected_zone.utcoffset(None):
            return None
        return parsed
    except (OverflowError, TypeError, ValueError):
        return None


def validate_cross_date_event(event, *, permission_verifier=None):
    """Check the exact v1 event shape and require an independent permission gate.

    `event` must explicitly provide service-day clocks, numeric clock offset,
    date-qualified offset-aware instants, `arrival_day_offset == 1`, city/station
    direction, a positive exact whole-minute duration, and permission evidence.
    The verifier must return the literal boolean `True` without mutating its
    isolated inputs. A pass means only that this contract was internally
    consistent and its supplied verifier accepted the permission evidence.
    """
    if not isinstance(event, Mapping):
        return _unknown("cross_date_event_missing_or_not_mapping")
    try:
        original = copy.deepcopy(event)
        before = copy.deepcopy(original)
    except Exception:
        return _unknown("cross_date_event_cannot_be_snapshotted")
    if not strict_snapshot_equal(event, before):
        return _unknown("cross_date_event_not_stable_json_shape")
    if set(event) != _KEYS:
        return _unknown("cross_date_event_shape_or_version_invalid")
    if event.get("contract_version") != CONTRACT_VERSION:
        return _unknown("cross_date_event_shape_or_version_invalid")

    for key in ("segment_id", "origin_city", "destination_city",
                "origin_station", "destination_station"):
        if not identifier_is_known(event.get(key)):
            return _unknown("cross_date_event_identity_missing_or_unknown")
    if event["origin_city"] == event["destination_city"]:
        return _unknown("cross_date_event_direction_invalid")
    if event["permission_status"] != "allowed":
        return _unknown("cross_date_event_permission_not_explicitly_allowed")
    permission_evidence = event["permission_evidence"]
    if not isinstance(permission_evidence, Mapping) or not scope_is_complete(permission_evidence):
        return _unknown("cross_date_event_permission_evidence_missing")

    if type(event["arrival_day_offset"]) is not int or event["arrival_day_offset"] != 1:
        return _unknown("cross_date_event_arrival_day_offset_invalid")
    if type(event["duration_minutes"]) is not int or event["duration_minutes"] <= 0:
        return _unknown("cross_date_event_duration_invalid")
    zone = _offset(event["clock_zone"])
    if zone is None:
        return _unknown("cross_date_event_timezone_missing_or_invalid")

    travel_date = event["travel_date"]
    if not isinstance(travel_date, str):
        return _unknown("cross_date_event_travel_date_invalid")
    try:
        service_day = date.fromisoformat(travel_date)
        if service_day.isoformat() != travel_date:
            return _unknown("cross_date_event_travel_date_invalid")
        arrival_day = service_day + timedelta(days=1)
    except (OverflowError, TypeError, ValueError):
        return _unknown("cross_date_event_travel_date_invalid")

    expected_departure = _local_datetime(service_day, event["departure_time"], zone)
    expected_arrival = _local_datetime(arrival_day, event["arrival_time"], zone)
    departure = _explicit_instant(event["departure_at"], zone)
    arrival = _explicit_instant(event["arrival_at"], zone)
    if any(value is None for value in
           (expected_departure, expected_arrival, departure, arrival)):
        return _unknown("cross_date_event_time_invalid_or_timezone_mismatched")
    try:
        if departure != expected_departure or arrival != expected_arrival:
            return _unknown("cross_date_event_instant_clock_or_date_mismatch")
        elapsed_seconds = (arrival - departure).total_seconds()
        if elapsed_seconds <= 0:
            return _unknown("cross_date_event_interval_nonpositive")
        if elapsed_seconds != event["duration_minutes"] * 60:
            return _unknown("cross_date_event_duration_time_mismatch")
    except (OverflowError, TypeError, ValueError):
        return _unknown("cross_date_event_time_comparison_invalid")

    if not callable(permission_verifier):
        return _unknown("cross_date_event_permission_verifier_required")
    try:
        verifier_event = copy.deepcopy(original)
        verifier_before = copy.deepcopy(verifier_event)
        accepted = permission_verifier(verifier_event)
        verified = (accepted is True and
                    strict_snapshot_equal(verifier_event, verifier_before) and
                    strict_snapshot_equal(event, before))
    except Exception:
        verified = False
    if not verified:
        return _unknown("cross_date_event_permission_verification_failed")

    return {
        "state": "pass",
        "reason": "cross_date_event_contract_consistent",
        "contract_version": CONTRACT_VERSION,
        "duration_minutes": event["duration_minutes"],
        "real_trip_feasibility": None,
        "source_truth_certified": False,
        "permission_certified": False,
        "execution_confirmed": False,
    }
