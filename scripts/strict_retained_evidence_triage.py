"""Inventory retained development evidence without certifying or dispatching it."""
import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from shorttrip.strict_v4_reader import V4Reader


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('diagnostic')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    diagnostic, output = Path(args.diagnostic), Path(args.output)
    if output.exists():
        raise FileExistsError('preserve previous triage output')
    catalog = ROOT / 'data/five_city_reference_v4_20261026/catalog.sqlite3'
    diagnostic_sha, catalog_sha = digest(diagnostic), digest(catalog)
    obj = json.loads(diagnostic.read_text(encoding='utf-8'))
    if obj.get('label') != 'engineering_only_not_formal_evaluation':
        raise ValueError('development engineering diagnostic required')
    reports = obj.get('reports')
    if (obj.get('holdout_per_task_results_generated') is not False or
            not isinstance(reports, list) or not reports or
            any(not isinstance(report, dict) or
                not isinstance(report.get('uid'), str) or
                '-development-' not in report['uid'] for report in reports)):
        raise ValueError('development-only task reports required')
    task_ids = {report['uid'] for report in reports}
    if len(task_ids) != len(reports) or obj.get('development_count') != len(reports):
        raise ValueError('development report inventory inconsistent')
    jobs = obj.get('gap_queue', {}).get('identity_resolution_workflow')
    if not isinstance(jobs, list):
        raise ValueError('development identity queue required')
    entity_ids = [job.get('entity_id') for job in jobs if isinstance(job, dict)]
    if len(entity_ids) != len(jobs) or any(not isinstance(x, str) or not x for x in entity_ids):
        raise ValueError('invalid entity identifier in queue')
    if len(set(entity_ids)) != len(entity_ids):
        raise ValueError('duplicate identity work item')
    if any(not isinstance(job.get('affected_tasks'), list) or not job['affected_tasks'] or
           any(task_id not in task_ids for task_id in job['affected_tasks']) for job in jobs):
        raise ValueError('identity work item is not bound to development reports')
    rows, methods = [], Counter()
    reader = V4Reader(catalog)
    try:
        for entity_id in entity_ids:
            record = reader.get(entity_id)
            for item in record['claims']:
                claim, evidence = item['payload'], item['evidence']
                retained = evidence.get('raw_text')
                raw_hash = evidence.get('raw_sha256')
                encoded = retained.encode('utf-8') if isinstance(retained, str) else None
                matching_digest = bool(encoded is not None and isinstance(raw_hash, str)
                    and hashlib.sha256(encoded).hexdigest() == raw_hash.lower())
                quote = claim.get('quote')
                quote_present = bool(isinstance(quote, str) and quote and
                                     isinstance(retained, str) and quote in retained)
                value = claim.get('value')
                scalar = (type(value) in (str, int, float) and
                          not (type(value) is str and not value) and
                          not (type(value) is float and not math.isfinite(value)))
                literal_reason = ('quote_missing_or_invalid' if not isinstance(quote, str) or not quote else
                                  'value_not_supported_scalar' if not scalar else None)
                literal_in_quote = (str(value) in quote if literal_reason is None else None)
                method = evidence.get('capture_method') or 'unknown'
                methods[method] += 1
                rows.append({'entity_id': entity_id, 'claim_id': claim.get('claim_id'),
                    'evidence_id': evidence.get('evidence_id'), 'native_field': claim.get('native_field'),
                    'capture_method': method, 'retained_text_present': encoded is not None,
                    'retained_text_sha256_matches_record': matching_digest,
                    'exact_quote_in_retained_text': quote_present,
                    'value_literal_in_quote': literal_in_quote,
                    'value_literal_not_applicable_reason': literal_reason,
                    'retained_text_has_unicode_replacement': isinstance(retained, str) and '\ufffd' in retained,
                    'source_published_at_as_stored': evidence.get('source_published_at'),
                    'source_updated_at_as_stored': evidence.get('source_updated_at'),
                    'original_time_text_as_stored': evidence.get('original_time_text'),
                    'observed_at_present': bool(claim.get('observed_at') or evidence.get('observed_at')),
                    'semantic_or_identity_verified': False, 'fetch_authorized': False})
    finally:
        reader.close()
    if diagnostic_sha != digest(diagnostic) or catalog_sha != digest(catalog):
        raise RuntimeError('input changed during triage')
    result = {'label': 'retained_text_triage_not_evidence_acceptance',
        'triage_script_sha256': digest(Path(__file__).resolve()),
        'diagnostic_sha256': diagnostic_sha, 'catalog_sha256': catalog_sha,
        'entity_count': len(entity_ids), 'claim_reference_count': len(rows),
        'unique_evidence_ids': len({r['evidence_id'] for r in rows if r['evidence_id']}),
        'retained_text_present': sum(r['retained_text_present'] for r in rows),
        'retained_text_sha256_matches_record': sum(r['retained_text_sha256_matches_record'] for r in rows),
        'exact_quote_in_retained_text': sum(r['exact_quote_in_retained_text'] for r in rows),
        'value_literal_in_quote': sum(r['value_literal_in_quote'] is True for r in rows),
        'value_literal_not_in_quote': sum(r['value_literal_in_quote'] is False for r in rows),
        'value_literal_not_applicable': sum(r['value_literal_in_quote'] is None for r in rows),
        'retained_text_has_unicode_replacement': sum(r['retained_text_has_unicode_replacement'] for r in rows),
        'observed_at_present': sum(r['observed_at_present'] for r in rows),
        'source_published_at_as_stored_present': sum(bool(r['source_published_at_as_stored']) for r in rows),
        'source_updated_at_as_stored_present': sum(bool(r['source_updated_at_as_stored']) for r in rows),
        'original_time_text_as_stored_present': sum(bool(r['original_time_text_as_stored']) for r in rows),
        'capture_method_reference_counts': dict(sorted(methods.items())),
        'original_http_response_certified': False, 'identity_or_truth_certified': False,
        'network_requests': 0, 'formal_freeze': False,
        'notes': ['Hash compares retained UTF-8 text with a stored digest, not original response bytes.',
                  'Quote presence does not establish value, semantics, source authorization, identity, licence or freshness.',
                  'Value substring is only a triage signal; numeric rendering may already have lost source precision.',
                  'A replacement character proves text loss; its absence does not prove correct encoding.',
                  'Stored publication/update labels retain their original precision and are not treated as observation time.',
                  'Counts are claim references and may repeat evidence.'], 'rows': rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('entity_count', 'claim_reference_count',
          'unique_evidence_ids', 'retained_text_present', 'retained_text_sha256_matches_record',
          'exact_quote_in_retained_text', 'observed_at_present')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
