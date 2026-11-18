"""Collect exact POIs and dated metro evidence outside the frozen evaluator."""
import argparse
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import sys
from time import sleep

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from shorttrip.dynamic.baidu import BaiduPlaceClient, load_credentials
from shorttrip.dynamic.local_access import (
    CHINA, baidu_evidence, baidu_route_reference, exact_amap_poi, timed_metro, verify_branch,
)
from shorttrip.live_amap import LiveAmapClient, LiveAmapError


def collect(credentials_root, trial_date, evidence):
    amap = LiveAmapClient(credentials_root, budget=5)
    baidu = BaiduPlaceClient(load_credentials(credentials_root / '.secrets/baidu.key'),
                             max_calls=3, cache=False, min_interval_s=1.1)
    name = '同盛祥(凤城五路店)'
    evidence['amap_pois'] = pois = {}
    for key, label, query, category in (
            ('restaurant', name, '同盛祥 凤城五路', '050000'),
            ('station', '西安北站', '西安北站', '150200'),
            ('bell', '西安钟楼', '西安钟楼', '110200')):
        pois[key] = exact_amap_poi(amap, '西安', query, label, category)
        sleep(1.1)
    evidence['baidu_poi'] = baidu_poi = baidu_evidence(baidu, '/place/v2/detail', {
        'uid': '5e5597b0f44a61663617dc49', 'scope': '2',
        'ret_coordtype': 'gcj02ll', 'output': 'json',
    })
    evidence['restaurant'] = restaurant = verify_branch(
        pois['restaurant']['poi'], baidu_poi['response'], city='西安',
        brand='同盛祥', branch='凤城五路店', address_token='26号',
    )
    evidence['routes'] = routes = []
    for day, clock, start, end in (
            (trial_date, time(13, 28), 'station', 'restaurant'),
            (trial_date + timedelta(days=1), time(13, 15), 'bell', 'station')):
        sleep(1.1)
        def coord(key):
            if key == 'restaurant':
                return restaurant['location']
            return list(map(float, pois[key]['poi']['location'].split(',')))
        origin, destination = coord(start), coord(end)
        route = timed_metro(
            amap, city='西安', citycode=pois['station']['poi']['citycode'],
            start=pois[start]['poi']['name'], end=pois[end]['poi']['name'],
            origin=origin, destination=destination,
            departure_at=datetime.combine(day, clock, tzinfo=CHINA).isoformat(),
        )
        routes.append(route)
        try:
            route['baidu_route_reference'] = baidu_route_reference(baidu, origin, destination)
        except LiveAmapError as exc:
            route['baidu_route_reference_error'] = str(exc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials-root', type=Path, required=True)
    parser.add_argument('--trial-date', type=date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    evidence = {'scope': 'dated transfer sample for a benchmark with undated historical intercity data',
                'trial_date': args.trial_date.isoformat()}
    with args.output.open('x', encoding='utf-8') as destination:
        try:
            collect(args.credentials_root, args.trial_date, evidence)
        finally:
            json.dump(evidence, destination, ensure_ascii=False, indent=2)
            destination.write('\n')
    for r in evidence['routes']:
        print(r['departure_at'], r['start'], r['end'], r['legs'][-1]['end_time'],
              r['source_duration_seconds'], r['legs'][1]['cost'])


if __name__ == '__main__':
    main()
