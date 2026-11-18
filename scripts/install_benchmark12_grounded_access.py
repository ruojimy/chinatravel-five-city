"""Install immutable map and semantic benchmark variants on top of V17."""
import argparse
import csv
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile

from g3_sandbox12_repaired_v17 import PROFILE as BASE, configure
from g3_sandbox12_repaired import REPO
from g3_sandbox12_xiamen import digest
from install_benchmark12_timeline_repair import replace

MODULES = Path('engine/chinatravel/symbol_verification')
ENVIRONMENT = Path('engine/chinatravel/environment')
SOURCE = REPO / 'src/sandbox_runtime/evaluator'
RESTAURANTS = Path('database/restaurants/xian/restaurants_xian.csv')
SCORER = Path('runtime/evaluator/score_tristate.py')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def patch(stage, path, before, after):
    file = stage / path
    file.write_text(replace(file.read_text(encoding='utf-8'), before, after), encoding='utf-8')


def semantic_records(stage):
    sources = ('https://wwj.shaanxi.gov.cn/bsfw/xzfw/202403/P020240321599276872624.pdf',
               'https://www.shaanxi.gov.cn/zfxxgk/fdzdgknr/ghxx/gtzygh/202406/P020240622343901996974.pdf')
    secondary = []
    for name, source in zip(('西安碑林博物馆', '秦始皇兵马俑'), sources):
        secondary.append({'city': '西安', 'name': name, 'category': '历史古迹', 'source': source})
    path = stage / 'database/attractions/xiamen/attractions.csv'
    with path.open(encoding='utf-8-sig', newline='') as file:
        locations = {r['id']: r for r in csv.DictReader(file)}
    parent, child = (locations[key] for key in ('200786859880360', '81835880107231'))
    if (parent['name'], child['name']) != ('嘉庚公园', '嘉庚公园-鳌亭'):
        raise ValueError('The curated park/child pair no longer matches the catalog')
    return {
        'secondary_types': secondary,
        'visit_relations': [{'city': '厦门', 'kind': 'attraction', 'name': parent['name'],
                             'position': child['name'], 'parent_catalog_id': parent['id'],
                             'child_catalog_id': child['id'], 'catalog_sha256': digest(path),
                             'source': 'Frozen catalog entry explicitly identifies 鳌亭 under 嘉庚公园',
                             'corroboration': 'https://www.yeecai.com/tour/showSceneInfo?id=1486'}],
    }


def install_semantic_scoring(stage, *, semantic, branch):
    if semantic:
        records = semantic_records(stage)
    else:
        records = {'secondary_types': [], 'visit_relations': []}
    if branch:
        records['visit_relations'].append({
            'city': branch['city'], 'kind': 'restaurant', 'name': branch['brand'],
            'position': branch['name'], 'amap_id': branch['amap_id'], 'baidu_uid': branch['baidu_uid'],
        })
    write(stage / 'runtime/grounded_places.json', records)
    for filename in ('grounded_places.py', 'grounded_clauses.py'):
        shutil.copyfile(SOURCE / filename, stage / MODULES / filename)
    patch(stage, SCORER, "            env = deepcopy(hard.func_dict)\n",
          """            from chinatravel.symbol_verification.grounded_clauses import grounded_clause
            grounded = grounded_clause(record['key'], clause, plan, hard.func_dict, public['target_city'])
            if grounded is not None:
                hard_results.append({'index': index, 'state': 'pass' if grounded else 'fail',
                                     'evaluator': 'grounded_place_clauses'})
                continue
            env = deepcopy(hard.func_dict)
""")
    if semantic:
        patch(stage, ENVIRONMENT / 'requested_places.py',
              "        positions=[a.get('position') for a in activities if matches(item,a.get('type'),a.get('position'))]",
              """        from chinatravel.symbol_verification.grounded_places import is_registered_target, registered_visit
        city = query.get('target_city')
        if is_registered_target(city, 'attraction', item['key']):
            positions = [a.get('position') for a in activities if a.get('type') in item['kinds']
                         and registered_visit(city, 'attraction', a.get('position'), item['key'])]
        else:
            positions = [a.get('position') for a in activities if matches(item,a.get('type'),a.get('position'))]""")


