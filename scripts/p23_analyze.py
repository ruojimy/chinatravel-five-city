"""Reconcile P23 saved outcomes without generating or selecting new proposals."""
import csv, hashlib, json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/p23_scaled_llm'
SPLITS = ('easy', 'medium', 'human')
ARMS = ('control', 'participant', 'retrieval_only', 'optimized')

def read(p):
    return json.loads(p.read_text(encoding='utf-8'))

def save(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def csv_save(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)

def digest(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def main():
    selection = read(OUT / 'selection.json')['uids']
    results = {}; rows = []; summaries = []
    for arm in ARMS:
        for split in SPLITS + (('competition_test',) if arm == 'control' else ()):
            records = [read(p) for p in sorted((OUT / 'evaluations' / arm / split).glob('*.json'))]
            assert records, (arm, split)
            results[arm, split] = {r['uid']: r for r in records}
            if arm != 'control':
                assert set(results[arm, split]) == set(selection[split])
            counts = dict(arm=arm, split=split, queries=len(records),
                          delivered=sum(r['proposal_delivered'] for r in records),
                          schema_pass=sum(r['official']['schema_ok'] for r in records),
                          commonsense_pass=sum(r['official']['commonsense_ok'] for r in records),
                          hard_pass=sum(r['proposal_delivered'] and r['official']['hard_ok'] for r in records),
                          all_pass=sum(r['official']['all_ok'] for r in records),
                          construction_failures=sum(bool(r['error']) for r in records))
            cached = read(OUT / 'aggregates' / f'{arm}_{split}.json')
            for key in counts:
                if key != 'construction_failures': assert counts[key] == cached[key], (arm, split, key)
            assert counts['construction_failures'] == cached['runtime_errors']
            summaries.append(counts)
            for r in records:
                p = OUT / 'plans' / arm / split / (r['uid'] + '.json')
                assert p.exists() == r['proposal_delivered'], p
                rows.append(dict(arm=arm, split=split, uid=r['uid'], delivered=r['proposal_delivered'],
                    schema=r['official']['schema_ok'], commonsense=r['official']['commonsense_ok'],
                    hard_pass=r['official']['hard_pass_count'], hard_total=r['official']['hard_total'],
                    all_pass=r['official']['all_ok'], construction_error=r['error'] or '',
                    plan_file=str(p.relative_to(OUT)) if p.exists() else '',
                    plan_sha256=digest(p) if p.exists() else ''))
    paired=[]; comparisons={}
    for split in SPLITS:
        for uid in selection[split]:
            paired.append(dict(split=split, uid=uid, **{
                arm: results[arm, split][uid]['official']['all_ok'] for arm in ARMS}))
    for before, after in [('control', 'participant'), ('participant', 'retrieval_only'), ('retrieval_only', 'optimized')]:
        groups = {}
        for split in SPLITS + ('total',):
            subset = [r for r in paired if split == 'total' or r['split'] == split]
            groups[split] = dict(queries=len(subset), before_pass=sum(r[before] for r in subset),
                after_pass=sum(r[after] for r in subset),
                gained=[r['uid'] for r in subset if not r[before] and r[after]],
                lost=[r['uid'] for r in subset if r[before] and not r[after]])
        comparisons[before + '_to_' + after] = groups
    failed = []
    for split in SPLITS:
        queries = {q['uid']: q for q in read(OUT / 'private' / split / 'queries.json')}
        for uid, r in results['retrieval_only', split].items():
            if r['official']['all_ok']: continue
            codes = queries[uid]['hard_logic_py']
            failed.append(dict(uid=uid, split=split, nature_language=queries[uid]['nature_language'],
                construction_error=r['error'], commonsense_violations=r['official']['commonsense_violations'],
                failed_hard_indices=[i for i, ok in enumerate(r['official']['hard_results']) if not ok],
                failed_hard_code=[code for code, ok in zip(codes, r['official']['hard_results']) if not ok]))
    revisions = {}
    for split in SPLITS:
        first={r['uid']:r for r in read(OUT/'intents'/(split+'.json'))}
        second={r['uid']:r for r in read(OUT/'intents_v2'/(split+'.json'))}
        revisions[split]=dict(changed=sum(first[u] != second[u] for u in first), unchanged=sum(first[u] == second[u] for u in first))
    summary = dict(scope='Frozen official sandbox; LLM semantic intents + deterministic scheduling',
        control_queries=704, participant_unique_queries=150, participant_intent_versions=300,
        evaluation_attempts=len(rows), delivered_plans=sum(r['delivered'] for r in rows),
        unique_control_uids=len({r['uid'] for r in rows if r['arm']=='control'}),
        aggregates=summaries, paired_comparisons=comparisons, intent_revisions=revisions,
        supplemental_candidates=sum(d['added'] for r in read(OUT/'retrieval_audit.json')['cases'] for d in r['retrieval']),
        live_api_calls=0, recommended_arm='retrieval_only',
        policy_selection='One globally selected fixed arm; never pick an arm per UID using hidden scores',
        generalization='Engineering comparison on this fixed sample; no held-out generalization or statistical claim')
    csv_save(OUT/'all_cases.csv', rows); csv_save(OUT/'paired_150.csv', paired)
    save(OUT/'summary.json', summary); save(OUT/'remaining_failures.json', failed)
    save(OUT/'recommended_policy.json', dict(arm='retrieval_only', planner='shorttrip.intent_planner.IntentPlanner',
        intents='intents_v2', public_candidates='public + public_v2', cost_repair_enabled=False,
        selection_basis='118/150 vs 109/150 first pass and 115/150 with experimental cost repair',
        per_case_oracle_selection=False, status='Selected after this sample comparison, not a held-out validation'))
    print(json.dumps({k:v for k,v in summary.items() if k not in ('aggregates','paired_comparisons')},ensure_ascii=False))
    print(json.dumps(comparisons, ensure_ascii=False))

if __name__ == '__main__': main()
