"""Build or replay residual V17 cases with a receipt-checked sandbox."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import runpy
import sys

from g3_sandbox12_repaired import configure
from g3_sandbox12_repaired_v17 import PROFILE

MEAL = '同盛祥(凤城五路店)'
XI_HOTEL = '宜家假日旅游民宿酒店(钟楼回民街店)'
XM_HOTEL = '汉庭优佳酒店(厦门植物园白鹭洲路店)'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


class Replay:
    def __init__(self, sandbox, query):
        self.sandbox = sandbox
        self.query = query
        self.city = query['target_city']
        self.people = query['people_number']
        self.trace = []

    def call(self, name, **args):
        result = getattr(self.sandbox, name)(**args)
        self.trace.append({'tool': name, 'args': args, 'result': result})
        return result

    def transfer(self, day, start, end, departure, mode):
        if start == end:
            return []
        context = {'day': day} if os.environ.get('CT_LOCAL_ROUTE_TRIAL_START_DATE') else {}
        result = self.call('goto', city=self.city, start=start, end=end, departure=departure,
                           mode=mode, people_number=self.people, **context)
        if not result['available']:
            raise ValueError(result['error'])
        return result['legs']

    def rail(self, origin, destination, train_id, transports, *, next_day=False):
        result = self.call('intercity_search', from_city=origin, to_city=destination, mode='train')
        records = [r['record']['payload']['data'] for r in result['records']]
        record = next(r for r in records if r['TrainID'] == train_id)
        activity = {
            'type': 'train', 'TrainID': train_id, 'start': record['From'], 'end': record['To'],
            'start_time': record['BeginTime'], 'end_time': record['EndTime'], 'price': record['Cost'],
            'tickets': self.people, 'cost': record['Cost'] * self.people, 'transports': transports,
        }
        if next_day:
            activity['arrival_day'] = 2
        return activity

    def visit(self, category, name, start, end, transports, *, rooms=None, price_override=None):
        kind = 'restaurant' if category in ('lunch', 'dinner') else category
        result = self.call('catalog_search', kind=kind, city=self.city, text=name, limit=8)
        record = next(r['payload'] for r in result['records'] if r['name'] == name)
        price = record['data']['price'] if price_override is None else price_override
        activity = {'type': category, 'position': name, 'start_time': start, 'end_time': end,
                    'price': price, 'cost': price * (rooms or self.people), 'transports': transports}
        if rooms is not None:
            activity['rooms'] = rooms
        if category == 'attraction':
            activity['tickets'] = self.people
        return activity

    def plan(self, *days):
        return {'start_city': self.query['start_city'], 'target_city': self.city,
                'people_number': self.people,
                'itinerary': [{'day': i, 'activities': activities} for i, activities in enumerate(days, 1)]}


def tongshengxiang(replay):
    station, bell, drum = '西安北站', '西安钟楼', '西安鼓楼'
    station_mode = 'metro' if os.environ.get('CT_LOCAL_ROUTE_TRIAL_START_DATE') else 'taxi'
    return replay.plan([
        replay.rail('苏州', '西安', 'G1970', []),
        replay.visit('lunch', MEAL, '13:57', '14:25',
                     replay.transfer(1, station, MEAL, '13:28', station_mode)),
        replay.visit('attraction', drum, '15:10', '16:00',
                     replay.transfer(1, MEAL, drum, '14:25', 'taxi')),
        replay.visit('accommodation', XI_HOTEL, '16:20', '08:30',
                     replay.transfer(1, drum, XI_HOTEL, '16:00', 'walk'), rooms=2),
    ], [
        replay.visit('attraction', bell, '12:15', '13:15',
                     replay.transfer(2, XI_HOTEL, bell, '11:55', 'walk')),
        replay.rail('西安', '苏州', 'G1976',
                    replay.transfer(2, bell, station, '13:15', station_mode)),
    ])


def overnight_xiamen(replay):
    station, sight, meal = '厦门北站', '中山路步行街', '黄则和花生汤(中山路店)'
    return replay.plan([
        replay.rail('北京', '厦门', 'D131', [], next_day=True),
    ], [
        replay.visit('attraction', sight, '11:20', '12:00',
                     replay.transfer(2, station, sight, '10:24', 'taxi'), price_override=0),
        replay.visit('lunch', meal, '12:15', '13:00',
                     replay.transfer(2, sight, meal, '12:00', 'walk')),
        replay.visit('accommodation', XM_HOTEL, '15:00', '07:15',
                     replay.transfer(2, meal, XM_HOTEL, '14:40', 'taxi'), rooms=1),
    ], [
        replay.rail('厦门', '北京', 'G966',
                    replay.transfer(3, XM_HOTEL, station, '07:45', 'taxi')),
    ])


def chongqing_same_day(replay):
    station, bell, drum, meal = '西安北站', '西安钟楼', '西安鼓楼', '西安饭庄'
    return replay.plan([
        replay.rail('重庆', '西安', 'G3782', []),
        replay.visit('lunch', meal, '13:20', '14:00',
                     replay.transfer(1, station, meal, '12:40', 'taxi')),
        replay.visit('attraction', bell, '14:25', '15:10',
                     replay.transfer(1, meal, bell, '14:00', 'taxi')),
        replay.visit('attraction', drum, '15:25', '16:10',
                     replay.transfer(1, bell, drum, '15:10', 'walk')),
        replay.rail('西安', '重庆', 'D1991',
                    replay.transfer(1, drum, station, '16:12', 'taxi')),
    ])


def score(profile, source, uid, file, output):
    sys.argv = ['score_tristate', '--target-root', str(profile / 'engine'),
                '--query', str(source / 'private' / f'{uid}.json'),
                '--audit', str(source / 'private' / f'{uid}.audit.json'),
                '--plan', str(file), '--output', str(output)]
    runpy.run_path(str(profile / 'runtime/evaluator/score_tristate.py'), run_name='__main__')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--profile', choices=('v17', 'v18_map', 'v19_semantics', 'v19_maps'), required=True)
    ap.add_argument('--uid', required=True)
    ap.add_argument('--plan', type=Path)
    ap.add_argument('--build', action='store_true')
    ap.add_argument('--probe', action='store_true')
    ap.add_argument('--without-timed-routes', action='store_true',
                    help='Score the plan without matching the trial date, leaving POI evidence enabled')
    args = ap.parse_args()
    uid, source, output = args.uid, args.source.resolve(), args.output.resolve()
    profile = PROFILE.with_name('xiamen12_historical_' + args.profile)
    configuration = configure(profile=profile)
    os.environ.pop('CT_LOCAL_ROUTE_TRIAL_START_DATE', None)
    access = profile / 'runtime/local_access.json'
    if access.is_file() and not args.without_timed_routes:
        os.environ['CT_LOCAL_ROUTE_TRIAL_START_DATE'] = read(access)['trial_date']
    query = read(source / 'public' / f'{uid}.json')
    if args.build or args.probe:
        from sandbox_adapter import Sandbox
        replay = Replay(Sandbox('G3'), query)
        try:
            if args.build:
                make_plan = {'x11e019': tongshengxiang, 'xm27n001': overnight_xiamen,
                             'x11h003': chongqing_same_day}[uid]
                plan = make_plan(replay)
                args.plan = output / 'plan.json'
                write(args.plan, plan)
            elif uid == 'xm27g002':
                replay.call('ferry_reference', city='厦门')
            else:
                a, b = query['start_city'], query['target_city']
                for mode in (('airplane', 'train') if uid == 'x11h003' else ('airplane',)):
                    for origin, destination in ((a, b), (b, a)):
                        replay.call('intercity_search', from_city=origin, to_city=destination, mode=mode)
        finally:
            write(output / 'trace.json', {'uid': uid, 'configuration': configuration, 'calls': replay.trace})
    if not args.probe:
        if args.plan is None:
            ap.error('--plan or --build required for scoring')
        score(profile, source, uid, args.plan.resolve(), output / 'score.json')


if __name__ == '__main__':
    main()