def install_restaurant(stage, branch):
    sys.path.insert(0, str(REPO / 'src'))
    from shorttrip.dynamic.opendata import gcj02_to_wgs84

    lon, lat = gcj02_to_wgs84(*branch['location'])
    price = float(branch['amap_business']['cost'])
    if not math.isfinite(price) or price <= 0:
        raise ValueError('Missing branch-specific Amap price reference')
    hours = branch['agreed_opening_windows']
    path = stage / RESTAURANTS
    with path.open(encoding='utf-8-sig', newline='') as stream:
        table = list(csv.DictReader(stream))
    if any(r['name'] == branch['name'] for r in table):
        raise ValueError('Restaurant branch already exists')
    next_id = max(int(row['id']) for row in table) + 1
    with path.open('a', encoding='utf-8', newline='') as stream:
        csv.writer(stream, lineterminator='\n').writerow([
            next_id, branch['name'], lat, lon, price, branch['amap_business']['keytag'],
            hours[0][0], hours[-1][1], branch['amap_business']['tag'],
        ])
    poi_path = stage / 'database/poi/xian/poi.json'
    pois = read(poi_path)
    if any(row['name'] == branch['name'] for row in pois):
        raise ValueError('Restaurant branch already has a POI')
    pois.append({'name': branch['name'], 'position': [lat, lon]})
    write(poi_path, pois)
    grade_path = stage / 'runtime/xian_grade_evidence_v3.json'
    grades = read(grade_path)
    # Preserve all earlier grade joins, including the blocked generic name.
    grades['kinds']['restaurant']['csv_sha256'] = digest(path)
    write(grade_path, grades)


