"""Deterministic soft penalties over unchanged ChinaTravel itinerary records."""
from dataclasses import dataclass, field, asdict
import math

CATEGORIES = ('transport', 'rhythm', 'distribution', 'efficiency')
MEALS = {'breakfast', 'lunch', 'dinner'}
INTERCITY = {'train', 'airplane'}


@dataclass
class SoftConfig:
    weights: dict = field(default_factory=lambda: dict.fromkeys(CATEGORIES, 1.0))
    commute_minutes: float = 60
    commute_unit: float = 15
    walk_minutes: float = 20
    walk_unit: float = 10
    station_wait_minutes: float = 90
    airport_wait_minutes: float = 180
    wait_unit: float = 30
    day_start: int = 540
    day_end: int = 1200
    playable_minimum: float = 240
    crowded_minutes: float = 540
    span_minutes: float = 720
    idle_minutes: float = 120
    minimum_attraction_minutes: float = 120
    rhythm_unit: float = 60
    missing_meal_penalty: float = 4
    empty_day_penalty: float = 8
    daily_transit_minutes: float = 120
    transit_unit: float = 30
    daily_distance_km: float = 30
    distance_unit: float = 10
    meal_detour_minutes: float = 15
    meal_detour_time_unit: float = 15
    meal_detour_km: float = 3
    meal_detour_distance_unit: float = 3
    train_buffer: float = 60
    airplane_buffer: float = 120

    def __post_init__(self):
        self.weights = {k: float(self.weights.get(k, 1)) for k in CATEGORIES}
        for key, value in asdict(self).items():
            values = value.values() if isinstance(value, dict) else [value]
            if any(not math.isfinite(float(v)) or v < 0 for v in values):
                raise ValueError(f'Invalid nonnegative configuration: {key}')
            if key.endswith('_unit') and value == 0:
                raise ValueError(f'Unit must be positive: {key}')
        if self.day_end <= self.day_start:
            raise ValueError('day_end must exceed day_start')


def clock(value):
    if not isinstance(value, str):
        return None
    try:
        h, m = map(int, value.split(':'))
        if not (0 <= h <= 24 and 0 <= m < 60 and (h < 24 or m == 0)):
            return None
        return h * 60 + m
    except (ValueError, TypeError):
        return None


def interval(record, base=0):
    start, end = clock(record.get('start_time')), clock(record.get('end_time'))
    if start is None or end is None:
        return None
    if end < start:
        end += 1440
    return base + start, base + end


def duration(record):
    value = interval(record)
    return value[1] - value[0] if value else None


def incoming_intervals(activity, base):
    """Place access legs on absolute dates, working backwards from the activity."""
    start = clock(activity.get('start_time'))
    anchor = base + start if start is not None else None
    values = []
    for leg in reversed(activity.get('transports', [])):
        value = interval(leg, base)
        if value and anchor is not None:
            while value[1] > anchor:
                value = (value[0] - 1440, value[1] - 1440)
            anchor = value[0]
        values.append(value)
    return list(reversed(values))


def union(intervals):
    result = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result


def point(activity, arriving=False):
    if activity.get('type') in INTERCITY:
        return activity.get('end' if arriving else 'start')
    return activity.get('position')


