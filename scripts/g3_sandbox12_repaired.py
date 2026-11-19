"""Select the 12-city historical benchmark with repaired catalog and rail data."""
import argparse
from datetime import date
import json
import os
import sys
from pathlib import Path

from g3_sandbox12_xiamen import REPO, configure as configure_profile, room_options

PROFILE = REPO / 'data/sandbox_profiles/xiamen12_historical_v20_completion'
CHECKOUT_PROFILE = PROFILE.with_name('xiamen12_historical_v16')
TIMELINE_PROFILE = PROFILE.with_name('xiamen12_historical_v17')
TOOLS = ('catalog_list', 'catalog_search', 'catalog_entity', 'catalog_preflight',
         'reference_search', 'intercity_search', 'goto', 'room_options', 'ferry_reference')


def configure(*, planner=False, profile=PROFILE):
    if 'sandbox_adapter' in sys.modules or 'chinatravel' in sys.modules:
        raise RuntimeError('Configure the repaired sandbox before importing its tools')
    for key in ('CT_TRAVEL_DATE', 'CT_TRAVEL_START_DATE', 'CT_TRAVEL_END_DATE',
                'CT_OFFICIAL_FARE_SIDECAR', 'CT_OFFICIAL_DISPLAY_SIDECAR',
                'CT_FLIGHT_REFERENCE_ROOT'):
        os.environ.pop(key, None)
    profile = Path(profile).resolve()
    info = configure_profile(profile)
    os.environ['CT_FREE_ATTRACTION_ASSUMPTION'] = '1'
    os.environ['CT_XIAMEN_HISTORICAL_FARES'] = '1'
    if planner:
        sys.path.insert(0, str(profile / 'planner'))
    info['profile'] = profile.name
    return info


def main(profile=PROFILE, *, allow_trial_date=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool', choices=TOOLS)
    parser.add_argument('--args-file', type=Path)
    parser.add_argument('--output-schema', action='store_true')
    if allow_trial_date:
        parser.add_argument('--trial-start-date', type=date.fromisoformat,
                            help='Replay pre-collected map evidence for this trial date')
    args = parser.parse_args()
    info = configure(profile=profile)
    if allow_trial_date:
        os.environ.pop('CT_LOCAL_ROUTE_TRIAL_START_DATE', None)
        if args.trial_start_date:
            os.environ['CT_LOCAL_ROUTE_TRIAL_START_DATE'] = args.trial_start_date.isoformat()
    if args.output_schema:
        print((profile / 'engine/chinatravel/evaluation/output_schema.json').read_text(encoding='utf-8'))
        return
    if not args.tool:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return
    if not args.args_file:
        parser.error('--args-file is required')
    arguments = json.loads(args.args_file.read_text(encoding='utf-8-sig'))
    if args.tool == 'room_options':
        result = room_options(profile=profile, **arguments)
    else:
        from sandbox_adapter import Sandbox
        result = getattr(Sandbox('G3'), args.tool)(**arguments)
    print(json.dumps({'configuration': info, 'result': result}, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
