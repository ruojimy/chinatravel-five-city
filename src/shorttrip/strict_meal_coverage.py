"""Explicit meal-slot coverage, conditional on independently checked inventory.

This component never infers meal requirements or authenticates travel facts.
"""
from __future__ import annotations

import copy
from datetime import date

from .strict_scope import identifier_is_known
from .strict_snapshot import strict_snapshot_equal


def check_meal_coverage(required_slots, events, *, inventory_verifier=None, event_verifier=None):
    """Compare a declared meal policy to a complete, independently checked plan inventory.

    Both lists use explicit ISO dates and meal slot identifiers. The independent
    inventory callback receives both lists and must validate policy binding and
    complete event coverage. Each event is separately verified. The component
    doesn't determine whether a restaurant is open or establish route feasibility.
    """
    def result(state, reason, missing=()):
        return {'state': state, 'reason': reason, 'missing_slots': list(missing),
                'truth_certified': False, 'execution_confirmed': False,
                'complete_itinerary_certified': False}

    if not isinstance(required_slots, list) or not required_slots or not isinstance(events, list):
        return result('unknown', 'meal_policy_or_events_missing')
    required = []
    for item in required_slots:
        if not isinstance(item, dict) or set(item) != {'date', 'slot'} or not _valid_slot(item):
            return result('unknown', 'meal_policy_scope_invalid')
        required.append((item['date'], item['slot']))
    if len(set(required)) != len(required):
        return result('unknown', 'meal_policy_slot_duplicate')
    observed, ids = [], []
    for item in events:
        if (not isinstance(item, dict) or set(item) != {'date', 'slot', 'entity_id', 'event_id'}
                or not _valid_slot(item) or
                not identifier_is_known(item.get('entity_id')) or
                not identifier_is_known(item.get('event_id'))):
            return result('unknown', 'meal_event_scope_invalid')
        observed.append((item['date'], item['slot']))
        ids.append(item['event_id'])
    if len(set(ids)) != len(ids) or len(set(observed)) != len(observed):
        return result('unknown', 'meal_event_duplicate_or_ambiguous')
    if not callable(inventory_verifier) or not callable(event_verifier):
        return result('unknown', 'independent_meal_verifiers_required')
    try:
        policy_copy, events_copy = copy.deepcopy(required_slots), copy.deepcopy(events)
        policy_before, events_before = copy.deepcopy(policy_copy), copy.deepcopy(events_copy)
        accepted = inventory_verifier(policy_copy, events_copy)
        if (accepted is not True or not strict_snapshot_equal(policy_copy, policy_before)
                or not strict_snapshot_equal(events_copy, events_before)
                or not strict_snapshot_equal(required_slots, policy_before)
                or not strict_snapshot_equal(events, events_before)):
            return result('unknown', 'meal_inventory_unverified_or_mutated')
        for event in events:
            event_copy = copy.deepcopy(event)
            before = copy.deepcopy(event_copy)
            if (event_verifier(event_copy) is not True or not strict_snapshot_equal(event_copy, before)
                    or not strict_snapshot_equal(required_slots, policy_before)
                    or not strict_snapshot_equal(events, events_before)):
                return result('unknown', 'meal_event_unverified_or_mutated')
    except Exception:
        return result('unknown', 'meal_verifier_failed')
    missing = [{'date': day, 'slot': slot} for day, slot in required if (day, slot) not in observed]
    return result('fail' if missing else 'pass',
                  'verified_required_meal_slots_missing' if missing else 'verified_meal_slots_covered',
                  missing)


def _valid_slot(item):
    value, slot = item.get('date'), item.get('slot')
    if not isinstance(value, str) or not isinstance(slot, str) or not slot.strip():
        return False
    if not identifier_is_known(slot):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False