def numeric_sum(values):
    values = list(values)
    if any(v is None or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        return None
    return sum(values)


def score_plan(plan, config=None, route_resolver=None):
    config = config or SoftConfig()
    details, unknown = [], []
    metrics = {'days': [], 'waits': [], 'meal_detours': []}

    def add(category, rule, penalty, day, actual=None, threshold=None, activity=None):
        if penalty > 0:
            details.append({'category': category, 'rule': rule, 'day': day,
                            'activity': activity, 'actual': actual, 'threshold': threshold,
                            'penalty': round(float(penalty), 6)})

    def excess(category, rule, actual, threshold, unit, day, index=None):
        if actual is not None:
            add(category, rule, max(0, actual - threshold) / unit, day, actual, threshold, index)

    entries = [(d['day'], a) for d in plan.get('itinerary', []) for a in d.get('activities', [])]
    previous = {id(a): entries[index - 1] if index else None for index, (_, a) in enumerate(entries)}
    intercity = [(n, a) for n, a in entries if a.get('type') in INTERCITY]
    arrival, departure = None, None
    if len(intercity) >= 2:
        n, a = intercity[0]
        iv = interval(a, (n - 1) * 1440)
        if iv:
            arrival = iv[1]
        n, a = intercity[-1]
        start = clock(a.get('start_time'))
        if start is not None:
            departure = (n - 1) * 1440 + start - (config.train_buffer if a['type'] == 'train' else config.airplane_buffer)
            legs = a.get('transports', [])
            access = incoming_intervals(a, (n - 1) * 1440)
            if access and access[0]:
                departure = min(departure, access[0][0])

    for day in plan.get('itinerary', []):
        n, acts = day['day'], day.get('activities', [])
        base = (n - 1) * 1440
        lo, hi = base + config.day_start, base + config.day_end
        if arrival is not None:
            lo = max(lo, arrival)
        if departure is not None:
            hi = min(hi, departure)
        hi = max(lo, hi)
        busy, attractions, city_spans = [], [], []
        transit_times, distances = [], []
        for i, a in enumerate(acts):
            iv = interval(a, base)
            if a.get('type') not in INTERCITY | {'accommodation'} and iv:
                busy.append((max(lo, iv[0]), min(hi, iv[1])))
                city_spans.append(iv)
                if a['type'] == 'attraction':
                    attractions.append((max(lo, iv[0]), min(hi, iv[1])))
            legs = a.get('transports', [])
            access = incoming_intervals(a, base)
            # The first intercity event's access legs would belong to the origin city.
            target_legs = [] if intercity and a is intercity[0][1] else legs
            durations = [duration(t) for t in target_legs]
            commute = numeric_sum(durations)
            transit_times.extend(durations)
            distances.extend(t.get('distance') for t in target_legs)
            excess('transport', 'long_commute', commute, config.commute_minutes, config.commute_unit, n, i)
            for j, t in enumerate(target_legs):
                tiv = access[j]
                if tiv:
                    busy.append((max(lo, tiv[0]), min(hi, tiv[1])))
                if t.get('mode') == 'walk':
                    excess('transport', 'long_walk', duration(t), config.walk_minutes, config.walk_unit, n, i)
                if duration(t) is None or t.get('distance') is None:
                    unknown.append({'day': n, 'activity': i, 'leg': j, 'metric': 'transport_time_or_distance'})
            if a.get('type') in INTERCITY:
                wait = None
                if legs and access[-1] and clock(a.get('start_time')) is not None:
                    wait = base + clock(a['start_time']) - access[-1][1]
                elif previous[id(a)] and iv:
                    prev_day, prev_activity = previous[id(a)]
                    prev_interval = interval(prev_activity, (prev_day - 1) * 1440)
                    if point(prev_activity, arriving=True) == a.get('start') and prev_interval:
                        wait = iv[0] - prev_interval[1]
                if wait is not None and wait < 0:
                    wait = None
                metrics['waits'].append({'day': n, 'activity': i, 'type': a['type'], 'minutes': wait})
                if wait is None:
                    unknown.append({'day': n, 'activity': i, 'metric': 'station_or_airport_wait'})
                threshold = config.station_wait_minutes if a['type'] == 'train' else config.airport_wait_minutes
                excess('transport', 'station_wait' if a['type'] == 'train' else 'airport_wait', wait, threshold, config.wait_unit, n, i)

        occupied = union(busy)
        busy_minutes = sum(end - start for start, end in occupied)
        cursor, gaps = lo, []
        for start, end in occupied:
            if start > cursor:
                gaps.append(start - cursor)
            cursor = max(cursor, end)
        if hi > cursor:
            gaps.append(hi - cursor)
        playable = hi - lo
        attr_minutes = sum(end - start for start, end in union(attractions))
        attr_count = sum(a.get('type') == 'attraction' for a in acts)
        transit, distance = numeric_sum(transit_times), numeric_sum(distances)
        span = max((x[1] for x in city_spans), default=0) - min((x[0] for x in city_spans), default=0)
        excess('rhythm', 'crowded_day', busy_minutes, config.crowded_minutes, config.rhythm_unit, n)
        excess('rhythm', 'long_day_span', span, config.span_minutes, config.rhythm_unit, n)
        for gap in gaps:
            excess('rhythm', 'idle_gap', gap, config.idle_minutes, config.rhythm_unit, n)
        if playable >= config.playable_minimum:
            add('rhythm', 'too_little_sightseeing', max(0, config.minimum_attraction_minutes - attr_minutes) / config.rhythm_unit,
                n, attr_minutes, config.minimum_attraction_minutes)
            if attr_count == 0:
                add('distribution', 'no_attractions', config.empty_day_penalty, n, 0, 1)
        for kind, begin, end in [('lunch', 720, 840), ('dinner', 1080, 1200)]:
            overlap = max(0, min(hi, base + end) - max(lo, base + begin))
            if overlap >= 60 and not any(a.get('type') == kind for a in acts):
                add('rhythm', 'missing_' + kind, config.missing_meal_penalty, n, 0, 1)
        excess('efficiency', 'daily_transit_time', transit, config.daily_transit_minutes, config.transit_unit, n)
        excess('efficiency', 'daily_transit_distance', distance, config.daily_distance_km, config.distance_unit, n)
        metrics['days'].append({'day': n, 'playable_minutes': playable, 'busy_minutes': busy_minutes,
                                'idle_gaps_minutes': gaps, 'attraction_count': attr_count,
                                'attraction_minutes': attr_minutes, 'city_span_minutes': span,
                                'city_transit_minutes': transit, 'city_transit_km': distance})

        i = 0
        while i < len(acts):
            if acts[i].get('type') not in MEALS:
                i += 1
                continue
            begin = i
            while i < len(acts) and acts[i].get('type') in MEALS:
                i += 1
            after = i
            record = {'day': n, 'meal_activities': list(range(begin, after)),
                      'extra_minutes': None, 'extra_km': None, 'reason': None}
            if begin == 0 or after == len(acts) or route_resolver is None:
                record['reason'] = 'missing_same_day_anchor_or_route_resolver'
            else:
                legs = [t for a in acts[begin:after + 1] for t in a.get('transports', [])]
                mode = 'metro' if any(t.get('mode') == 'metro' for t in legs) else 'taxi' if any(t.get('mode') == 'taxi' for t in legs) else 'walk'
                source, destination = point(acts[begin - 1], True), point(acts[after])
                start_time = legs[0].get('start_time') if legs else acts[begin - 1].get('end_time')
                record.update(start=source, end=destination, mode=mode)
                try:
                    if not source or not destination or start_time is None:
                        raise ValueError('missing_anchor')
                    direct = [] if source == destination else route_resolver(plan['target_city'], source, destination, start_time, mode)
                    if not isinstance(direct, list):
                        raise ValueError('no_direct_route')
                    actual_time, direct_time = numeric_sum(duration(t) for t in legs), numeric_sum(duration(t) for t in direct)
                    actual_km, direct_km = numeric_sum(t.get('distance') for t in legs), numeric_sum(t.get('distance') for t in direct)
                    record.update(actual_minutes=actual_time, direct_minutes=direct_time,
                                  actual_km=actual_km, direct_km=direct_km)
                    if actual_time is not None and direct_time is not None:
                        record['extra_minutes'] = max(0, actual_time - direct_time)
                    if actual_km is not None and direct_km is not None:
                        record['extra_km'] = max(0, actual_km - direct_km)
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    record['reason'] = type(exc).__name__
            excess('efficiency', 'meal_detour_time', record['extra_minutes'], config.meal_detour_minutes, config.meal_detour_time_unit, n, begin)
            excess('efficiency', 'meal_detour_distance', record['extra_km'], config.meal_detour_km, config.meal_detour_distance_unit, n, begin)
            metrics['meal_detours'].append(record)
    raw = {k: round(sum(d['penalty'] for d in details if d['category'] == k), 6) for k in CATEGORIES}
    categories = {k: round(raw[k] * config.weights[k], 6) for k in CATEGORIES}
    waits, meals = metrics['waits'], metrics['meal_detours']
    metrics['total_city_transit_minutes'] = numeric_sum(d['city_transit_minutes'] for d in metrics['days'])
    metrics['total_city_transit_km'] = numeric_sum(d['city_transit_km'] for d in metrics['days'])
    return {'total_penalty': round(sum(categories.values()), 6), 'categories': categories,
            'raw_categories': raw, 'details': details, 'metrics': metrics, 'unknown': unknown,
            'coverage': {'waits_known': sum(w['minutes'] is not None for w in waits), 'waits_total': len(waits),
                         'meal_routes_known': sum(m['extra_minutes'] is not None and m['extra_km'] is not None for m in meals),
                         'meal_routes_total': len(meals)}, 'configuration': asdict(config)}
