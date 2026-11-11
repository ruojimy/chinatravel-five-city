"""Validate P20 artifacts, freeze hashes and JSON integrity; rebuild the manifest."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/p20_deepseek_dynamic_sandbox'


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def digest(p):
    h = hashlib.sha256()
    with open(p, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    checks = []

    def check(name, ok, detail=None):
        checks.append({'name': name, 'ok': bool(ok), 'detail': detail})
        return ok

    protocol = load(OUT / 'public/protocol.json')
    catalog = ROOT / protocol['baseline']['catalog']
    check('baseline_sha256', digest(catalog) == protocol['baseline']['sha256'],
          protocol['baseline']['sha256'])
    freeze = load(OUT / 'private/freeze.json')
    mismatches = [f for f, h in freeze['files'].items() if digest(ROOT / f) != h]
    check('freeze_hashes', not mismatches, mismatches)
    queries = load(OUT / 'public/queries.json')
    plans = sorted((OUT / 'plans').glob('*/*.json'))
    check('query_count', len(queries) == 4, len(queries))
    check('plan_count', len(plans) == 9, [str(p.relative_to(OUT)) for p in plans])
    expected = {(q['case_id'], s) for q in queries for s in ('static_first', 'dynamic_first')}
    expected.add(('D03', 'revised'))
    actual = {(p.parent.name, p.stem) for p in plans}
    check('expected_stages', actual == expected, sorted(expected - actual) + sorted(actual - expected))
    evaluation = load(OUT / 'evaluation.json')
    check('evaluation_plans', len(evaluation['evaluations']) == 9, len(evaluation['evaluations']))
    check('strict_acceptance_zero', evaluation['metrics']['strict_accepted'] == 0,
          evaluation['metrics']['strict_accepted'])
    claims = load(OUT / 'overlay/v001/claims.json')['claims']
    check('claim_count', len(claims) == 21, len(claims))
    gates = {c['ingest_verdict']['status'] for c in claims}
    check('all_claims_unverified', gates == {'unverified'}, sorted(gates))
    check('no_hard_claims', not any(c['ingest_verdict']['usable_as_hard_fact'] for c in claims))
    check('no_labelled_estimates', not any(c['ingest_verdict']['usable_as_labelled_estimate'] for c in claims))
    search_queries = sum(len(load(p)['queries']) for p in (OUT / 'live').glob('search_*.json'))
    opens = list((OUT / 'live').glob('open_*.json'))
    failed = list((OUT / 'live').glob('open_*.failed.json'))
    check('search_budget', search_queries <= 16, search_queries)
    check('open_budget', len(opens) + len(failed) <= 24, len(opens) + len(failed))
    bad_json = []
    for pattern in ('events/*/*.json', 'logs/*.json', 'plans/*/*.json', 'live/*.json',
                    'live/*.failed.json', 'agent_state/*.json', 'overlay/v001/*.json'):
        for p in OUT.glob(pattern):
            try:
                load(p)
            except Exception as exc:  # noqa: BLE001
                bad_json.append({'file': str(p), 'error': f'{type(exc).__name__}: {exc}'})
    check('json_integrity', not bad_json, bad_json[:10])
    check('report_exists', (OUT / 'REPORT.md').exists() and (OUT / 'REPORT.md').stat().st_size > 5000)
    check('summary_exists', (OUT / 'summary.json').exists())
    check('manifest_exists', (OUT / 'manifest.json').exists())
    result = {'at': datetime.now(timezone.utc).isoformat(), 'ok': all(c['ok'] for c in checks),
              'checks': checks, 'no_truth_certification': True}
    (OUT / 'validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    scripts = [ROOT / 'scripts' / name for name in ('p20_agent.py', 'p20_live_fetch.py', 'p20_extract_live.py',
                                                    'p20_ingest_overlay.py', 'p20_evaluate.py', 'p20_report.py',
                                                    'p20_validate.py')]
    files = [p for p in OUT.rglob('*') if p.is_file() and p.name not in ('manifest.json', 'current_evaluation.json')
             and not p.name.endswith(('-wal', '-shm'))] + scripts
    inventory = [{'file': str(p.relative_to(ROOT)), 'sha256': digest(p), 'bytes': p.stat().st_size}
                 for p in sorted(set(files))]
    (OUT / 'manifest.json').write_text(json.dumps({
        'at': result['at'], 'baseline': protocol['baseline'], 'files': inventory,
        'evidence_bytes': sum(x['bytes'] for x in inventory), 'no_truth_certification': True,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'ok': result['ok'], 'failed': [c['name'] for c in checks if not c['ok']],
                      'checks': len(checks), 'files': len(inventory)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
