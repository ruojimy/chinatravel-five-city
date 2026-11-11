"""Fifteen new fixed cases; no API call during --prepare."""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
import random
from pathlib import Path
import subprocess
import sys
import time

OUT = Path(__file__).resolve().parent
CONFIG = json.loads((OUT/'config.json').read_text(encoding='utf-8'))
PROJECT = Path(CONFIG['project'])
os.environ.update(PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8', PYTHONUTF8='1', PYTHONUNBUFFERED='1')
sys.dont_write_bytecode = True
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / 'reproduction'))


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    from chinatravel.data.load_datasets import NpEncoder
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, cls=NpEncoder), encoding='utf-8')
    # Windows readers can briefly deny replacement of an open status file.
    for attempt in range(20):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.1 * min(attempt + 1, 5))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare():
    if (OUT / 'manifest.json').exists():
        return read(OUT / 'manifest.json')
    from prepare import normalize
    files = ['chinatravel/agent/nesy_agent/prompts/prompts.py',
             'chinatravel/agent/nesy_agent/prompts/prompts_en.py',
             'chinatravel/agent/nesy_agent/llm_driven_rec.py',
             'chinatravel/agent/nesy_agent/nesy_agent.py',
             'chinatravel/soft_constraints/agent.py', 'chinatravel/soft_constraints/scoring.py',
             'chinatravel/soft_constraints/pool.py']
    manifest = {'created_at': datetime.now(timezone.utc).isoformat(), 'project': str(PROJECT),
                'language': 'zh', 'candidate_target': 20, 'translation_cache': 'fresh_per_case',
                'oracle_in_planning': False, 'sample_rule': 'seeded random sample of five untested UIDs per split',
                'seed': CONFIG['seed'], 'excluded_uids': read(OUT/'excluded_uids.json')['uids'],
                'source_sha256': {f: digest(PROJECT / f) for f in files}, 'cases': []}
    for filename in ('prompts.py','prompts_en.py'):
        source = PROJECT / 'chinatravel/agent/nesy_agent/prompts' / filename
        destination = OUT / 'prompt_snapshots' / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    for split in ('easy','medium','human'):
        source = PROJECT / 'reproduction/data' / f'{split}.csv'
        with source.open(encoding='utf-8-sig', newline='') as file:
            rows = list(csv.DictReader(file))
        excluded = set(read(OUT/'excluded_uids.json')['uids'])
        rows = [r for r in rows if r['uid'] not in excluded]
        assert len(rows) >= 5, f'Not enough unseen cases: {split}'
        rows = random.Random(str(CONFIG['seed'])+':'+split).sample(rows, 5)
        for number, row in enumerate(rows, 1):
            case = f'{split}_{number}'
            query = normalize(row)
            save(OUT / 'queries' / f'{case}.json', query)
            manifest['cases'].append({'case': case, 'split': split, 'uid': query['uid'],
                                      'query': f'queries/{case}.json', 'csv_sha256': digest(source)})
    save(OUT / 'manifest.json', manifest)
    return manifest


def evaluate(case, full_query, result):
    from chinatravel.evaluation.schema_constraint import evaluate_schema_constraints
    from chinatravel.evaluation.commonsense_constraint import evaluate_commonsense_constraints
    from chinatravel.evaluation.hard_constraint import evaluate_hard_constraints_v2
    uid = full_query['uid']
    index, queries, plans = [uid], {uid: full_query}, {uid: result}
    directory = OUT / 'evaluation' / case
    directory.mkdir(parents=True, exist_ok=True)
    schema = read(PROJECT / 'chinatravel/evaluation/output_schema.json')
    schema_rate, schema_table, schema_pass = evaluate_schema_constraints(index, plans, schema)
    comm_macro, comm_micro, comm_table, comm_pass = evaluate_commonsense_constraints(index, queries, plans, lang='zh')
    hard_macro, hard_micro, cond_macro, cond_micro, hard_table, hard_pass = evaluate_hard_constraints_v2(index, queries, plans, comm_pass, lang='zh')
    for name, table in [('schema',schema_table),('commonsense',comm_table),('logical_py',hard_table)]:
        table.to_csv(directory / f'{name}.csv', index=False)
    return {'schema_pass': uid in schema_pass, 'commonsense_pass': uid in comm_pass,
            'official_hard_pass': uid in hard_pass,
            'all_pass': uid in set(schema_pass) & set(comm_pass) & set(hard_pass),
            'schema_percent': schema_rate, 'commonsense_micro_percent': comm_micro,
            'hard_micro_percent': hard_micro}


