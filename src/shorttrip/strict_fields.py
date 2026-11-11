"""Small conservative primitives for the future strict planner adapter.

Inputs must already have passed identity and evidence qualification; these
functions alone do not make a catalogue value reliable.
"""
from decimal import Decimal, localcontext
from .strict_money import exact_money
from .strict_scope import identifier_is_known


def total_required_cost(costs):
    """None represents an unknown total, including for an empty leg list."""
    if not isinstance(costs, list) or not costs:
        return None
    values = [exact_money(value) for value in costs]
    if any(value is None for value in values):
        return None
    with localcontext() as context:
        context.prec = max(1000, sum(len(str(value)) for value in values) + 20)
        total = sum(values, Decimal(0))
    return int(total) if total == total.to_integral_value() else format(total, 'f')


def room_beds_for_scope(claim, room_type):
    """Do not borrow beds from another room type or an unbound claim."""
    if not isinstance(claim, dict) or not identifier_is_known(room_type) or claim.get('room_type') != room_type:
        return None
    beds = claim.get('beds')
    return beds if type(beds) is int and beds > 0 else None


def intercity_duration_minutes(value, unit):
    """Convert exact native hours without inferring unit or float precision."""
    hours = exact_money(value)
    if unit != 'hours' or hours is None or hours <= 0:
        return None
    with localcontext() as context:
        context.prec = max(1000, len(str(hours)) + 20)
        minutes = hours * 60
    return int(minutes) if minutes == minutes.to_integral_value() else format(minutes, 'f')
