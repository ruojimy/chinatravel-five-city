"""Seven-kind v4 read-only engineering smoke; not a frozen evaluation."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from shorttrip.strict_gap_queue import build_static_gap_queue
from shorttrip.strict_v4_adapter import diagnose_record
from shorttrip.strict_v4_reader import V4Reader
from shorttrip.strict_independent_verifier import verify_evidence

CITIES = ['西安', '厦门', '宁波', '长沙', '青岛']
CATALOG = ROOT / 'data/five_city_reference_v4_20261026/catalog.sqlite3'
# These are declared probe requirements, not assertions about the records.
# An empty scope intentionally diagnoses missing real room/direction context.
REQUIREMENTS = {
    'attraction': [{'native_field': 'price', 'policy_field': 'price',
                    'scope': {'ticket': 'ordinary_adult', 'currency': 'CNY', 'travel_date': '2026-11-15'}}],
    'restaurant': [{'native_field': 'price', 'policy_field': 'price',
                    'scope': {'meal': 'per_person', 'currency': 'CNY', 'travel_date': '2026-11-15'}}],
    'accommodation': [{'native_field': 'numbed', 'policy_field': 'room_configuration', 'scope': {}}],
    'poi': [{'native_field': 'position', 'policy_field': 'coordinates', 'scope': {'coordinate_system': 'WGS84'}}],
    'metro_station': [{'native_field': 'position', 'policy_field': 'coordinates', 'scope': {'coordinate_system': 'WGS84'}}],
    'train': [{'native_field': 'Duration', 'policy_field': 'intercity_schedule', 'scope': {}}],
    'flight': [{'native_field': 'Duration', 'policy_field': 'intercity_schedule', 'scope': {}}],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True)
    out = Path(ap.parse_args().output)
    if out.exists():
        raise FileExistsError('preserve previous smoke artifact')
    now = datetime.now(timezone.utc).isoformat()
    def audit(_record, _requirement, claim, evidence):
        # v4 raw_text is a method-marked extract, not automatically original
        # HTTP bytes. Preserve its digest separately and never promote it to
        # response_bytes or fabricate a reviewed policy/binding.
        capture = {'retrieved_at': evidence.get('retrieved_at'),
                   'observed_at': evidence.get('observed_at')}
        report = verify_evidence(claim=claim, capture=capture, policy={},
            pinned_policy_sha256='', reviewed_bindings={},
            pinned_reviewed_bindings_sha256='', now=now)
        raw_text = evidence.get('raw_text')
        report['stored_extracted_text_hash_matches'] = (
            hashlib.sha256(raw_text.encode('utf-8')).hexdigest() == evidence.get('raw_sha256')
            if isinstance(raw_text, str) else None)
        report['capture_method'] = evidence.get('capture_method')
        report['source_url'] = evidence.get('source_url')
        return report
    reader = V4Reader(CATALOG)
    try:
        reports = []
        for kind, requirements in REQUIREMENTS.items():
            for entity_id in reader.first_by_city_kind(CITIES, kind):
                record = reader.get(entity_id)
                reports.append(diagnose_record(record, requirements, registry={}, now=now,
                                               uid='seven-kind:' + entity_id,
                                               evidence_auditor=audit))
    finally:
        reader.close()
    queue = build_static_gap_queue(reports)
    result = {'label': 'engineering_smoke', 'evaluation_at': now,
              'catalog_sha256': hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
              'evaluator_sha256': {str(p.relative_to(ROOT)).replace('\\','/'): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in [Path(__file__).resolve(), ROOT/'src/shorttrip/strict_v4_adapter.py',
                            ROOT/'src/shorttrip/strict_snapshot.py', ROOT/'src/shorttrip/strict_scope.py',
                            ROOT/'src/shorttrip/strict_independent_verifier.py', ROOT/'src/shorttrip/strict_gap_queue.py',
                            ROOT/'src/shorttrip/strict_identity_review.py', ROOT/'src/shorttrip/strict_v4_evidence.py',
                            ROOT/'src/shorttrip/strict_evidence.py', ROOT/'src/shorttrip/collection_workflow.py',
                            ROOT/'src/shorttrip/strict_v4_reader.py', ROOT/'src/shorttrip/freshness.py',
                            ROOT/'src/shorttrip/expansion_contract.py']},
              'requirements': REQUIREMENTS, 'approved_source_profiles': {},
              'reports': reports, 'gap_queue': queue, 'formal_cohort': False,
              'truth_certified': False, 'execution_confirmed': False}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'records': len(reports), 'cities': len(CITIES),
                      'kinds': len(REQUIREMENTS), 'static_jobs': len(queue['static_jobs']),
                      'unresolved_data_gaps': len(queue['unresolved'])}))


if __name__ == '__main__':
    main()