def run_case(case):
    os.chdir(PROJECT)  # Existing example-plan loader uses repository-relative paths.
    from chinatravel.agent.llms import create_llm
    from chinatravel.environment.world_env import WorldEnv
    from chinatravel.soft_constraints.agent import SoftLLMDrivenAgent
    from experiment_agent import ExperimentAgent
    from rules import audit
    from chinatravel.agent.nesy_agent import llm_driven_rec
    from chinatravel.agent.nesy_agent.prompts import prompts
    from chinatravel.data.load_datasets import ORACLE_FIELDS

    manifest = read(OUT / 'manifest.json')
    for path, expected in manifest['source_sha256'].items():
        assert digest(PROJECT / path) == expected, f'Source changed during experiment: {path}'
    for filename, expected in manifest.get('experiment_sha256',{}).items():
        assert digest(OUT/filename)==expected, f'Experiment source changed: {filename}'
    entry = next(c for c in manifest['cases'] if c['case'] == case)
    full_query = read(OUT / entry['query'])
    query = {k:v for k,v in full_query.items() if k not in ORACLE_FIELDS}
    assert not ORACLE_FIELDS & query.keys()
    # Deliberately never load the cloud .env or cloud request factory.
    model = CONFIG['model']
    endpoint = CONFIG['base_url']
    assert endpoint == 'http://127.0.0.1:18080/v1'
    os.environ.update(CHINATRAVEL_OPENAI_BASE_URL=endpoint,
        CHINATRAVEL_OPENAI_API_KEY='local-no-key', CHINATRAVEL_OPENAI_MODEL=model,
        CHINATRAVEL_OPENAI_WIRE_API='chat', CHINATRAVEL_OPENAI_TOKEN_LIMIT_ARG='max_tokens',
        CHINATRAVEL_OPENAI_RAISE_ERRORS='1', NO_PROXY='127.0.0.1,localhost')
    assert llm_driven_rec.NEXT_POI_TYPE_INSTRUCTION == prompts.NEXT_POI_TYPE_INSTRUCTION
    template = prompts.NEXT_POI_TYPE_INSTRUCTION
    assert 'hotel' in template and '13:00' in template and 'POI_type_list' in template
    template_sha = hashlib.sha256(template.encode('utf-8')).hexdigest()
    status_path = OUT / 'status' / f'{case}.json'
    status = {'group':entry['group'], 'base_case':entry['base_case'], 'repetition':entry['repetition'], 'case': case, 'split': entry['split'], 'uid': entry['uid'], 'model': model,
              'base_url': endpoint, 'state': 'running', 'pid': os.getpid(), 'started_at': datetime.now(timezone.utc).isoformat(),
              'candidate_target': 20, 'candidate_count': 0, 'translation_cache': 'fresh',
              'activity_template_sha256': template_sha, 'activity_prompt_requests': 0,
              'activity_prompt_responses': 0, 'oracle_in_planning': False,
              'request_settings': {'thinking': 'disabled', 'max_tokens': 4096}}
    save(status_path, status)
    llm = create_llm(model, max_tokens=4096)
    assert llm._client_kwargs['base_url'] == endpoint
    llm._client_kwargs.update(timeout=600, max_retries=0)
    original_send = llm._send_request
    traces = OUT / 'traces'
    traces.mkdir(exist_ok=True)
    trace_path = traces / f'{case}.jsonl'
    if trace_path.exists():
        raise RuntimeError('Refusing to overwrite existing traces; use a new output directory')
    api_count = 0

    def send(messages, request_args):
        nonlocal api_count
        assert str(llm.llm.base_url).rstrip('/') == endpoint
        api_count += 1
        text = '\n'.join(str(m.get('content','')) for m in messages)
        is_activity = text.lstrip().startswith(template.lstrip().split('{}',1)[0])
        if is_activity:
            status['activity_prompt_requests'] += 1
        record = {'call': api_count, 'stage': 'activity_type' if is_activity else 'other',
                  'template_sha256': template_sha if is_activity else None,
                  'model': model, 'base_url': os.getenv('CHINATRAVEL_OPENAI_BASE_URL'),
                  'messages': messages, 'requested_at': datetime.now(timezone.utc).isoformat()}
        save(status_path, status)
        started = time.monotonic()
        try:
            answer = original_send(messages, request_args)
            record.update(assistant=answer, elapsed_seconds=time.monotonic()-started)
            if is_activity:
                status['activity_prompt_responses'] += 1
            return answer
        except Exception as exc:
            record.update(error_type=type(exc).__name__, elapsed_seconds=time.monotonic()-started)
            raise
        finally:
            with trace_path.open('a',encoding='utf-8') as file:
                file.write(json.dumps(record,ensure_ascii=False)+'\n')
            status['api_calls'] = api_count
            save(status_path,status)

    llm._send_request = send
    cache = OUT / 'cache' / case
    if cache.exists() and any(cache.rglob('*.json')):
        raise RuntimeError('Fresh-cache experiment refuses existing JSON cache')

    def checkpoint(pool):
        save(OUT / 'candidates' / f'{case}.json',pool.items)
        status.update(candidate_count=len(pool.items), minimum_penalty=pool.best()['score']['total_penalty'])
        save(status_path,status)
        print(f'{case}: {len(pool.items)}/20 candidates',flush=True)

    agent_type = SoftLLMDrivenAgent if entry['group']=='A' else ExperimentAgent
    agent_options = {} if entry['group']=='A' else {'group':entry['group']}
    agent = agent_type(**agent_options, env=WorldEnv(lang='zh'), backbone_llm=llm, cache_dir=str(cache),
                               log_dir=str(cache), debug=True, lang='zh',
                               candidate_limit=20, wall_limit_seconds=1750, on_candidate=checkpoint)
    original_record_prune = agent.record_prune
    def record_prune(rejected):
        original_record_prune(rejected)
        count = sum(agent.prune_counts.values())
        if agent.prune_counts[rejected['rule']] == 1 or count % 1000 == 0:
            status.update(prune_counts=dict(agent.prune_counts),
                          prune_examples=agent.prune_examples)
            save(status_path,status)
    agent.record_prune = record_prune
    original_translation = agent.translate_nl2sl
    def translate_checked(*args, **kwargs):
        status['phase'] = 'translation'
        save(status_path,status)
        translated = original_translation(*args, **kwargs)
        status.update(phase='search', validated_constraint_programs=len(translated['hard_logic_py']),
                      translation_repairs=translated.get('reflect_cnt',0),
                      extraction_repairs=translated.get('extraction_repair_count',0),
                      source_coverage_items=len(translated.get('source_coverage',[])),
                      program_sources=translated.get('translation_program_sources',[]))
        save(status_path,status)
        return translated
    agent.translate_nl2sl = translate_checked
    from dataclasses import asdict
    status['meal_order_profile'] = 'C: no window-minus30 meal shortcut; full-visit + real meal access feasibility; both DFS orders'
    status['soft_configuration'] = asdict(agent.soft_config)
    status['evaluation_profile'] = 'original schema/commonsense/hard evaluation'
    save(status_path,status)
    started = time.monotonic()
    try:
        success, selected = agent.run(query,load_cache=False)
        save(OUT/'results'/f'{case}.json',selected)
        save(OUT/'selection'/f'{case}.json',agent.selection)
        save(OUT/'candidates'/f'{case}.json',agent.pool.items)
        status.update(state='generated' if success else 'no_feasible_candidate',
                      candidate_count=len(agent.pool.items), complete=agent.pool.full,
                      minimum_penalty=agent.selection['minimum_penalty'],
                      selected_ordinal=agent.selection['selected_ordinal'],
                      elapsed_seconds=time.monotonic()-started)
        status['evaluation'] = evaluate(case,full_query,selected) if success else {}
        status['new_rule_audit'] = audit(selected,full_query['days']) if success else {}
        status['combined_pass'] = bool(status['evaluation'].get('all_pass') and status['new_rule_audit'].get('all_pass'))
        status['rule_rejections'] = getattr(agent,'rule_rejections',0)
        if agent.selection.get('stop_reason')=='wall_limit_reached':
            status['state']='timed_out_with_candidates' if success else 'timed_out_no_candidates'
    except Exception as exc:
        status.update(state='failed',error_type=type(exc).__name__,error_message=str(exc),candidate_count=len(agent.pool.items),
                      elapsed_seconds=time.monotonic()-started)
        save(status_path,status)
        raise
    finally:
        status.update(prune_counts=getattr(agent,'prune_counts',{}),
                      prune_examples=getattr(agent,'prune_examples',{}))
        status['finished_at'] = datetime.now(timezone.utc).isoformat()
        save(status_path,status)
    print(f'{case}: {status["state"]}, {status["candidate_count"]}/20, eval={status["evaluation"].get("all_pass", False)}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--case',required=True)
    run_case(parser.parse_args().case)
