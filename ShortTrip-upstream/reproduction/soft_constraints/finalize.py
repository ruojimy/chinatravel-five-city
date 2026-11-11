"""Recompute all saved candidate scores, select exact minimum, and independently audit."""
from contextlib import redirect_stdout
from dataclasses import asdict
from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from chinatravel.soft_constraints.pool import fingerprint, snapshot
from chinatravel.soft_constraints.scoring import SoftConfig, score_plan
from chinatravel.environment.tools.transportation.apis import Transportation
from chinatravel.symbol_verification.commonsense_constraint import func_commonsense_constraints
from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py
from chinatravel.data.load_datasets import NpEncoder
import jsonschema


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, cls=NpEncoder), encoding='utf-8')


def structure(plan):
    return json.dumps([[(a.get('type'), a.get('position'), a.get('TrainID'), a.get('FlightID'))
                        for a in d['activities']] for d in plan['itinerary']], ensure_ascii=False)


def main():
    manifest = read(ROOT / 'reproduction/manifest.json')
    transport = Transportation(lang='zh')

    @lru_cache(maxsize=10000)
    def route(city, start, end, start_time, mode):
        return transport.goto(city, start, end, start_time, mode)

    schema = read(ROOT / 'chinatravel/evaluation/output_schema.json')
    bundle = {'agent': 'LLMNeSySoft', 'candidate_target': 20, 'cases': [],
              'module_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                for name in ['chinatravel/soft_constraints/scoring.py',
                                             'chinatravel/soft_constraints/pool.py',
                                             'chinatravel/soft_constraints/agent.py']}}
    for sample in manifest['samples']:
        split, uid = sample['split'], sample['uid']
        status = read(OUT / f'{split}.status.json')
        selection = read(OUT / f'{split}.selection.json')
        if status['state'] != 'generated':
            raise RuntimeError(f'{split}: generation did not finish')
        config = SoftConfig(**selection['configuration'])
        candidates = read(OUT / f'{split}.candidates.json')
        if len(candidates) != 20 or len({fingerprint(c['plan']) for c in candidates}) != 20:
            raise RuntimeError(f'{split}: expected exactly 20 unique candidates')
        query = read(ROOT / sample['query_path'])
        translated_path = ROOT / 'cache' / status['method'] / 'translation_deepseek-flash_reflect' / f'{uid}.json'
        translated = read(translated_path)
        for candidate in candidates:
            assert candidate['fingerprint'] == fingerprint(candidate['plan'])
            candidate['score'] = score_plan(candidate['plan'], config, route)
            jsonschema.validate(candidate['plan'], schema)
            with redirect_stdout(io.StringIO()):
                commonsense = bool(func_commonsense_constraints(query, candidate['plan'], lang='zh'))
                original_hard = [bool(v) for v in evaluate_constraints_py(translated['hard_logic_py'], candidate['plan'])]
            # Official hard labels are inspected only after scoring; never filter or alter rank.
            official = [bool(v) for v in evaluate_constraints_py(query['hard_logic_py'], candidate['plan'])]
            candidate['audit'] = {'schema': True, 'original_commonsense': commonsense,
                                  'translated_hard_constraints': original_hard,
                                  'official_hard_constraints': official}
            assert commonsense and all(original_hard), f'{split}: a collected candidate was not originally feasible'
        winner = min(candidates, key=lambda c: (c['score']['total_penalty'], c['ordinal']))
        selection.update(selected_ordinal=winner['ordinal'], selected_fingerprint=winner['fingerprint'],
                         minimum_penalty=winner['score']['total_penalty'], rescored=True,
                         candidate_count=len(candidates), complete=True,
                         structural_variants=len({structure(c['plan']) for c in candidates}))
        result_path = ROOT / status['result']
        result = read(result_path)
        result.update(winner['plan'])
        assert snapshot(result) == winner['plan']
        baseline = read(ROOT / 'results/LLMNeSy_deepseek-flash' / f'{uid}.json')
        baseline_score = score_plan(baseline, config, route)
        save(OUT / f'{split}.candidates.json', candidates)
        save(OUT / f'{split}.selection.json', selection)
        save(result_path, result)
        with (OUT / f'{split}.eval.log').open('w', encoding='utf-8') as log:
            evaluated = subprocess.run([sys.executable, '-X', 'utf8', 'eval_exp.py', '--splits', sample['local_split'],
                                       '--method', status['method'], '--lang', 'zh'], cwd=ROOT,
                                      stdout=log, stderr=subprocess.STDOUT)
        if evaluated.returncode:
            raise RuntimeError(f'{split}: original evaluation failed')
        item = {'split': split, 'uid': uid, 'query': query, 'status': status,
                'selection': selection, 'selected_plan': result,
                'selected_score': winner['score'], 'baseline_score': baseline_score,
                'candidates': candidates, 'configuration': asdict(config)}
        bundle['cases'].append(item)
        print(f'{split}: 20 unique feasible candidates, chosen #{winner["ordinal"]}, '
              f'minimum={winner["score"]["total_penalty"]}, baseline={baseline_score["total_penalty"]}', flush=True)
    save(OUT / 'all_results.json', bundle)


if __name__ == '__main__':
    main()
