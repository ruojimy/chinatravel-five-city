"""Project evidence-aware P21 plans into the official ChinaTravel shape without inventing numbers.

A projection is ready only when every official activity has numeric cost/price and every
transport has the official required numeric/time fields. Otherwise the missing fields are
reported and no native plan is emitted.
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/p21_flash_fixed'
OFFICIAL = {'attraction', 'lunch', 'dinner', 'breakfast', 'accommodation'}


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def main():
    protocol = load(OUT / 'public/protocol.json')
    schema = load(ROOT / 'ChinaTravel/chinatravel/evaluation/output_schema.json')
    queries = {q['case_id']: q for q in load(OUT / 'public/queries.json')}
    entries = {}
    for p in sorted((OUT / 'plans').glob('*/*.json')):
        cid, stage = p.parent.name, p.stem
        answer = load(p)
        plan = answer['proposed_plan']
        missing = []
        days = []
        for day in plan.get('itinerary', []):
            acts = []
            for a in day.get('activities', []):
                if a.get('type') not in OFFICIAL:
                    missing.append(f'activity:{a.get("type")}:not_official_type')
                    continue
                for key in ('cost', 'price'):
                    if not isinstance(a.get(key), (int, float)) or isinstance(a.get(key), bool):
                        missing.append(f'activity:{a.get("type")}:{key}')
                transports = []
                for t in a.get('transports') or []:
                    for key in ('start', 'end', 'mode', 'start_time', 'end_time', 'price', 'cost', 'distance'):
                        if t.get(key) is None:
                            missing.append(f'transport:{a.get("type")}:{key}')
                    if all(t.get(k) is not None for k in ('start', 'end', 'mode', 'start_time', 'end_time',
                                                          'price', 'cost', 'distance')):
                        transports.append({k: t[k] for k in ('start', 'end', 'mode', 'start_time', 'end_time',
                                                             'price', 'cost', 'distance')})
                acts.append({'type': a['type'], 'start_time': a['start_time'], 'end_time': a['end_time'],
                             'position': a.get('position', ''), 'cost': a.get('cost'), 'price': a.get('price'),
                             'transports': transports})
            days.append({'day': day.get('day'), 'activities': acts})
        projected = {'people_number': plan.get('people_number'), 'start_city': plan.get('start_city'),
                     'target_city': plan.get('target_city'), 'itinerary': days}
        schema_errors = []
        if not missing:
            schema_errors = [{'path': list(e.absolute_path), 'message': e.message}
                             for e in Draft7Validator(schema).iter_errors(projected)]
        entries[f'{cid}/{stage}'] = {
            'case_id': cid, 'stage': stage,
            'ready': not missing and not schema_errors,
            'missing_fields': sorted(set(missing))[:40],
            'missing_count': len(set(missing)),
            'projected_activity_count': sum(len(d['activities']) for d in days),
            'schema_errors': schema_errors[:20] if not missing else [],
            'note': 'No numeric field is invented. Missing fields block the native projection.',
        }
    result = {'at': None, 'entries': entries,
              'ready': sum(1 for x in entries.values() if x['ready']),
              'blocked': sum(1 for x in entries.values() if not x['ready']),
              'note': 'Official schema projection audit; blocked is not a fabricated plan.'}
    (OUT / 'native_projection.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'ready': result['ready'], 'blocked': result['blocked'],
                      'entries': {k: (v['ready'], v['missing_count']) for k, v in entries.items()}},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
