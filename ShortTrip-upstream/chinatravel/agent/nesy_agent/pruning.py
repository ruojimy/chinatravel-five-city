"""Necessary conditions only: unknown and unfinished requirements stay searchable.

This module deliberately does not execute arbitrary translated Python on prefixes.
Only supported standard templates whose failure cannot be repaired are used.
"""
import ast
import math
import operator
from functools import lru_cache

from .constraint_compiler import comparison, compile_constraint


OPS = {ast.Eq: operator.eq, ast.LtE: operator.le, ast.Lt: operator.lt,
       ast.GtE: operator.ge, ast.Gt: operator.gt}


def reason(rule, constraint, **details):
    return dict(rule=rule, constraint=constraint, details=details)


@lru_cache(maxsize=256)
def _facts(codes):
    result = []
    for code in codes:
        fact = comparison(code)
        if fact and compile_constraint(code) is not None:
            result.append((code, fact))
    return tuple(result)


def facts(query):
    return _facts(tuple(query.get('hard_logic', [])))


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (ValueError, TypeError):
        return None


def clock(value):
    try:
        hour, minute = map(int, str(value).split(':'))
        return hour * 60 + minute if hour >= 0 and 0 <= minute < 60 else None
    except (ValueError, TypeError):
        return None


def ticket_kind(row):
    for key, kind in (('TrainID', 'train'), ('FlightID', 'airplane')):
        value = row.get(key)
        if isinstance(value, str) and value and value.lower() != 'nan':
            return kind
    return None


def exceeded(query, lower_bound):
    if lower_bound is None:
        return None
    for code, (field, op, value, shape) in facts(query):
        if field == 'cost' and shape == 'scalar' and isinstance(op, (ast.LtE, ast.Lt, ast.Eq)):
            if not isinstance(value, (int, float)):
                continue
            if (lower_bound >= value if isinstance(op, ast.Lt) else lower_bound > value):
                return reason('budget_lower_bound', code, lower_bound=lower_bound)
    return None


def fixed_cost(query, poi_plan, rooms=None):
    total = 0
    for key in ('go_transport', 'back_transport'):
        if key in poi_plan:
            cost = number(poi_plan[key].get('Cost'))
            if cost is None:
                return None
            total += cost * query['people_number']
    if 'accommodation' in poi_plan and query['days'] > 1:
        hotel = poi_plan['accommodation']
        beds = number(hotel.get('numbed'))
        price = number(hotel.get('price'))
        if price is None or not beds or beds <= 0:
            return None
        rooms = rooms if rooms is not None else math.ceil(query['people_number'] / beds)
        # An overnight outbound ticket may replace hotel nights. Only reserve
        # nights after its known arrival day; unknown dates add no lower bound.
        go = poi_plan.get('go_transport')
        nights = 0
        if go is not None:
            start, end = clock(go.get('BeginTime')), clock(go.get('EndTime'))
            duration = number(go.get('Duration'))
            if start is not None and end is not None:
                offset = round((start + duration * 60 - end) / 1440) if duration else int(end < start)
                if (duration and abs(offset * 1440 + end - start - duration * 60) <= 60) or (duration is None and end != start):
                    nights = max(0, query['days'] - (offset + 1))
        total += int(price) * rooms * nights
    return total


def selection_reason(query, poi_plan, rooms=None):
    tickets = [poi_plan[k] for k in ('go_transport', 'back_transport') if k in poi_plan]
    known = all(ticket_kind(row) is not None for row in tickets)
    modes = {ticket_kind(row) for row in tickets}
    complete = 'go_transport' in poi_plan and 'back_transport' in poi_plan
    for code, (field, op, value, shape) in facts(query):
        if shape != 'scalar':
            continue
        if field == 'intercity_transport' and isinstance(op, ast.Eq) and known:
            if modes - value or (complete and modes != value):
                return reason('intercity_mode', code, selected=sorted(modes))
        if field == 'train_type' and isinstance(op, ast.Eq):
            trains = [row for row in tickets if ticket_kind(row) == 'train']
            if any(str(row['TrainID'])[0] not in value for row in trains) or (complete and known and not trains):
                return reason('train_prefix', code, selected=[str(row['TrainID']) for row in trains])
        if field == 'return_start_time' and 'back_transport' in poi_plan:
            actual, limit = clock(poi_plan['back_transport'].get('BeginTime')), clock(value)
            if actual is not None and limit is not None and not OPS[type(op)](actual, limit):
                return reason('return_deadline', code, departure=poi_plan['back_transport']['BeginTime'])
        if field in ('rooms', 'room_type', 'hotel_price') and 'accommodation' in poi_plan:
            hotel = poi_plan['accommodation']
            actual = {'rooms': rooms, 'room_type': hotel.get('numbed'), 'hotel_price': hotel.get('price')}[field]
            if field == 'hotel_price' and number(actual) is not None:
                actual = int(float(actual))
            if actual is not None and number(actual) is not None and not OPS[type(op)](float(actual), value):
                return reason('hotel_selection', code, actual=float(actual))
    return exceeded(query, fixed_cost(query, poi_plan, rooms))


