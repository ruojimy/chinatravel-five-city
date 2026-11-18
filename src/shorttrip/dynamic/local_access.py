"""Capture two-provider POI identity and dated, replayable metro evidence."""
from datetime import datetime, timedelta, timezone
import json
from math import ceil, isfinite
import unicodedata

from geopy.distance import geodesic

from shorttrip.live_amap import LiveAmapError


CHINA = timezone(timedelta(hours=8))


def _normalize(value):
    return unicodedata.normalize('NFKC', value).replace(' ', '')


def baidu_evidence(client, path, params):
    """Keep credentials out of a raw-response evidence bundle."""
    response = client.request(path, params, use_cache=False)
    if str(response.get('status')) != '0':
        raise LiveAmapError(f'baidu_status:{response.get("status")}')
    raw = json.dumps(response, ensure_ascii=False)
    for secret in (client.credentials.ak, client.credentials.sk):
        if secret:
            raw = raw.replace(secret, '[REDACTED]')
    return {'path': path, 'request': params, 'response': json.loads(raw)}


def baidu_route_reference(client, origin, destination):
    """Cross-check the same endpoints; this API supplies an undated estimate."""
    params = {'coord_type': 'gcj02', 'ret_coordtype': 'gcj02', 'steps_info': '1'}
    for key, point in (('origin', origin), ('destination', destination)):
        params[key] = ','.join(f'{x:.6f}' for x in reversed(point))
    return baidu_evidence(client, '/directionlite/v1/transit', params)


def exact_amap_poi(client, city, keyword, exact_name, type_prefix):
    response, request = client._call('/v5/place/text', {
        'keywords': keyword, 'region': city, 'city_limit': 'true',
        'types': type_prefix, 'show_fields': 'business', 'page_size': '10',
        'output': 'JSON',
    })
    hits = [p for p in response.get('pois') or []
            if _normalize(p['name']) == _normalize(exact_name)
            and p.get('cityname', '').removesuffix('市') == city
            and p.get('typecode', '').startswith(type_prefix[:2])
            and p.get('id') and p.get('location')]
    if len(hits) != 1:
        raise LiveAmapError('expected_one_exact_poi')
    return {'poi': hits[0], 'request': request, 'response': response}


def verify_branch(amap, baidu, *, city, brand, branch, address_token, max_distance_m=60):
    """Check identity and address in GCJ-02 before accepting Baidu's location."""
    other = baidu['result']
    names = [_normalize(x['name']) for x in (amap, other)]
    if (amap['cityname'].removesuffix('市') != city
            or other.get('city', '').removesuffix('市') != city
            or not all(name.startswith(brand) and f'({branch})' in name for name in names)
            or not all(address_token in x['address'] for x in (amap, other))
            or not amap['id'] or not other['uid']):
        raise ValueError('POI identity or address conflict')
    lon, lat = map(float, amap['location'].split(','))
    point = (float(other['location']['lat']), float(other['location']['lng']))
    separation = geodesic((lat, lon), point).meters
    if not isfinite(separation) or separation > max_distance_m:
        raise ValueError('POI coordinates disagree')
    return {'name': amap['name'], 'brand': brand, 'city': city, 'coord_system': 'GCJ02',
            'location': [point[1], point[0]], 'amap_id': amap['id'], 'baidu_uid': other['uid'],
            'distance_m': round(separation, 2), 'address': amap['address'],
            'amap_business': amap.get('business', {}), 'baidu_detail': other.get('detail_info', {})}


def _endpoint_name(stop):
    return stop['name']


def _positive_number(value, *, allow_zero=False):
    number = float(value)
    if not isfinite(number) or number < 0 or (not allow_zero and not number):
        raise ValueError('invalid provider measurement')
    return number


def _native_legs(route, start, end, departure):
    """Translate a source walk–single metro–walk path into the native schema."""
    segments = route['segments']
    if len(segments) != 2 or any(
            segment.get(key) for segment in segments for key in ('taxi', 'railway')):
        raise ValueError('route shape outside native schema')
    entry = segments[0].get('bus', {}).get('buslines', [])
    if len(entry) != 1 or segments[1].get('bus', {}).get('buslines'):
        raise ValueError('transfers require a schema upgrade')
    line = entry[0]
    if '地铁' not in line['type']:
        raise ValueError('not a metro line')
    board, alight = map(_endpoint_name, (line['departure_stop'], line['arrival_stop']))
    first, last = [segment['walking'] for segment in segments]
    total = _positive_number(route['cost']['duration'])
    fare = _positive_number(route['cost']['transit_fee'], allow_zero=True)
    # The busline's own duration is sometimes omitted; use the route total
    # less the documented walking time and keep any provider waiting time.
    walk_seconds = [_positive_number(w['cost']['duration'], allow_zero=True) for w in (first, last)]
    ride_seconds = _positive_number(total - sum(walk_seconds))
    minutes = [ceil(seconds / 60) for seconds in (walk_seconds[0], ride_seconds, walk_seconds[1])]
    distances = [_positive_number(item['distance'], allow_zero=True) / 1000 for item in (first, line, last)]
    clocks = [departure]
    for duration in minutes:
        clocks.append(clocks[-1] + timedelta(minutes=duration))
    if clocks[-1].date() != departure.date():
        raise ValueError('native replay supports same-day transfers only')
    places = (start, board, alight, end)
    return [{'start': places[i], 'end': places[i + 1], 'mode': mode,
             'start_time': clocks[i].strftime('%H:%M'), 'end_time': clocks[i + 1].strftime('%H:%M'),
             'distance': distances[i], 'cost': fare if mode == 'metro' else 0}
            for i, mode in enumerate(('walk', 'metro', 'walk'))]


def timed_metro(client, *, city, citycode, start, end, origin, destination, departure_at):
    """Return the first representable route from Amap for these dated endpoints."""
    departure = datetime.fromisoformat(departure_at)
    if departure.tzinfo is None or departure.second or departure.microsecond:
        raise ValueError('local route departure needs an explicit timezone and minute precision')
    departure = departure.astimezone(CHINA)
    claims = client.transit(origin, destination, city1=citycode, city2=citycode,
                            departure_at=departure.isoformat(), mode='metro')
    if not all(c['entity_verified'] and c['mode_requirement_met'] for c in claims):
        raise LiveAmapError('unverified_route_endpoints_or_mode')
    response = json.loads(claims[0]['raw_text'])
    for route in response['route']['transits']:
        try:
            legs = _native_legs(route, start, end, departure)
        except (KeyError, TypeError, AttributeError, ValueError):
            continue
        return {'city': city, 'start': start, 'end': end, 'mode': 'metro',
                'departure': departure.strftime('%H:%M'), 'departure_at': departure.isoformat(),
                'endpoints_gcj02': [list(origin), list(destination)], 'provider': 'amap',
                'evidence_id': claims[0]['evidence_id'], 'legs': legs,
                'source_duration_seconds': int(route['cost']['duration']), 'claims': claims}
    raise LiveAmapError('no_representable_metro_route')
