"""Offline five-city plan diagnostic smoke, not a planner evaluation."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from shorttrip.strict_plan_diagnostics import diagnose_plan
from shorttrip.strict_v4_reader import V4Reader

CITIES = ['西安', '厦门', '宁波', '长沙', '青岛']
CATALOG = ROOT / 'data/five_city_reference_v4_20261026/catalog.sqlite3'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    output = Path(parser.parse_args().output).resolve()
    if output.exists():
        raise FileExistsError('Preserve immutable smoke artifact')
    now = datetime.now(timezone.utc).isoformat()
    reader = V4Reader(CATALOG)
    try:
        ids = reader.first_by_city_kind(CITIES, 'attraction')
        reports = []
        requirements = [{'native_field': 'price', 'policy_field': 'price',
                         'scope': {'ticket': 'ordinary_adult', 'currency': 'CNY'}}]
        for city, entity_id in zip(CITIES, ids):
            record = reader.get(entity_id)
            candidate = {
                'activity': {'start': datetime(2026, 11, 2, 10),
                             'end': datetime(2026, 11, 2, 11), 'windows': None},
                'route_requirement': {'context': {'origin': 'unknown', 'destination': city}},
                'route_evidence': {},
                'required_costs': [None], 'budget': 500,
            }
            reports.append(diagnose_plan(
                uid='plan-smoke:' + city, city=city,
                record_requirements=[(record, requirements)], registry={}, now=now,
                candidate=candidate))
        result = {
            'label': 'engineering_smoke', 'evaluation_at': now,
            'catalog': 'data/five_city_reference_v4_20261026/catalog.sqlite3',
            'catalog_sha256': hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
            'cities': CITIES, 'record_ids': ids,
            'registry_policy': 'empty; no field-specific source profiles approved',
            'requirements': requirements,
            'candidate_unknowns': ['opening schedule', 'route evidence', 'required cost'],
            'formal_cohort': False, 'planner_completeness_claimed': False,
            'execution_confirmed': False, 'reports': reports,
            'repair_queue': [g for report in reports for g in report['repair_queue']],
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'artifact': str(output), 'records': len(reports),
                          'outcomes': [r['outcome'] for r in reports],
                          'formal_cohort': False,
                          'repair_jobs': len(result['repair_queue'])}, ensure_ascii=False))
    finally:
        reader.close()


if __name__ == '__main__':
    main()
