"""Read-only five-city engineering smoke; not an evaluation cohort."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from shorttrip.strict_v4_reader import V4Reader
from shorttrip.strict_v4_adapter import diagnose_record

CITIES = ['西安', '厦门', '宁波', '长沙', '青岛']
CATALOG = ROOT / 'data/five_city_reference_v4_20261026/catalog.sqlite3'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    output=Path(parser.parse_args().output).resolve()
    if output.exists():
        raise FileExistsError('Preserve immutable smoke artifact')
    now = datetime.now(timezone.utc).isoformat()
    reader = V4Reader(CATALOG)
    try:
        ids = reader.first_by_city_kind(CITIES, 'attraction')
        reports = []
        for entity_id in ids:
            record = reader.get(entity_id)
            requirements = [{'native_field':'price', 'policy_field':'price',
                             'scope':{'ticket':'ordinary_adult', 'currency':'CNY'}}]
            # No source profile is promoted from the historical blanket registry.
            reports.append(diagnose_record(record, requirements, registry={}, now=now,
                                           uid='smoke:' + entity_id))
        result = {'label':'engineering_smoke', 'evaluation_at':now,
                  'catalog':'data/five_city_reference_v4_20261026/catalog.sqlite3',
                  'catalog_sha256':hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
                  'adapter_sha256':hashlib.sha256((ROOT/'src/shorttrip/strict_v4_adapter.py').read_bytes()).hexdigest(),
                  'evidence_gate_sha256':hashlib.sha256((ROOT/'src/shorttrip/strict_evidence.py').read_bytes()).hexdigest(),
                  'cities':CITIES, 'registry_policy':'empty pending field-specific reviewed profiles',
                  'requirements':requirements, 'formal_cohort':False,
                  'execution_confirmed':False, 'reports':reports,
                  'repair_queue':[g for r in reports for g in r['repair_queue']]}
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'artifact':str(output),'records':len(reports),
                          'data_blocked':sum(bool(r['axes']['data']) for r in reports),
                          'adapter_blocked':sum(bool(r['axes']['adapter']) for r in reports),
                          'repair_jobs':len(result['repair_queue'])},ensure_ascii=False))
    finally:
        reader.close()

if __name__ == '__main__': main()
