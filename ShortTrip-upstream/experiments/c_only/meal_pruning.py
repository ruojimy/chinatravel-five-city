"""Optimistic necessary C meal checks before expanding a fixed ticket/hotel pair.

Travel between meals is zero and restaurant reuse is relaxed here. Passing is
not a feasible schedule certificate; failing these relaxed conditions is enough
to reject the combination. Existing real-route meal checks remain in DFS.
"""
from chinatravel.agent.nesy_agent.pruning import exceeded, fixed_cost, number, reason
from rules import clock, ticket_interval


def meal_lower_bound(obligations, restaurants, begin, end, hotel_days=()):
    cursor = begin
    minimum_cost = 0
    unknown_rows = restaurants is None
    rows = [] if restaurants is None else restaurants.to_dict('records')
    for o in sorted((o for o in obligations if o['status'] == 'required'),
                    key=lambda o: (o['day'], o['window'][0])):
        choices = []
        lo, hi = o['window']
        duration = o['duration']
        base = (o['day'] - 1) * 1440
        unknown = unknown_rows
        for row in rows:
            try:
                opens, closes = clock(row['opentime']), clock(row['endtime'])
                if closes <= opens:
                    unknown = True
                    continue
            except (ValueError, KeyError, TypeError):
                unknown = True
                continue
            for b, e in o['free_intervals']:
                start = max(cursor, begin, b, lo, base + opens)
                finish = start + duration
                if start < hi and finish <= min(e, end, base + closes):
                    price = number(row.get('price'))
                    choices.append((finish, int(price) if price is not None else 0))
        if o['kind'] == 'breakfast' and o['day'] in hotel_days:
            start, finish = base + 480, base + 510
            if (start >= max(cursor, begin, lo) and start < hi and finish <= end
                    and any(b <= start and finish <= e for b, e in o['free_intervals'])):
                choices.append((finish, 0))
        if unknown:
            # Unknown database information cannot establish impossibility.
            for b, e in o['free_intervals']:
                start = max(cursor, begin, b, lo)
                if start < hi and start + duration <= min(e, end):
                    choices.append((start + duration, 0))
        if not choices:
            return reason('meal_combination_infeasible', o['kind'], day=o['day'],
                          earliest_after=cursor, return_departure=end), None
        cursor = min(finish for finish, _ in choices)
        minimum_cost += min(price for _, price in choices)
    return None, minimum_cost


def preflight(agent, query, poi_plan):
    go = ticket_interval(dict(start_time=poi_plan['go_transport']['BeginTime'],
                              end_time=poi_plan['go_transport']['EndTime'],
                              duration_hours=poi_plan['go_transport'].get('Duration')), 1)
    back = ticket_interval(dict(start_time=poi_plan['back_transport']['BeginTime'],
                                end_time=poi_plan['back_transport']['EndTime'],
                                duration_hours=poi_plan['back_transport'].get('Duration')), query['days'])
    if go['end'] >= back['start']:
        return reason('ticket_chronology', 'outbound arrival < return departure',
                      arrival=go['end'], departure=back['start'])
    hotel_days = range(go['end_day'] + 1, query['days'] + 1) if 'accommodation' in poi_plan else ()
    rejected, food = meal_lower_bound(agent.requirements(poi_plan),
                                     getattr(agent, 'memory', {}).get('restaurants'),
                                     go['end'], back['start'], hotel_days)
    if rejected:
        return rejected
    fixed = fixed_cost(query, poi_plan, getattr(agent, 'required_rooms', None))
    if fixed is not None:
        return exceeded(query, fixed + food * query['people_number'])
    return None
