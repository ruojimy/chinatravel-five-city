"""Invoke original ChinaTravel entrypoints with local credentials and fixed data."""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reproduction'


def configure():
    allowed = {'CHINATRAVEL_OPENAI_API_KEY', 'CHINATRAVEL_OPENAI_BASE_URL',
               'CHINATRAVEL_OPENAI_MODEL', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY',
               'OPENAI_BASE_URL', 'OPENAI_MODEL'}
    for path in (ROOT.parent / '.env.local', ROOT / '.env.local', OUT / '.env.local'):
        if path.exists():
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                key, sep, value = line.removeprefix('export ').partition('=')
                if sep and key.strip() in allowed:
                    os.environ[key.strip()] = value.strip().strip('\"\'')
    key = (os.getenv('CHINATRAVEL_OPENAI_API_KEY') or os.getenv('DEEPSEEK_API_KEY')
           or os.getenv('OPENAI_API_KEY'))
    if not key:
        raise SystemExit('Missing API key. Save CHINATRAVEL_OPENAI_API_KEY in .env.local.')
    os.environ['CHINATRAVEL_OPENAI_API_KEY'] = key
    os.environ.setdefault('CHINATRAVEL_OPENAI_BASE_URL', os.getenv('OPENAI_BASE_URL') or 'https://api.deepseek.com')
    os.environ.setdefault('CHINATRAVEL_OPENAI_MODEL', 'deepseek-flash')
    os.environ['CHINATRAVEL_OPENAI_WIRE_API'] = 'chat'
    os.environ['CHINATRAVEL_OPENAI_RAISE_ERRORS'] = '1'
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['PYTHONUTF8'] = '1'
    return os.environ['CHINATRAVEL_OPENAI_MODEL']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--split', choices=['easy', 'medium', 'human', 'all'], default='all')
    parser.add_argument('--resume', action='store_true', help='Reuse existing result files; does not rerun them.')
    args = parser.parse_args()
    model = configure()
    sys.path.insert(0, str(ROOT))
    from chinatravel.agent.load_model import build_method_name
    from chinatravel.agent.llms import create_llm
    from chinatravel.environment.world_env import WorldEnv
    env = WorldEnv(lang='zh')
    print(f'Chinese sandbox loaded: {len(env.support_cities)} cities', flush=True)
    from entrypoint import configured_factory
    llm = configured_factory(create_llm)(model)
    try:
        response = llm.chat([{'role': 'user', 'content': 'Reply exactly OK.'}], max_tokens=64)
    except Exception as exc:
        # Do not echo server error bodies or request headers containing credentials.
        raise SystemExit(f'Model preflight failed: {type(exc).__name__}, status={getattr(exc, "status_code", None)}')
    if not response.get('content'):
        raise SystemExit('Model preflight returned no text.')
    print(f'Model preflight passed: {model}', flush=True)
    if args.preflight:
        return
    method = build_method_name('LLMNeSy', model, lang='zh')
    manifest = json.loads((OUT / 'manifest.json').read_text(encoding='utf-8'))
    status_path = OUT / 'run_status.json'
    status = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}
    status.update(model=model, method=method, agent='LLMNeSy', oracle_translation=False)
    status['request_configuration'] = {'max_tokens': 4096, 'thinking': {'type': 'disabled'}}
    status.setdefault('cases', {})
    logs = OUT / 'logs'
    logs.mkdir(exist_ok=True)
    def save_status():
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    for sample in manifest['samples']:
        split, uid = sample['split'], sample['uid']
        if args.split != 'all' and split != args.split:
            continue
        result = ROOT / 'results' / method / f'{uid}.json'
        item = {'uid': uid, 'started_at': datetime.now(timezone.utc).isoformat()}
        status['cases'][split] = item
        save_status()
        command = [sys.executable, '-X', 'utf8', 'reproduction/entrypoint.py', '--splits', sample['local_split'],
                   '--agent', 'LLMNeSy', '--llm', model, '--lang', 'zh']
        if args.resume:
            command += ['--skip', '1']
        print(f'Running {split}: {uid}', flush=True)
        with (logs / f'{split}.log').open('w', encoding='utf-8') as log:
            completed = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        item['run_exit_code'] = completed.returncode
        if completed.returncode == 0 and result.exists():
            plan = json.loads(result.read_text(encoding='utf-8'))
            item['result'] = result.relative_to(ROOT).as_posix()
            item['all_constraints_pass'] = plan.get('all_constraints_pass', 0)
            evaluation = [sys.executable, '-X', 'utf8', 'eval_exp.py', '--splits', sample['local_split'],
                          '--method', method, '--lang', 'zh']
            with (logs / f'{split}_eval.log').open('w', encoding='utf-8') as log:
                evaluated = subprocess.run(evaluation, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            item['eval_exit_code'] = evaluated.returncode
        item['finished_at'] = datetime.now(timezone.utc).isoformat()
        save_status()
        print(f'Finished {split}: run={completed.returncode}, eval={item.get("eval_exit_code")}', flush=True)
    print('All requested cases processed. Run reproduction/render.py to build the report.', flush=True)


if __name__ == '__main__':
    main()
