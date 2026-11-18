"""Append one public HTTPS detail-page retrieval to a budgeted evidence journal."""
import argparse,json
from pathlib import Path
from entity_evidence import capture

def main():
    p=argparse.ArgumentParser();p.add_argument('--request-file',type=Path,required=True)
    p.add_argument('--journal',type=Path,required=True);p.add_argument('--budget',type=int,default=12)
    a=p.parse_args()
    if a.budget<1:raise ValueError('budget must be positive')
    request=json.loads(a.request_file.read_text(encoding='utf-8-sig'))
    a.journal.parent.mkdir(parents=True,exist_ok=True)
    print(json.dumps(capture(a.journal,request,budget=a.budget),ensure_ascii=False))

if __name__=='__main__':main()
