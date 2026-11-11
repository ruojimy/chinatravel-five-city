"""Scoped room/beds and room-night price check; no booking is performed."""
import copy
import re
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from .strict_snapshot import strict_snapshot_equal
from .strict_scope import identifier_is_known, scope_is_complete


_REQUIREMENT_KEYS = frozenset({
    'entity_id', 'room_type', 'check_in', 'check_out', 'rooms',
    'guests_per_room', 'minimum_beds', 'eligibility', 'meal_plan',
    'taxes_included', 'mandatory_fees_included',
})
_CLAIM_KEYS = frozenset({
    'entity_id', 'room_type', 'check_in', 'check_out', 'guests_per_room',
    'currency', 'unit', 'rate', 'beds', 'max_guests_per_room',
    'eligibility', 'meal_plan', 'taxes_included', 'mandatory_fees_included',
})


def check_lodging(requirement, claim, *, claim_verifier=None):
    """Check exact entity, room, stay dates, occupancy and quoted price scope.

    The independently verified quote must cover the whole stay and declare a
    constant CNY/room/night rate. Date-only values retain date precision.
    The rate must be a nonnegative integer or an unrounded decimal string;
    floating point inputs cannot preserve the source's exact lexical value.
    Capacity/bed count refer to that room type. Unknown or differing scopes do
    not become free lodging or constraint failure.
    """
    def unknown(reason):
        return {'state':'unknown','reason':reason,'total_cny':None,
                'execution_confirmed':False}
    if not isinstance(requirement, dict) or not isinstance(claim, dict):
        return unknown('lodging_input_missing')
    if (set(requirement) - _REQUIREMENT_KEYS or set(claim) - _CLAIM_KEYS):
        return unknown('lodging_scope_has_unsupported_fields')
    for key in ('entity_id','room_type','check_in','check_out','eligibility','meal_plan'):
        if not isinstance(requirement.get(key),str) or not requirement[key].strip():
            return unknown('lodging_scope_incomplete')
    if (not identifier_is_known(requirement['entity_id']) or
            not identifier_is_known(requirement['room_type']) or
            not scope_is_complete({'eligibility': requirement['eligibility'],
                                   'meal_plan': requirement['meal_plan']})):
        return unknown('lodging_scope_incomplete')
    try:
        start, end = date.fromisoformat(requirement['check_in']), date.fromisoformat(requirement['check_out'])
    except ValueError:
        return unknown('stay_date_invalid')
    if start.isoformat() != requirement['check_in'] or end.isoformat() != requirement['check_out']:
        return unknown('stay_date_invalid')
    nights = (end-start).days
    if nights <= 0:
        return unknown('stay_date_invalid')
    for key in ('rooms','guests_per_room','minimum_beds'):
        if type(requirement.get(key)) is not int or requirement[key] <= 0:
            return unknown('lodging_scope_incomplete')
    if (type(requirement.get('taxes_included')) is not bool or
        type(requirement.get('mandatory_fees_included')) is not bool):
        return unknown('lodging_scope_incomplete')
    if any(not strict_snapshot_equal(claim.get(k), requirement[k]) for k in
           ('entity_id','room_type','check_in','check_out','guests_per_room',
            'eligibility','meal_plan','taxes_included','mandatory_fees_included')):
        return unknown('quote_scope_mismatch')
    if not requirement['taxes_included'] or not requirement['mandatory_fees_included']:
        return unknown('mandatory_charges_not_included')
    if claim.get('currency') != 'CNY' or claim.get('unit') != 'CNY/room/night':
        return unknown('price_unit_or_currency_unqualified')
    price, beds, capacity = claim.get('rate'), claim.get('beds'), claim.get('max_guests_per_room')
    try:
        if type(price) is int and price >= 0:
            decimal_rate = Decimal(price)
        elif (isinstance(price, str) and len(price) <= 256 and
              re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', price)):
            decimal_rate = Decimal(price)
        else:
            return unknown('room_quote_value_invalid')
    except (InvalidOperation, ValueError, OverflowError):
        return unknown('room_quote_value_invalid')
    if (type(beds) is not int or beds < 1 or type(capacity) is not int or capacity < 1):
        return unknown('room_quote_value_invalid')
    try:
        req_before, claim_before = copy.deepcopy(requirement), copy.deepcopy(claim)
        req_copy, claim_copy = copy.deepcopy(req_before), copy.deepcopy(claim_before)
        verified = (callable(claim_verifier) and claim_verifier(req_copy, claim_copy) is True
                    and strict_snapshot_equal(req_copy, req_before)
                    and strict_snapshot_equal(claim_copy, claim_before)
                    and strict_snapshot_equal(requirement, req_before)
                    and strict_snapshot_equal(claim, claim_before))
    except Exception:
        verified = False
    if not verified:
        return unknown('independent_room_quote_verifier_required')
    try:
        with localcontext() as context:
            context.prec = max(100, len(decimal_rate.as_tuple().digits) +
                               len(str(nights)) + len(str(requirement['rooms'])) + 10)
            total = decimal_rate * nights * requirement['rooms']
        total_cny = int(total) if total == total.to_integral_value() else None
    except (OverflowError, InvalidOperation, ValueError):
        return unknown('room_total_invalid')
    state = 'pass' if beds >= requirement['minimum_beds'] and capacity >= requirement['guests_per_room'] else 'fail'
    return {'state':state,'reason':'verified_room_requirements', 'total_cny':total_cny,
            'total_decimal':str(total),
            'nights':nights,'execution_confirmed':False}
