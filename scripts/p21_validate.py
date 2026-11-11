"""Validate P21 artifact integrity, evidence contracts and protected prior outputs."""
from __future__ import annotations

import collections
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from p21_report import ROOT, OUT, load, save, digest, activities


def main():
    checks = []

    def check(name, ok, detail=None):
        checks.append({'name': name, 'ok': bool(ok), 'detail': detail})

    protocol = load(OUT / 'public/protocol.json')
    check('baseline_hash', digest(ROOT / protocol['baseline']['catalog']) == protocol['baseline']['sha256'])
    freeze = load(OUT / 'private/freeze.json')
    bad_freeze = [k for k, v in freeze['files'].items() if digest(ROOT / k) != v]
    check('frozen_protocol_and_code_unchanged', not bad_freeze, bad_freeze)
    old = load(OUT / 'private/continuation_checkpoint.json')
    bad_old = [k for k, v in old['protected_files'].items() if digest(ROOT.parent / k) != v]
    check('static_p20_and_p20_ppt_unchanged', not bad_old,
          {'protected_files': len(old['protected_files']), 'mismatches': bad_old})
    expected = {(c, s) for c in ('D01', 'D02', 'D03', 'D04') for s in ('static_first', 'dynamic_first')}
    expected.add(('D03', 'revised'))
    paths = sorted((OUT / 'plans').glob('*/*.json'))
    check('nine_expected_outputs', {(p.parent.name, p.stem) for p in paths} == expected)
    check('all_json_readable', all(isinstance(load(p), (dict, list)) for p in OUT.rglob('*.json')))
    ev = load(OUT / 'evaluation.json')
    check('evaluation_has_nine_no_runtime_errors', len(ev['evaluations']) == 9 and
          all('evaluation_error' not in e for e in ev['evaluations']))
    check('evaluated_answer_hashes', all(hashlib.sha256(json.dumps(load(OUT / 'plans' / e['case_id'] / (e['stage'] + '.json')), ensure_ascii=False, sort_keys=True).encode()).hexdigest() == e['answer_sha256'] for e in ev['evaluations']))
    total = collections.Counter(c['status'] for e in ev['evaluations'] for c in e['adapted_evidence_aware_checks'])
    check('score_totals_reconcile', dict(total) == ev['metrics']['check_status_counts'] and sum(total.values()) == ev['metrics']['total_checks'], dict(total))
    required = {'hotel_room_count', 'accommodation_rooms_declared', 'zero_cost_has_source_or_hard_evidence'}
    required_dynamic = {'claims_reviewed_complete', 'claims_used_cited', 'dynamic_evidence_consumed'}
    failures = []
    for e in ev['evaluations']:
        req = required | (required_dynamic if e['stage'] != 'static_first' else set())
        if e['case_id'] == 'D02':
            req |= {'twin_room_configuration_declared'}
        selected = {c['name']: c['status'] for c in e['adapted_evidence_aware_checks']}
        failures.extend(f"{e['case_id']}/{e['stage']}/{name}" for name in req if selected.get(name) != 'pass')
    check('fixed_interface_contracts_pass', not failures, failures)
    overlay = OUT / 'overlay/v001/claims.json'
    original = ROOT / protocol['evidence']['source']
    check('overlay_identical_to_p20_frozen_claims', digest(overlay) == digest(original))
    claims = load(overlay)['claims']
    check('21_unverified_claims_no_hard_or_estimate', len(claims) == 21 and all(
        c['ingest_verdict']['status'] == 'unverified' and not c['ingest_verdict']['usable_as_hard_fact'] and not c['ingest_verdict']['usable_as_labelled_estimate'] for c in claims))
    events = [load(p) for p in (OUT / 'events').glob('*/*.json')]
    check('no_live_gateway_requests', not any(e['request']['action'] == 'request_live' for e in events))
    check('no_new_live_capture_directory', not (OUT / 'live').exists())
    aliases = {a['alias_id']: a['canonical_id'] for a in load(OUT / 'private/duplicate_aliases.json')['reviewed_pairs']}
    check('no_reviewed_alias_selected', all(a.get('entity_id') not in aliases for p in paths for a in activities(load(p))))
    # Independently confirm phase-local evidence reads for claims actually selected.
    unread = []
    for p in paths:
        if p.stem == 'static_first':
            continue
        selected = {a.get('entity_id') for a in activities(load(p))}
        needed = {aliases.get(c['entity_id'], c['entity_id']) for c in claims if aliases.get(c['entity_id'], c['entity_id']) in selected}
        read = {aliases.get(e['request'].get('args', {}).get('entity_id'), e['request'].get('args', {}).get('entity_id')) for e in events if e['case_id'] == p.parent.name and e['stage'] == p.stem and e['request']['action'] == 'evidence'}
        unread.extend((p.parent.name, p.stem, rid) for rid in needed - read)
    check('selected_claim_entities_read_in_their_phase', not unread, unread)
    summary = load(OUT / 'summary.json')
    check('summary_matches_evaluation', summary['metrics'] == ev['metrics'])
    check('protocol_deviations_disclosed', not any(summary['protocol_deviations']['predefined_dynamic_instruction_delivered'].values()) and len(summary['protocol_deviations']['revision_target_locks_not_in_prior_p21_plan']) == 3)
    report = (OUT / 'REPORT.md').read_text(encoding='utf-8')
    check('report_covers_deviations_and_scope', all(s in report for s in ('阶段启动分支有误', '修订输入沿用了 P20', '不能称完全预注册', '新增 live 检索')))
    deck = ROOT.parent / 'output/ppt/P21_DeepSeekFlash固定证据回归_20261023.pptx'
    receipt = ROOT.parent / '.ppt-p21-20261023/validation.json'
    finalizer = load(receipt) if receipt.exists() else {}
    check('ppt_exists_and_finalized', deck.exists() and finalizer.get('firstPartyImport', {}).get('passed') is True
          and finalizer.get('packageIntegrity', {}).get('status') == 'pass'
          and finalizer.get('presentationLayout', {}).get('findingCount') == 0
          and finalizer.get('finalSha256') == digest(deck))
    if deck.exists():
        with zipfile.ZipFile(deck) as z:
            slides = [n for n in z.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml')]
            check('ppt_eight_slides', len(slides) == 8, len(slides))
    qa = ROOT.parent / '.ppt-p21-20261023/visual_qa.json'
    check('eight_slide_visual_review', qa.exists() and load(qa).get('all_eight_reviewed') is True)
    result = {'at': datetime.now(timezone.utc).isoformat(), 'ok': all(c['ok'] for c in checks),
              'scope': 'Artifact integrity and finite interface contracts, not real-world feasibility or a clean preregistered protocol.',
              'no_truth_certification': True, 'checks': checks}
    save(OUT / 'validation.json', result)
    files = [p for p in OUT.rglob('*') if p.is_file() and p.name != 'manifest.json' and not p.name.endswith(('-wal', '-shm'))]
    files += [ROOT / 'scripts' / name for name in ('p21_agent.py', 'p21_evaluate.py', 'p21_native_projection.py', 'p21_report.py', 'p21_validate.py')]
    files += [p for p in (deck, receipt, qa, ROOT.parent / '.ppt-p21-20261023/build.mjs', ROOT.parent / '.ppt-p21-20261023/finalize.mjs') if p.exists()]
    save(OUT / 'manifest.json', {'at': result['at'], 'path_base': str(ROOT.parent),
         'baseline_sha256': protocol['baseline']['sha256'], 'no_truth_certification': True,
         'files': [{'file': str(p.relative_to(ROOT.parent)).replace('\\', '/'), 'sha256': digest(p), 'bytes': p.stat().st_size} for p in sorted(set(files))]})
    manifest = load(OUT / 'manifest.json')
    assert all(digest(ROOT.parent / row['file']) == row['sha256'] for row in manifest['files'])
    print(json.dumps({'ok': result['ok'], 'checks': len(checks), 'failed': [c['name'] for c in checks if not c['ok']], 'manifest_files': len(manifest['files'])}, ensure_ascii=False))
    raise SystemExit(0 if result['ok'] else 1)


if __name__ == '__main__':
    main()
