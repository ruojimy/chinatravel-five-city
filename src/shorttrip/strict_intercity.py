"""Scoped intercity timetable checking without making a booking."""
from datetime import date, datetime, timedelta, timezone
import re
import copy
from .strict_fields import intercity_duration_minutes
from .strict_snapshot import strict_snapshot_equal
from .strict_scope import identifier_is_known


_REQUIREMENT_KEYS = frozenset({
    'origin_city', 'destination_city', 'origin_station', 'destination_station',
    'travel_date', 'departure_time', 'clock_zone',
})
_CLAIM_KEYS = _REQUIREMENT_KEYS | frozenset({
    'arrival_time', 'arrival_day_offset', 'Duration', 'Duration_unit',
})
_OFFSET_PATTERN = re.compile(r'^([+-])([0-9]{2}):([0-9]{2})$')
_CLOCK_PATTERN = re.compile(r'^[0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?$')


def _explicit_offset(value):
    if not isinstance(value, str):
        return None
    match = _OFFSET_PATTERN.fullmatch(value)
    if not match:
        return None
    if value == '-00:00':
        return None
    sign = 1 if match.group(1) == '+' else -1
    hours, minutes = int(match.group(2)), int(match.group(3))
    if hours > 14 or minutes > 59 or (hours == 14 and minutes != 0):
        return None
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def check_intercity(requirement, claim, *, claim_verifier=None):
    """Check explicit departure context, native-hour duration, and end time.

    The departure/arrival timezone is deliberately not inferred. This check
    requires a reviewed same-zone context and explicit arrival day offset;
    the callback must independently verify schedule/source/identity/scope.
    """
    def unknown(reason):
        return {'state':'unknown','reason':reason,'duration_minutes':None,
                'execution_confirmed':False}
    if not isinstance(requirement, dict) or not isinstance(claim, dict):
        return unknown('intercity_input_missing')
    if (set(requirement) - _REQUIREMENT_KEYS or set(claim) - _CLAIM_KEYS):
        return unknown('intercity_scope_has_unsupported_fields')
    keys=('origin_city','destination_city','origin_station','destination_station',
          'travel_date','departure_time','clock_zone')
    if any(not isinstance(requirement.get(k),str) or not requirement[k].strip() for k in keys):
        return unknown('intercity_context_missing')
    if any(not identifier_is_known(requirement[k]) for k in keys[:4]):
        return unknown('intercity_context_missing')
    if any(not strict_snapshot_equal(claim.get(k), requirement[k]) for k in keys):
        return unknown('intercity_context_mismatch')
    zone = _explicit_offset(requirement['clock_zone'])
    if zone is None:
        return unknown('intercity_timezone_invalid_or_unverifiable')
    if requirement['origin_city'] == requirement['destination_city']:
        return unknown('intercity_direction_invalid')
    try:
        trip_date=date.fromisoformat(requirement['travel_date'])
        if trip_date.isoformat() != requirement['travel_date']:
            return unknown('intercity_time_invalid')
        if (not _CLOCK_PATTERN.fullmatch(requirement['departure_time']) or
                not isinstance(claim.get('arrival_time'), str) or
                not _CLOCK_PATTERN.fullmatch(claim['arrival_time'])):
            return unknown('intercity_time_invalid')
        start_local=datetime.fromisoformat(trip_date.isoformat()+'T'+requirement['departure_time'])
        end_local=datetime.fromisoformat(trip_date.isoformat()+'T'+claim['arrival_time'])
        if start_local.tzinfo is not None or end_local.tzinfo is not None:
            return unknown('intercity_time_precision_or_zone_invalid')
        start = start_local.replace(tzinfo=zone)
        end = end_local.replace(tzinfo=zone)
    except (ValueError, TypeError, KeyError):
        return unknown('intercity_time_invalid')
    offset=claim.get('arrival_day_offset')
    if type(offset) is not int or offset not in (0,1,2):
        return unknown('intercity_arrival_day_offset_missing')
    try:
        end += timedelta(days=offset)
    except OverflowError:
        return unknown('intercity_time_invalid')
    if claim.get('Duration') is None:
        return unknown('intercity_duration_missing')
    if claim.get('Duration_unit') in (None, ''):
        return unknown('intercity_duration_unit_unknown')
    if claim.get('Duration_unit') != 'hours':
        return unknown('native_duration_unit_conflict')
    minutes=intercity_duration_minutes(claim.get('Duration'),claim.get('Duration_unit'))
    if minutes is None:
        return unknown('intercity_duration_invalid')
    from decimal import Decimal, localcontext
    elapsed = end - start
    with localcontext() as context:
        context.prec = max(1000, len(str(minutes)) + 20)
        actual_seconds = (Decimal(elapsed.days * 86400 + elapsed.seconds) +
                          Decimal(elapsed.microseconds) / Decimal(1000000))
        declared_seconds = Decimal(minutes) * 60
    if actual_seconds != declared_seconds:
        return unknown('duration_timetable_conflict')
    try:
        req_before,claim_before=copy.deepcopy(requirement),copy.deepcopy(claim)
        req_copy,claim_copy=copy.deepcopy(req_before),copy.deepcopy(claim_before)
        verified=(callable(claim_verifier) and claim_verifier(req_copy,claim_copy) is True
                  and strict_snapshot_equal(req_copy, req_before)
                  and strict_snapshot_equal(claim_copy, claim_before)
                  and strict_snapshot_equal(requirement, req_before)
                  and strict_snapshot_equal(claim, claim_before))
    except Exception:
        verified=False
    if not verified:
        return unknown('independent_intercity_verifier_required')
    return {'state':'pass','reason':'scoped_intercity_timetable_verified',
            'duration_minutes':minutes,'execution_confirmed':False}
