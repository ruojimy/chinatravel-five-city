"""Score a saved Easy/Medium/Human submission against a frozen public profile."""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys

from g3_sandbox12_repaired import configure


REPO = Path(__file__).resolve().parents[1]
PROFILES = REPO/'data/sandbox_profiles'
RUN = REPO/'results/v19-20261118/luna_v19_standard_36'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uid', required=True)
    parser.add_argument('--phase', choices=('first','revision'), default='revision')
    parser.add_argument('--profile', choices=('v17','v19_semantics','v19_maps'), default='v19_maps')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = read(RUN/'public/manifest.json')
    if args.uid not in manifest['cases']:
        parser.error('Unknown case in Easy/Medium/Human archive')
    case = RUN/'runs'/args.uid
    phase = case/args.phase
    submitted = read(phase/'submission.json')
    if submitted['status']=='keep_first':
        phase = case/'first'
        submitted = read(phase/'submission.json')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if submitted['status']=='blocked_by_data':
        record = {'uid':args.uid,'overall':'blocked_by_data','reasons':submitted['reply']['reasons']}
        with args.output.open('x',encoding='utf-8') as stream:
            json.dump(record,stream,ensure_ascii=False,indent=2)
            stream.write('\n')
        print(json.dumps(record,ensure_ascii=False))
        return
    profile = PROFILES/f'xiamen12_historical_{args.profile}'
    configure(profile=profile)
    os.environ.pop('CT_LOCAL_ROUTE_TRIAL_START_DATE',None)
    local = profile/'runtime/local_access.json'
    if local.is_file():
        os.environ['CT_LOCAL_ROUTE_TRIAL_START_DATE'] = read(local)['trial_date']
    engine = profile/'engine'
    query = RUN/'private'/f'{args.uid}.json'
    audit = RUN/'private'/f'{args.uid}.audit.json'
    entry = profile/'runtime/evaluator/score_tristate.py'
    sys.argv = [str(entry),'--target-root',str(engine),'--query',str(query),'--audit',str(audit),
                '--plan',str(phase/'plan.json'),'--output',str(args.output.resolve())]
    runpy.run_path(str(entry),run_name='__main__')


if __name__=='__main__':
    main()
