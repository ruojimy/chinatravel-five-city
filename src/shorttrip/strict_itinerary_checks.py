"""Conservative chronology and location continuity checks for itineraries.

P31 times, labels, identities and entrances are proposal facts. They are only
compared after the caller independently verifies the corresponding facts.
This module does not prove route feasibility, meal completeness or budget.
"""
from datetime import date, datetime
from copy import deepcopy
from .strict_snapshot import strict_snapshot_equal
from .strict_scope import identifier_is_known


_ACTIVITIES = {'visit', 'attraction', 'breakfast', 'lunch', 'dinner', 'meal'}
_TIMELINE_TYPES = _ACTIVITIES | {'travel', 'wait'}


def check_itinerary_chronology_and_continuity(days, *, fact_verifier=None):
    """Check ordered intervals and explicitly declared segment endpoints.

    ``fact_verifier(kind, fact)`` must return exactly True independently for
    an interval or endpoint fact. Missing contexts or unverifiable proposals
    yield ``unknown``; no self-asserted status field is consumed.
    """
    if not isinstance(days, list) or not days:
        return _result('unknown', 'unknown', [], ['days_missing'])
    try:
        original_snapshot = deepcopy(days)
        isolated_days = deepcopy(original_snapshot)
    except Exception:
        return _result('unknown', 'unknown', [], ['days_snapshot_unavailable'])
    interval_facts, endpoint_facts = [], []
    structural_errors, unresolved = [], []
    chronology_unresolved, continuity_unresolved = [], []

    for day_index, day in enumerate(isolated_days):
        if not isinstance(day, dict):
            structural_errors.append(f'day_{day_index + 1}_malformed')
            continue
        day_value = day.get('date')
        try:
            day_date = date.fromisoformat(day_value) if isinstance(day_value, str) else None
        except ValueError:
            day_date = None
        if day_date is None or day_date.isoformat() != day_value:
            structural_errors.append(f'day_{day_index + 1}_date_invalid')
            continue
        timeline = day.get('timeline')
        if not isinstance(timeline, list) or not timeline:
            marker = f'day_{day_index + 1}_timeline_missing'
            unresolved.append(marker)
            chronology_unresolved.append(marker)
            continuity_unresolved.append(marker)
            continue
        for item_index, item in enumerate(timeline):
            if not isinstance(item, dict):
                structural_errors.append(f'day_{day_index + 1}_item_{item_index + 1}_malformed')
                continue
            kind = item.get('type')
            if not isinstance(kind, str) or kind not in _TIMELINE_TYPES:
                marker = f'day_{day_index + 1}_item_{item_index + 1}_type_unsupported'
                unresolved.append(marker)
                chronology_unresolved.append(marker)
                continuity_unresolved.append(marker)
                continue
            start, end = _parse_interval(day_date, item.get('start'), item.get('end'))
            if start is None or end is None:
                structural_errors.append(f'day_{day_index + 1}_item_{item_index + 1}_interval_invalid')
                continue
            try:
                nonpositive = end <= start
            except TypeError:
                structural_errors.append(f'day_{day_index + 1}_item_{item_index + 1}_interval_timezone_mismatch')
                continue
            if nonpositive:
                structural_errors.append(f'day_{day_index + 1}_item_{item_index + 1}_interval_nonpositive')
                continue
            fact = {'day_index': day_index, 'item_index': item_index, 'type': kind,
                    'start': start.isoformat(), 'end': end.isoformat()}
            verified = _verified(fact_verifier, 'interval', fact)
            interval_facts.append({'start': start, 'end': end, 'verified': verified,
                                   'fact': fact})
            if not verified:
                marker = f'day_{day_index + 1}_item_{item_index + 1}_interval_unverified'
                unresolved.append(marker)
                chronology_unresolved.append(marker)

            origin, destination = _locations(kind, item)
            endpoints = []
            for side, location in (('origin', origin), ('destination', destination)):
                if location is None:
                    endpoints.append({'side': side, 'location': None, 'verified': False})
                    marker = f'day_{day_index + 1}_item_{item_index + 1}_{side}_context_missing'
                    unresolved.append(marker)
                    continuity_unresolved.append(marker)
                    continue
                endpoint_fact = {'day_index': day_index, 'item_index': item_index,
                                 'side': side, 'type': kind, **location}
                ok = _verified(fact_verifier, 'endpoint', endpoint_fact)
                endpoints.append({'side': side, 'location': location, 'verified': ok})
                if not ok:
                    marker = f'day_{day_index + 1}_item_{item_index + 1}_{side}_unverified'
                    unresolved.append(marker)
                    continuity_unresolved.append(marker)
            endpoint_facts.append({'day_index': day_index, 'kind': kind, 'origin': endpoints[0],
                                   'destination': endpoints[1], 'fact': fact})

    if not strict_snapshot_equal(days, original_snapshot):
        return _result('unknown', 'unknown', [], ['verifier_mutated_original_itinerary'])
    chronology_state, chronology_reason = _check_chronology(interval_facts, structural_errors,
                                                            chronology_unresolved)
    continuity_state, continuity_reason = _check_continuity(endpoint_facts,
                                                            continuity_unresolved,
                                                            structural_errors)
    return _result(chronology_state, continuity_state, structural_errors,
                   sorted(set(unresolved)), chronology_reason, continuity_reason)


