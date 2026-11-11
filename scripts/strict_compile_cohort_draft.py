"""Compile supported draft syntax only; do not freeze or run evaluation."""
import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from shorttrip.strict_constraint_compiler import compile_constraint
from shorttrip.collection_task_schema import validate_cohort


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('draft')
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    source, out = Path(args.draft), Path(args.output)
    if out.exists():
        raise FileExistsError('preserve previous draft artifact')
    raw = source.read_bytes()
    draft = json.loads(raw)
    tasks = draft['tasks']
    outcomes = collections.Counter()
    for task in tasks:
        new_constraints = []
        for item in task['additional_constraints']:
            compiled = compile_constraint(item)
            outcomes[compiled['status'] + ':' + compiled['reason']] += 1
            new_constraints.append(compiled['constraint'] if compiled['status'] == 'supported' else item)
        task['additional_constraints'] = new_constraints
    validate_cohort(tasks)
    draft.update({'artifact_status':'SYNTAX_COMPILED_DRAFT_NOT_FORMALLY_FROZEN',
                  'input_sha256':hashlib.sha256(raw).hexdigest(),
                  'compiler_sha256':hashlib.sha256((ROOT/'src/shorttrip/strict_constraint_compiler.py').read_bytes()).hexdigest(),
                  'compilation_summary':dict(outcomes), 'formal_freeze':False,
                  'executable':False, 'evaluation_ready':False,
                  'natural_language_equivalence_verified':False, 'feasibility_verified':False})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(draft,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'tasks':len(tasks),'compilation_summary':dict(outcomes),
                      'formal_freeze':False}))


if __name__ == '__main__':
    main()
