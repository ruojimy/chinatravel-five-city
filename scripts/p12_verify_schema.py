"""Stream-audit expansion JSONL; no network and no normalization/defaults."""
from pathlib import Path
import argparse,gzip,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.expansion_contract import discovery_summary

def records(path):
    path=Path(path)
    opener=gzip.open if path.suffix=='.gz' else open
    with opener(path,'rt',encoding='utf-8-sig') as stream:
        for line in stream:
            if line.strip():yield json.loads(line)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('input',help='expansion envelope JSONL')
    p.add_argument('--now',help='timezone-aware frozen evaluation time')
    p.add_argument('--output')
    args=p.parse_args()
    result=discovery_summary(records(args.input),now=args.now)
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:Path(args.output).write_text(text,encoding='utf-8')
    print(text)
    return 0 if result['complete'] else 1

if __name__=='__main__':raise SystemExit(main())
