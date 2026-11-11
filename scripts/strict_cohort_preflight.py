"""Report structural readiness for a draft without freezing or evaluating it."""
import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from shorttrip.strict_cohort_preflight import preflight


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('draft')
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    source, out = Path(args.draft), Path(args.output)
    if out.exists():
        raise FileExistsError('preserve preflight artifact')
    raw = source.read_bytes()
    draft = json.loads(raw)
    tasks = draft['tasks']
    dev = [task for task in tasks if task.get('split') == 'development']
    holdout = [task for task in tasks if task.get('split') == 'holdout']
    check = preflight(dev, holdout)
    # Schema/preflight findings are summarized by reason; no per-holdout task
    # diagnostics are fed into a collection strategy.
    summary = dict(collections.Counter(x['reason'] for x in check['blockers']))
    result = {'source_sha256': hashlib.sha256(raw).hexdigest(),
              'source': str(source.resolve()), 'development_count': len(dev),
              'holdout_count': len(holdout), 'blocker_counts': summary,
              'freeze_approved': False, 'formal_evaluation_performed': False,
              'holdout_per_task_results_generated': False}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