def install_maps(stage, evidence):
    branch = evidence['restaurant']
    if not evidence['routes'] or branch['coord_system'] != 'GCJ02':
        raise ValueError('Missing verified route or restaurant location')
    for route in evidence['routes']:
        for claim in route['claims']:
            if (not claim['entity_verified'] or not claim['mode_requirement_met']
                    or sha256(claim['raw_text'].encode()).hexdigest() != claim['raw_sha256']):
                raise ValueError('Missing route provenance or checksum mismatch')
    windows = r'(\d\d:\d\d)-(\d\d:\d\d)'
    amap_times = re.findall(windows, branch['amap_business']['opentime_week'])
    baidu_times = re.findall(windows, branch['baidu_detail']['shop_hours'])
    common = [(max(a, c), min(b, d)) for a, b in amap_times[:len(baidu_times)]
              for c, d in baidu_times if max(a, c) < min(b, d)]
    if not common:
        raise ValueError('No overlapping restaurant hours')
    branch['agreed_opening_windows'] = sorted(set(common))
    install_restaurant(stage, branch)
    write(stage / 'runtime/local_access.json', evidence)
    shutil.copyfile(SOURCE / 'local_route_replay.py', stage / MODULES / 'local_route_replay.py')
    patch(stage, ENVIRONMENT / 'tools/transportation/apis.py',
          '        locationA = start\n',
          '''        from chinatravel.symbol_verification.local_route_replay import frozen_route
        recorded = frozen_route(city, start, end, transport_type, start_time)
        if recorded is not None:
            return [dict(leg) for leg in recorded['legs']]
        locationA = start
''')
    patch(stage, Path('runtime/sandbox_adapter.py'),
          '    def goto(self, city, start, end, mode, departure, people_number=1):',
          '    def goto(self, city, start, end, mode, departure, people_number=1, day=None):')
    patch(stage, Path('runtime/sandbox_adapter.py'),
          '        result = self._goto(city, start, end, mode, departure, people_number)',
          '        result = self._goto(city, start, end, mode, departure, people_number, day=day)')
    patch(stage, Path('runtime/sandbox_adapter.py'),
          '    def _goto(self, city, start, end, mode, departure, people_number):',
          '    def _goto(self, city, start, end, mode, departure, people_number, *, day=None):')
    patch(stage, Path('runtime/sandbox_adapter.py'),
          '        try:\n            result = Transportation(lang=\'zh\').goto(city,start,end,departure,mode)',
          '''        from chinatravel.symbol_verification.local_route_replay import frozen_route, route_day
        evidence = None
        try:
            with route_day(day):
                result = Transportation(lang='zh').goto(city,start,end,departure,mode)
                evidence = frozen_route(city, start, end, mode, departure)''')
    patch(stage, Path('runtime/sandbox_adapter.py'),
          "        return {'city':city,'start':start,'end':end,'mode':mode,'departure':departure,\n                'people_number':people_number,'available':bool(prepared),'legs':prepared,'error':error,",
          """        dated = {}
        if evidence and prepared:
            dated = {'source': 'Amap dated public-transit estimate',
                     'route_scope': 'exact endpoints and supplied Asia/Shanghai departure',
                     'departure_at': evidence['departure_at'], 'evidence_id': evidence['evidence_id']}
        return {'city':city,'start':start,'end':end,'mode':mode,'departure':departure,
                'people_number':people_number,'available':bool(prepared),'legs':prepared,'error':error,""")
    patch(stage, Path('runtime/sandbox_adapter.py'),
          "                'real_world_route_proof':False}\n\nTOOLS",
          "                'real_world_route_proof':False, **dated}\n\nTOOLS")
    patch(stage, MODULES / 'multileg_transport.py',
          '                    sub,notes=legacy_checker(context,synthetic,verbose=False)',
          '''                    from chinatravel.symbol_verification.local_route_replay import route_day
                    with route_day(segment[0].get('start_day', day)):
                        sub,notes=legacy_checker(context,synthetic,verbose=False)''')
    patch(stage, MODULES / 'commonsense_constraint.py',
          '                # if time_compare_if_earlier_equal(endtime, activity_i["start_time"]) or time_compare_if_earlier_equal(activity_i["end_time"], opentime): \n                if not ((contains_visit(select_restaurant, activity_i["start_time"], activity_i["end_time"]) if contains_visit(select_restaurant, activity_i["start_time"], activity_i["end_time"]) is not None else (time_compare_if_earlier_equal(opentime, activity_i["start_time"]) and time_compare_if_earlier_equal(activity_i["end_time"], endtime)))):',
          '''                from chinatravel.symbol_verification.local_route_replay import meal_open
                start, end = activity_i["start_time"], activity_i["end_time"]
                known_open = meal_open(target_city, position, start, end)
                if known_open is None:
                    known_open = contains_visit(select_restaurant, start, end)
                if known_open is None:
                    known_open = time_compare_if_earlier_equal(opentime, start) and time_compare_if_earlier_equal(end, endtime)
                if not known_open:''')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', choices=('v18_map', 'v19_semantics', 'v19_maps'), required=True)
    parser.add_argument('--map-evidence', type=Path)
    args = parser.parse_args()
    if (args.version != 'v19_semantics') != bool(args.map_evidence):
        parser.error('Map variants require --map-evidence')
    parent = configure()
    receipt = read(BASE / 'receipt.json')
    profile = BASE.with_name('xiamen12_historical_' + args.version)
    if profile.exists():
        raise FileExistsError(profile)
    with tempfile.TemporaryDirectory(prefix='.ga-', dir=profile.parent) as tmp:
        stage = Path(tmp) / 'p'
        shutil.copytree(BASE, stage, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        evidence = read(args.map_evidence) if args.map_evidence else {}
        if evidence:
            install_maps(stage, evidence)
        install_semantic_scoring(stage, semantic=args.version != 'v18_map', branch=evidence.get('restaurant'))
        files = {p.relative_to(stage).as_posix(): digest(p) for p in stage.rglob('*')
                 if p.is_file() and p != stage / 'receipt.json'}
        receipt.update(parent_receipt_sha256=parent['receipt_sha256'], scoring_revision=args.version,
                       files=files, map_source_sha256=digest(args.map_evidence) if args.map_evidence else None)
        if evidence:
            receipt['boundary'] = ('Undated historical benchmark with exact dated Amap transfer samples. '
                                   'Intercity fares, live availability and unrecorded routes remain unknown.')
        write(stage / 'receipt.json', receipt)
        stage.rename(profile)
    print(f'{profile} {digest(profile / "receipt.json")}')


if __name__ == '__main__':
    main()
