"""Compare the original 36 requests on V19 and V20, including date-scoped prices."""
from collections import Counter
from math import isfinite
from datetime import date, datetime, timedelta
from pathlib import Path
import json

from g3_sandbox12_repaired_v20 import configure

REPO = Path(__file__).resolve().parents[1]
RUN = REPO / 'results/v19-20261118/luna_v19_standard_36'
BASE = REPO / 'results/v20-20261119'


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def minutes(clock):
    hrs,mns=map(int,clock.split(':'))
    return hrs*60+mns


def service_rows(result, mode):
    unique={}
    for item in result['records']:
        service=item['record']['payload']['data']
        price=service.get('Cost')
        if type(price) not in (int,float) or not isfinite(price) or price < 0:
            continue
        try:
            start,end=map(minutes,(service['BeginTime'],service['EndTime']))
            duration=round(float(service['Duration'])*60)
        except (KeyError,TypeError,ValueError):
            continue
        if duration<=0 or abs((start+duration-end) % 1440) not in (0,1,1439):
            continue
        service_id=service['TrainID' if mode=='train' else 'FlightID']
        key=(mode,service_id,service['From'],service['To'],start,end,price)
        unique[key]={'mode':mode, 'service':service_id,'from':service['From'],'to':service['To'],
                     'start':start,'arrives':start+duration,'price':price}
    return list(unique.values())