def local_mode_allowed(query, mode):
    for _, (field, op, value, shape) in facts(query):
        if field == 'transport_type' and shape == 'scalar' and isinstance(op, (ast.Eq, ast.LtE)):
            if mode not in value:
                return False
    return True


def local_ranking(query, proposed):
    """Model suggestions rank allowed modes; omissions are not hard bans."""
    result = []
    for mode in list(proposed or []) + ['metro', 'taxi', 'walk']:
        if mode in ('metro', 'taxi', 'walk') and mode not in result and local_mode_allowed(query, mode):
            result.append(mode)
    return result


def prefix_reason(query, plan, poi_plan, rooms=None):
    rejected = selection_reason(query, poi_plan, rooms)
    if rejected:
        return rejected
    activities = [a for day in plan for a in day.get('activities', [])]
    local = other = actual_intercity = actual_hotel = 0
    for activity in activities:
        cost = number(activity.get('cost', 0))
        legs = activity.get('transports', [])
        costs = [number(leg.get('cost', 0)) for leg in legs]
        if cost is None or any(c is None for c in costs):
            # Do not infer a budget impossibility from unknown/negative costs.
            local = None
            break
        local += sum(costs)
        if activity.get('type') in ('train', 'airplane'):
            actual_intercity += cost
        elif activity.get('type') == 'accommodation':
            actual_hotel += cost
        else:
            other += cost
    reserved = fixed_cost(query, poi_plan, rooms)
    if local is not None and reserved is not None:
        # Selected tickets and all planned hotel nights are already reserved.
        reserved_intercity = fixed_cost(query, {k: poi_plan[k] for k in ('go_transport', 'back_transport') if k in poi_plan})
        lower = max(reserved_intercity, actual_intercity) + max(reserved - reserved_intercity, actual_hotel) + other + local
        rejected = exceeded(query, lower)
        if rejected:
            return rejected
    for activity in activities:
        kind = activity.get('type')
        legs = activity.get('transports', [])
        # Match the existing primary-mode helper, allowing metro access walks.
        mode = legs[1].get('mode') if len(legs) == 3 else legs[0].get('mode') if len(legs) == 1 else None
        if mode is not None and not local_mode_allowed(query, mode):
            return reason('local_mode', 'transport_type', mode=mode)
        for code, (field, op, value, shape) in facts(query):
            if shape != 'scalar':
                continue
            actual = None
            if field == 'tickets' and kind in ('attraction', 'train', 'airplane'):
                actual = activity.get('tickets')
            elif field in ('rooms', 'room_type', 'hotel_price') and kind == 'accommodation':
                actual = activity.get({'rooms': 'rooms', 'room_type': 'room_type', 'hotel_price': 'price'}[field])
            elif field == 'food_price' and kind in ('breakfast', 'lunch', 'dinner'):
                actual = activity.get('price')
            if actual is not None and number(actual) is not None and not OPS[type(op)](float(actual), value):
                return reason('executed_activity', code, kind=kind, actual=float(actual))
            for leg in legs:
                key = 'tickets' if field == 'tickets' and leg.get('mode') == 'metro' else 'cars' if field == 'taxi_cars' and leg.get('mode') == 'taxi' else None
                if key and leg.get(key) is not None and not OPS[type(op)](leg[key], value):
                    return reason('executed_transport', code, actual=leg[key])
    return None