def _parse_interval(day_date, start, end):
    if not isinstance(start, str) or not isinstance(end, str):
        return None, None
    try:
        return (datetime.fromisoformat(day_date.isoformat() + 'T' + start),
                datetime.fromisoformat(day_date.isoformat() + 'T' + end))
    except ValueError:
        return None, None


def _locations(kind, item):
    if kind == 'travel':
        origin = _location(item, 'origin_id', 'origin_entrance_id')
        destination = _location(item, 'destination_id', 'destination_entrance_id')
        return origin, destination
    if kind in _ACTIVITIES:
        location = _location(item, 'entity_id', 'entrance_id')
        return location, location
    # Waiting does not establish a route endpoint; labels are not identities.
    return None, None


def _location(item, identity_field, entrance_field):
    identity, entrance = item.get(identity_field), item.get(entrance_field)
    if not identifier_is_known(identity) or not identifier_is_known(entrance):
        return None
    return {'identity': identity, 'entrance': entrance}


def _verified(verifier, kind, fact):
    if not callable(verifier):
        return False
    try:
        supplied = deepcopy(fact)
        before = deepcopy(supplied)
        accepted = verifier(kind, supplied)
        return accepted is True and strict_snapshot_equal(supplied, before)
    except Exception:
        return False


def _check_chronology(intervals, structural_errors, unresolved):
    if structural_errors:
        return 'fail', 'malformed_or_nonpositive_interval'
    if not intervals:
        return 'unknown', 'intervals_unavailable'
    conflict = False
    unknown = bool(unresolved)
    for previous, current in zip(intervals, intervals[1:]):
        if not previous['verified'] or not current['verified']:
            unknown = True
            continue
        try:
            if current['start'] < previous['start'] or current['start'] < previous['end']:
                conflict = True
        except TypeError:
            unknown = True
    if conflict:
        return 'fail', 'verified_order_or_overlap_conflict'
    if unknown or any(not x['verified'] for x in intervals):
        return 'unknown', 'chronology_evidence_incomplete'
    return 'pass', 'verified_ordered_nonoverlapping_intervals'


def _check_continuity(segments, unresolved, structural_errors):
    if len(segments) < 2:
        return 'unknown', 'continuity_requires_adjacent_segments'
    conflict = False
    unknown = bool(unresolved) or bool(structural_errors)
    for previous, current in zip(segments, segments[1:]):
        if previous['day_index'] != current['day_index']:
            # The intervening overnight stay and transfers are not represented
            # by either day's adjacent timeline entries.
            unknown = True
            continue
        if previous['kind'] != 'travel' and current['kind'] != 'travel':
            # Without an explicit movement segment the bridge has no basis to
            # assert that consecutive activity records imply direct movement.
            unknown = True
            continue
        arrival = previous['destination']
        departure = current['origin']
        if (arrival['location'] is None or departure['location'] is None or
                not arrival['verified'] or not departure['verified']):
            unknown = True
            continue
        if arrival['location'] != departure['location']:
            conflict = True
    if conflict:
        return 'fail', 'verified_endpoint_identity_or_entrance_mismatch'
    if unknown:
        return 'unknown', 'endpoint_evidence_incomplete'
    return 'pass', 'verified_adjacent_endpoint_continuity'


def _result(chronology, continuity, errors, unresolved,
            chronology_reason=None, continuity_reason=None):
    return {'chronology': {'state': chronology, 'reason': chronology_reason,
                           'structural_errors': list(errors)},
            'continuity': {'state': continuity, 'reason': continuity_reason,
                           'unresolved': list(unresolved)},
            'unresolved': list(unresolved), 'truth_certified': False,
            'execution_confirmed': False}
