"""Run isolated soft-mode cases with original sandbox, translation, DFS and evaluator."""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'reproduction'))


def save(path, value):
    from chinatravel.data.load_datasets import NpEncoder
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, cls=NpEncoder), encoding='utf-8')
    temporary.replace(path)


def run_case(split, target=20, wall_limit=None, config_path=None):
    from run import configure
    from entrypoint import configured_factory
    from chinatravel.agent.llms import create_llm
    from chinatravel.data.load_datasets import load_query
    from chinatravel.environment.world_env import WorldEnv
    from chinatravel.soft_constraints.agent import SoftLLMDrivenAgent
    from chinatravel.soft_constraints.scoring import SoftConfig
    from types import SimpleNamespace

    model = configure()
    method = 'LLMNeSySoft_' + model.replace('/', '_')
    manifest = json.loads((ROOT / 'reproduction/manifest.json').read_text(encoding='utf-8'))
    sample = next(s for s in manifest['samples'] if s['split'] == split)
    _, records = load_query(SimpleNamespace(splits=sample['local_split'], lang='zh', oracle_translation=False))
    query = records[sample['uid']]
    assert not {'hard_logic_py', 'hard_logic_nl', 'hard_logic'} & query.keys()
    config = SoftConfig(**json.loads(Path(config_path).read_text(encoding='utf-8'))) if config_path else SoftConfig()
    save(OUT / f'{split}.configuration.json', asdict(config))
    started = time.monotonic()
    status = {'split': split, 'uid': sample['uid'], 'model': model, 'method': method,
              'candidate_target': target, 'state': 'running', 'oracle_translation': False,
              'request_configuration': {'max_tokens': 4096, 'thinking': {'type': 'disabled'}},
              'wall_limit_seconds': wall_limit}
    save(OUT / f'{split}.status.json', status)
    llm = configured_factory(create_llm)(model)
    llm._client_kwargs.update(timeout=90, max_retries=1)

    def checkpoint(pool):
        save(OUT / f'{split}.candidates.json', pool.items)
        print(f'{split}: {len(pool.items)}/{target} feasible unique candidates', flush=True)

    cache = ROOT / 'cache' / method
    original_translation = ROOT / 'cache' / 'translation_deepseek-flash_reflect' / f'{sample["uid"]}.json'
    if not original_translation.exists():
        raise RuntimeError('The controlled comparison requires the previous original model-generated translation cache')
    previous = json.loads(original_translation.read_text(encoding='utf-8'))
    if previous.get('uid') != query['uid'] or previous.get('nature_language') != query['nature_language']:
        raise RuntimeError('Translation cache does not match this query')
    translation_destination = cache / 'translation_deepseek-flash_reflect' / original_translation.name
    translation_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original_translation, translation_destination)
    status['translation_cache'] = {'source': original_translation.relative_to(ROOT).as_posix(),
                                   'sha256': hashlib.sha256(original_translation.read_bytes()).hexdigest(),
                                   'origin': 'prior_original_model_generated_DSL_not_Oracle'}
    save(OUT / f'{split}.status.json', status)
    agent = SoftLLMDrivenAgent(env=WorldEnv(lang='zh'), backbone_llm=llm,
                               cache_dir=str(cache), log_dir=str(cache), debug=True,
                               lang='zh', candidate_limit=target, soft_config=config,
                               wall_limit_seconds=wall_limit, on_candidate=checkpoint)
    try:
        success, selected = agent.run(query, load_cache=True)
    except Exception as exc:
        status.update(state='failed', error_type=type(exc).__name__,
                      candidate_count=len(agent.pool.items), elapsed_seconds=time.monotonic()-started)
        save(OUT / f'{split}.status.json', status)
        raise
    result_path = ROOT / 'results' / method / f'{sample["uid"]}.json'
    save(result_path, selected)
    save(OUT / f'{split}.selection.json', agent.selection)
    save(OUT / f'{split}.candidates.json', agent.pool.items)
    status.update(state='generated' if success else 'no_feasible_candidate',
                  candidate_count=len(agent.pool.items), complete=agent.pool.full,
                  result=result_path.relative_to(ROOT).as_posix(),
                  elapsed_generation_seconds=time.monotonic()-started)
    # Original CLI evaluator loads the official annotations only after selection.
    command = [sys.executable, '-X', 'utf8', 'eval_exp.py', '--splits', sample['local_split'],
               '--method', method, '--lang', 'zh']
    with (OUT / f'{split}.eval.log').open('w', encoding='utf-8') as log:
        evaluated = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    status.update(eval_exit_code=evaluated.returncode, elapsed_seconds=time.monotonic()-started)
    save(OUT / f'{split}.status.json', status)
    print(f'{split}: done, count={len(agent.pool.items)}, minimum={agent.selection["minimum_penalty"]}', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=['easy','medium','human'])
    parser.add_argument('--target', type=int, default=20)
    parser.add_argument('--wall-limit-seconds', type=float, default=None)
    parser.add_argument('--config', help='Optional SoftConfig JSON, including thresholds and weights')
    args = parser.parse_args()
    if args.case:
        run_case(args.case, args.target, args.wall_limit_seconds, args.config)
        return
    os.environ.update(PYTHONIOENCODING='utf-8', PYTHONUTF8='1', PYTHONUNBUFFERED='1')
    children = []
    for split in ('easy','medium','human'):
        log = (OUT / f'{split}.run.log').open('w', encoding='utf-8')
        command = [sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '--case', split, '--target', str(args.target)]
        if args.wall_limit_seconds is not None:
            command += ['--wall-limit-seconds', str(args.wall_limit_seconds)]
        if args.config:
            command += ['--config', str(Path(args.config).resolve())]
        child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        children.append((split, child, log))
        print(f'Started original DFS + soft collection: {split}', flush=True)
    failed = False
    for split, child, log in children:
        code = child.wait()
        log.close()
        print(f'{split}: exit={code}', flush=True)
        failed = failed or code != 0
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
