"""Configure and inspect a hash-verified expanded eleven-city sandbox profile.

Configuration occurs before importing chinatravel, whose checkers initialise
singleton tools. Run a new process when switching profiles.
"""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
import argparse,json,os,sys

REPO=Path(__file__).resolve().parents[1]
RUNTIME=REPO/'src/sandbox_runtime'
ENGINE=REPO/'ShortTrip-upstream'

def _checked_file(base, rel, expected):
    rel=Path(rel)
    path=(base/rel).resolve()
    if rel.is_absolute() or not path.is_relative_to(base.resolve()) or not path.is_file():
        raise ValueError('unsafe or missing evidence path: '+str(rel))
    actual=sha256(path.read_bytes()).hexdigest()
    if actual!=expected:raise ValueError('evidence hash mismatch: '+str(rel))
    return path

def configure(profile, *, engine=ENGINE, live_dir=None, environ=None):
    profile=Path(profile).resolve();engine=Path(engine).resolve()
    if live_dir:
        live_path=Path(live_dir).resolve()
        if live_path==profile or live_path.is_relative_to(profile):
            raise ValueError('live journal must be outside the immutable profile')
    snapshot=profile/'data_integration/dynamic_snapshot_v2.json'
    db=profile/'expanded/G3_ext11/chinatravel/environment/database'
    if not snapshot.is_file() or not db.is_dir() or not (engine/'chinatravel').is_dir():
        raise FileNotFoundError('missing sandbox snapshot, database or engine')
    data=json.loads(snapshot.read_text(encoding='utf-8-sig'))
    if data.get('schema')!='chinatravel-dynamic-snapshot-v4.2':
        raise ValueError('unsupported snapshot schema')
    for entry in data['evidence_files']:
        _checked_file(snapshot.parent,entry['path'],entry['sha256'])
    for entry in data['changed_direct_files']:
        _checked_file(profile,entry['path'],entry['after_sha256'])
    inventory=profile/'profile_file_hashes.json'
    if inventory.is_file():
        receipt=profile/'profile_install_receipt.json'
        if receipt.is_file():
            recorded=json.loads(receipt.read_text(encoding='utf-8-sig')).get('inventory_sha256')
            if recorded and recorded!=sha256(inventory.read_bytes()).hexdigest():
                raise ValueError('profile inventory receipt mismatch')
        declared=json.loads(inventory.read_text(encoding='utf-8-sig'))
        if not isinstance(declared,dict):raise ValueError('invalid profile inventory')
        for rel,expected in declared.items():_checked_file(profile,rel,expected)
        actual={p.relative_to(profile).as_posix() for p in profile.rglob('*') if p.is_file()
                and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.tmp')
                and p.name not in ('profile_file_hashes.json','profile_install_receipt.json')}
        if actual!=set(declared):raise ValueError('profile file inventory changed')
    target=os.environ if environ is None else environ
    target.update(CHINATRAVEL_PROFILE='expanded11',CHINATRAVEL_DATABASE_ROOT=str(db),
                      CT_SANDBOX_PROFILE_ROOT=str(profile),CT_SANDBOX_ENGINE_ROOT=str(engine),
                      CT_SANDBOX_RUNTIME_DIR=str(RUNTIME),CT_DYNAMIC_MODE='live' if live_dir else 'snapshot')
    if live_dir:target['CT_DYNAMIC_LIVE_DIR']=str(live_path)
    else:target.pop('CT_DYNAMIC_LIVE_DIR',None)
    return {'profile':str(profile),'engine':str(engine),'database':str(db),
            'snapshot_sha256':sha256(snapshot.read_bytes()).hexdigest(),
            'mode':'live' if live_dir else 'snapshot'}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--profile',type=Path,required=True)
    ap.add_argument('--engine',type=Path,default=ENGINE)
    ap.add_argument('--live-dir',type=Path)
    ap.add_argument('--tool',choices=('catalog_list','catalog_search','catalog_entity','catalog_preflight',
                                      'reference_search','intercity_search','goto'))
    ap.add_argument('--args-file',type=Path)
    args=ap.parse_args();info=configure(args.profile,engine=args.engine,live_dir=args.live_dir)
    if not args.tool:
        print(json.dumps(info,ensure_ascii=False,indent=2));return
    if not args.args_file:ap.error('--args-file is required with --tool')
    arguments=json.loads(args.args_file.read_text(encoding='utf-8-sig'))
    if not isinstance(arguments,dict):raise ValueError('tool arguments must be an object')
    sys.path.insert(0,str(RUNTIME))
    from sandbox_adapter import Sandbox
    result=getattr(Sandbox('G3'),args.tool)(**arguments)
    print(json.dumps({'configuration':info,'result':result},ensure_ascii=False,allow_nan=False))

if __name__=='__main__':main()