def intercity_lower_bound(outbound,returning,days):
    best=None
    for a in outbound:
        for b in returning:
            day=((days*1440-1-b['arrives'])//1440) if b['arrives'] <days*1440 else -1
            departure=day*1440+b['start']
            if day<0 or departure<=a['arrives']:
                continue
            price=a['price']+b['price']
            if best is None or price < best['fare_per_person']:
                best={'fare_per_person':price,'outbound':a,'return':{**b,'departure_day':day+1},
                      'destination_window_minutes':departure-a['arrives']}
    return best

FIRST = date(2026, 11, 20)


def dated_pairs(outbound, returning, finish, people, budget):
    pairs = []
    for a in outbound:
        arrival = datetime.fromisoformat(a['arrival'])
        for b in returning:
            departure = datetime.fromisoformat(b['departure'])
            gap = round((departure - arrival).total_seconds() / 60)
            if gap <= 0 or datetime.fromisoformat(b['arrival']).date() > finish:
                continue
            price = round((a['fare_cny'] + b['fare_cny']) * people, 2)
            pairs.append({'outbound': a, 'return': b, 'party_displayed_fare': price,
                          'passes_displayed_fare_cutoff': budget is None or price <= budget,
                          'destination_window_minutes': gap})
    if not pairs:
        return None, None
    cheapest = min(pairs, key=lambda p: (p['party_displayed_fare'], -p['destination_window_minutes']))
    window = max((p for p in pairs if p['passes_displayed_fare_cutoff']),
                 key=lambda p: (p['destination_window_minutes'], -p['party_displayed_fare']), default=None)
    return cheapest, window


def preflight(box, profile):
    baseline = read(RUN / 'transport_preflight.json')
    if len(baseline['cases']) != 36:
        raise ValueError('Expected the frozen paired 36-case cohort')
    results, historical, dated = {}, {}, {}
    for uid, original in baseline['cases'].items():
        q = read(RUN / 'private' / f'{uid}.json')
        origin, dest = q['start_city'], q['target_city']
        party, days, budget = q['people_number'], q['days'], original['budget_ceiling']
        finish = FIRST + timedelta(days=days-1)
        v19_pair = original['pair_floor']
        dirs, observations, routes = [], [], []
        for a, b, day in ((origin, dest, FIRST), (dest, origin, finish)):
            v20_direction, sample = [], []
            for mode in original['allowed_intercity_modes']:
                key = (a, b, mode)
                if key not in historical:
                    result = box.intercity_search(a, b, mode)
                    if result['errors']:
                        raise RuntimeError(result['errors'])
                    historical[key] = service_rows(result, mode)
                    if result['dated_observations']:
                        raise AssertionError('An undated search exposed dated quotes')
                v20_direction.extend(historical[key])
                dated_key = (*key, day)
                if dated_key not in dated:
                    result = box.intercity_search(a, b, mode, travel_date=day.isoformat())
                    dated[dated_key] = result['dated_observations']
                    if any(r['strict_budget_eligible'] or r['departure'][:10] != day.isoformat() for r in dated[dated_key]):
                        raise AssertionError('Dated quote promoted outside its admission gate')
                sample.extend(dated[dated_key])
                routes.append({'route': [a, b], 'mode': mode, 'sample_date': day.isoformat(),
                               'dated_seat_observations': len(dated[dated_key]),
                               'distinct_dated_services': len({r['service'] for r in dated[dated_key]})})
            dirs.append(v20_direction)
            observations.append(sample)
        v20_pair = intercity_lower_bound(*dirs, days)
        if v19_pair != v20_pair:
            raise AssertionError(f'Frozen intercity result drifted for {uid}')
        cheapest, window = dated_pairs(*observations, finish, party, budget)
        v19_budget = v19_pair is not None and not original['intercity_floor_above_budget']
        results[uid] = {
            'id': uid, 'question': q['nature_language'], 'difficulty': uid.split('-')[2][0],
            'origin': origin, 'destination': dest, 'days': days, 'party': party, 'budget': budget,
            'allowed_modes': original['allowed_intercity_modes'],
            'v19_pair': v19_pair, 'v20_undated_pair': v20_pair, 'v19_passed_fare_cutoff': v19_budget,
            'dated_sample_routes': routes, 'cheapest_sample_pair': cheapest, 'longest_under_budget_pair': window,
            'any_clock_pair_v19_or_sample': bool(v19_pair or cheapest),
            'passes_fare_cutoff_v19_or_sample': bool(v19_budget or (cheapest and cheapest['passes_displayed_fare_cutoff'])),
        }
    summaries = {}
    for city in ('西安', '厦门'):
        rows = [row for row in results.values() if row['destination'] == city]
        summaries[city] = {'n': len(rows), 'v19_clock': sum(bool(x['v19_pair']) for x in rows),
                           'v19_under_budget': sum(x['v19_passed_fare_cutoff'] for x in rows),
                           'with_dated_sample_clock': sum(x['any_clock_pair_v19_or_sample'] for x in rows),
                           'with_dated_sample_fare_cutoff': sum(x['passes_fare_cutoff_v19_or_sample'] for x in rows),
                           'clock_changed': [x['id'] for x in rows if not x['v19_pair'] and x['cheapest_sample_pair']],
                           'fare_cutoff_changed': [x['id'] for x in rows if not x['v19_passed_fare_cutoff']
                                                  and x['passes_fare_cutoff_v19_or_sample']]}
    return {'profile': profile, 'v19_profile_receipt_sha256': baseline['profile_receipt_sha256'],
            'sample_start': FIRST.isoformat(), 'scope': 'Necessary direct-service date, clock and fare checks. Air fees, actual booking and station transfers are unresolved.',
            'cities': summaries, 'cases': results}


def catalog(box):
    out = {}
    for city in box.cities:
        out[city] = {}
        for kind in ('attraction', 'restaurant', 'accommodation'):
            counts = Counter()
            for _, record in box._eligible(kind, city):
                payload = record['payload']
                data, access = payload['data'], payload['access']
                counts['eligible'] += 1
                counts['has_position'] += int(access['planning_position_available'])
                counts['has_price'] += int(data.get('price') is not None)
                counts['all_required_fields'] += int(not access['planning_required_missing'])
                completion = access.get('catalog_completion', {})
                if kind != 'accommodation':
                    counts[completion['status']] += 1
                    counts['mapped_numeric'] += int(bool(completion['mapped_codes'] and completion['values']))
                    counts['known_cuisine_from_empty'] += int(kind == 'restaurant'
                        and completion['original_value'] is None and bool(completion['values']))
                    counts['new_operating_field_records'] += int(bool(
                        completion['filled_fields'].keys() & {'price', 'opentime', 'endtime'}))
                else:
                    counts['has_bed_count'] += int(data.get('numbed') is not None and data['numbed'] > 0)
            out[city][kind] = counts
    return out


def smoke(box):
    from chinatravel.environment.tools.restaurants.apis import Restaurants
    from chinatravel.symbol_verification.concept_func import func_dict
    from chinatravel.symbol_verification.grounded_clauses import grounded_clause, _CATEGORY, _CUISINE

    result = box.catalog_search('restaurant', '西安', cuisine='陕菜')
    assert any(r['name'] == '西安饭庄' for r in result['records'])
    frame = Restaurants(lang='zh').select('西安', key='name', func=lambda n: n == '西安饭庄')
    assert len(frame) == 1 and frame.iloc[0]['cuisine'] == '陕西菜'
    museum = box.catalog_search('attraction', '西安', category='博物馆')
    assert any(r['name'] == '西安博物院' for r in museum['records'])
    assert not any(r['name'] == '兴庆宫公园' for r in museum['records'])
    # Use native lookup functions and the evaluator's audited clause entry point.
    functions = {**func_dict, 'allactivities': lambda plan: plan}
    for key, template, item, label, outcome in (
            ('required_attraction_types', _CATEGORY, {'type': 'attraction', 'position': '西安博物院'}, '博物馆', True),
            ('required_attraction_types', _CATEGORY, {'type': 'attraction', 'position': '兴庆宫公园'}, '博物馆', False),
            ('cuisine', _CUISINE, {'type': 'lunch', 'position': '西安饭庄'}, '陕菜', True),
            ('cuisine', _CUISINE, {'type': 'lunch', 'position': '西安饭庄'}, '粤菜', False)):
        clause = template.replace('{required}', repr({label}))
        assert grounded_clause(key, clause, [item], functions, '西安') is outcome
    assert box.catalog_entity('attraction:xian:100')['payload']['data']['price'] == 54
    assert box.catalog_entity('attraction:xiamen:257538151989012')['payload']['data']['opentime'] == '06:00'
    botanical = box.catalog_entity('attraction:xiamen:216163219282179')
    assert botanical['payload']['data']['price'] == 30
    assert botanical['payload']['access']['main_path']
    hotel = box.catalog_entity('accommodation:xian:760')
    assert hotel['payload']['access']['catalog_completion']['evidence']['historical_room_stay_cny'] == 594.66
    from chinatravel.environment.tools.poi.apis import Poi
    poi = Poi(lang='zh')
    for name, price in (('厦门园林植物园', 30), ('日光岩', 50), ('菽庄花园', 30)):
        result = box.catalog_search('attraction', '厦门', name)
        exact = next(r for r in result['records'] if r['name'] == name)['payload']
        assert exact['access']['main_path'] and exact['data']['price'] == price
        assert poi.search('厦门', name) == (exact['data']['lat'], exact['data']['lon'])
    assert not box.intercity_search('北京', '厦门', 'airplane', travel_date='2026-11-21')['dated_observations']


def main():
    profile = configure()
    from sandbox_adapter import Sandbox
    box = Sandbox('G3')
    smoke(box)
    audit = preflight(box, profile)
    archived = read(BASE / 'transport_preflight_v19_v20.json')
    if archived['profile']['public_receipt_sha256'] != profile['receipt_sha256']:
        raise ValueError('Published profile receipt changed')
    for key in ('sample_start', 'v19_profile_receipt_sha256', 'cities', 'cases'):
        if archived[key] != audit[key]:
            raise AssertionError(f'Published comparison did not reproduce: {key}')
    if read(BASE / 'catalog_audit_v20.json')['cities'] != catalog(box):
        raise AssertionError('Published catalog audit did not reproduce')
    print(f"Reproduced {len(audit['cases'])} transport comparisons and twelve-city catalog totals.")
    for city, result in audit['cities'].items():
        print(city, result)
    for row in audit['cases'].values():
        if not row['v19_passed_fare_cutoff']:
            pair = row['cheapest_sample_pair']
            print(row['id'], [pair[k] for k in ('party_displayed_fare', 'destination_window_minutes')]
                  if pair else 'no dated pair')


if __name__ == '__main__':
    main()
