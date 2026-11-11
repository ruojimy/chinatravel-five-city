"""Explore development drafts only. This is not a frozen evaluation."""
import argparse
import collections
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from shorttrip.strict_cohort_adapter import diagnose_development_task
from shorttrip.strict_gap_queue import build_static_gap_queue
from shorttrip.strict_v4_reader import V4Reader

CATALOG = ROOT / 'data/five_city_reference_v4_20261026/catalog.sqlite3'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('draft')
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    source, out = Path(args.draft), Path(args.output)
    if out.exists():
        raise FileExistsError('preserve previous smoke artifact')
    raw = source.read_bytes()
    draft = json.loads(raw)
    tasks = [task for task in draft['tasks'] if task.get('split') == 'development']
    now = datetime.now(timezone.utc).isoformat()
    reader = V4Reader(CATALOG)
    try:
        reports = [diagnose_development_task(task, reader=reader, now=now) for task in tasks]
    finally:
        reader.close()
    queue = build_static_gap_queue(reports)
    result = {'label':'engineering_only_not_formal_evaluation', 'evaluation_at':now,
              'draft_sha256':hashlib.sha256(raw).hexdigest(),
              'catalog_sha256':hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
              'development_count':len(reports),
              'outcomes':dict(collections.Counter(x['outcome'] for x in reports)),
              'reports':reports, 'gap_queue':queue,
              'holdout_per_task_results_generated':False,
              'frozen':False, 'formal_score':None, 'network_requests':0}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'development_count':len(reports), 'outcomes':result['outcomes'],
                      'static_jobs':len(queue['static_jobs']),
                      'identity_workflow':len(queue['identity_resolution_workflow']),
                      'formal_score':None}))


if __name__ == '__main__':
    main()
