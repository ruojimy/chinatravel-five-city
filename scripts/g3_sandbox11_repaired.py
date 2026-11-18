"""Select the repaired Xi'an benchmark while preserving its original engine contract."""
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import sys

from g3_sandbox import REPO, configure as configure_base
from g3_sandbox12_xiamen import digest

BASE = REPO / 'data/sandbox_profiles/xian_n16v2'
PROFILE = BASE.with_name('xian11_historical_repair')


def configure():
    if 'sandbox_adapter' in sys.modules or 'chinatravel' in sys.modules:
        raise RuntimeError('Configure the repaired sandbox before importing its tools')
    receipt = json.loads((PROFILE / 'receipt.json').read_text(encoding='utf-8'))
    if receipt['schema'] != 'xian11-historical-repair-v1':
        raise ValueError('Invalid Xi’an repair receipt')
    files = {path.relative_to(PROFILE).as_posix(): path for path in PROFILE.rglob('*')
             if path.is_file() and path != PROFILE / 'receipt.json'
             and '__pycache__' not in path.parts and path.suffix != '.pyc'}
    if set(files) != set(receipt['files']) or any(digest(path) != receipt['files'][name]
                                                for name, path in files.items()):
        raise ValueError('Xi’an repaired profile files changed')
    for key in ('CT_TRAVEL_DATE', 'CT_TRAVEL_START_DATE', 'CT_TRAVEL_END_DATE',
                'CT_OFFICIAL_FARE_SIDECAR', 'CT_OFFICIAL_DISPLAY_SIDECAR',
                'CT_FLIGHT_REFERENCE_ROOT', 'CT_FREE_ATTRACTION_ASSUMPTION', 'CT_XIAMEN_DISCOVERY_ONLY'):
        os.environ.pop(key, None)
    engine = PROFILE / 'engine'
    info = configure_base(BASE, engine=engine)
    if info['snapshot_sha256'] != receipt['base_snapshot_sha256']:
        raise ValueError('Xi’an base snapshot changed')
    os.environ.update(CHINATRAVEL_DATABASE_ROOT=str(PROFILE / 'database'),
                      CT_SANDBOX_RUNTIME_DIR=str(PROFILE / 'runtime'), CT_XIAMEN_HISTORICAL_FARES='1')
    sys.path[:0] = [str(PROFILE / 'runtime'), str(engine)]
    return dict(info, profile=PROFILE.name, database=os.environ['CHINATRAVEL_DATABASE_ROOT'],
                receipt_sha256=sha256((PROFILE / 'receipt.json').read_bytes()).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool', choices=('catalog_list', 'catalog_search', 'catalog_entity',
                                           'catalog_preflight', 'reference_search', 'intercity_search', 'goto'))
    parser.add_argument('--args-file', type=Path)
    args = parser.parse_args()
    info = configure()
    if not args.tool:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        if not args.args_file:
            parser.error('--args-file is required')
        from sandbox_adapter import Sandbox
        arguments = json.loads(args.args_file.read_text(encoding='utf-8-sig'))
        result = getattr(Sandbox('G3'), args.tool)(**arguments)
        print(json.dumps({'configuration': info, 'result': result}, ensure_ascii=False, allow_nan=False))
