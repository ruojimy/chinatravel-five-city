"""Build an offline static gap queue from strict engineering diagnostics."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from shorttrip.strict_gap_queue import build_static_gap_queue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('diagnostics')
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    source, output = Path(args.diagnostics), Path(args.output)
    if output.exists():
        raise FileExistsError('preserve previous queue artifact')
    raw = source.read_bytes()
    data = json.loads(raw)
    if isinstance(data.get('reports'), list):
        reports = data['reports']
    elif isinstance(data.get('cases'), list):
        reports = [case['diagnostic'] for case in data['cases']]
    else:
        raise ValueError('expected reports or cases')
    result = build_static_gap_queue(reports)
    result.update({'source_sha256': hashlib.sha256(raw).hexdigest(),
                   'source': str(source.resolve()), 'diagnostics_count': len(reports),
                   'engineering_only': data.get('label') == 'engineering_smoke'})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'diagnostics': len(reports), 'static_jobs': len(result['static_jobs']),
                      'unresolved': len(result['unresolved'])}))


if __name__ == '__main__':
    main()
