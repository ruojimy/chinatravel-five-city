"""Opt in to the local 12-city Xiamen historical benchmark profile."""
from pathlib import Path
from hashlib import sha256
import argparse,csv,json,os,sys
from g3_sandbox12 import REPO, configure as configure_base
PROFILE=REPO/'data/sandbox_profiles/xiamen12_historical_v19_maps'
def digest(p):return sha256(p.read_bytes()).hexdigest()
def configure(profile=PROFILE):
    profile=Path(profile).resolve();receipt=json.loads((profile/'receipt.json').read_text(encoding='utf8'))
    if receipt.get('schema')!='xiamen12-historical-v1':raise ValueError('invalid Xiamen profile')
    for rel,want in receipt['files'].items():
        p=(profile/rel).resolve()
        if not p.is_relative_to(profile) or not p.is_file() or digest(p)!=want:raise ValueError('profile evidence changed: '+rel)
    # Older local receipts did not inventory nested receipt files. Keep those
    # named, immutable versions readable; all newer versions hash them.
    legacy_nested_receipts=profile.name in {'xiamen12_historical','xiamen12_historical_v2','xiamen12_historical_v3','xiamen12_historical_v4'}
    actual={p.relative_to(profile).as_posix() for p in profile.rglob('*') if p.is_file() and p != profile/'receipt.json'
      and not (legacy_nested_receipts and p.name=='receipt.json') and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    if actual!=set(receipt['files']):raise ValueError('profile file inventory changed')
    configure_base()
    os.environ.update(CHINATRAVEL_PROFILE='expanded12',CHINATRAVEL_DATABASE_ROOT=str(profile/'database'),
        CT_SANDBOX_ENGINE_ROOT=str(profile/'engine'),CT_SANDBOX_RUNTIME_DIR=str(profile/'runtime'),
        CT_XIAMEN_DISCOVERY_ONLY='1')
    # Configure before importing chinatravel or sandbox_adapter. Put the
    # selected profile first even if its path was already present elsewhere.
    for path in (profile/'engine', profile/'runtime'):
        while str(path) in sys.path:sys.path.remove(str(path))
        sys.path.insert(0,str(path))
    return {'profile':'xiamen12_historical','path':str(profile),'receipt_sha256':digest(profile/'receipt.json'),
            'boundary':receipt['boundary']}
def room_options(hotel_name, *, include_reference=False, profile=PROFILE):
    """Read the historical room subtable without promoting unresolved sources."""
    root=Path(profile).resolve()
    with (root/'database/accommodations/xiamen/accommodations.csv').open(encoding='utf-8-sig',newline='') as stream:
        hits=[r for r in csv.DictReader(stream) if r.get('name')==hotel_name]
    if len(hits)!=1:
        return {'hotel_name':hotel_name,'status':'unknown_or_ambiguous_hotel','matched_records':len(hits),'rooms':[]}
    key=hits[0]['id'];evidence=root/'xiamen_evidence'
    with (evidence/'official_room_price_history.csv').open(encoding='utf-8-sig',newline='') as stream:
        official=[dict(r) for r in csv.DictReader(stream) if r.get('main_record_id')==key]
    with (evidence/'room_types_history.csv').open(encoding='utf-8-sig',newline='') as stream:
        refs=[dict(r) for r in csv.DictReader(stream) if r.get('main_record_id')==key]
    variants=[];variant_path=evidence/'nikko_manual/manual_room_variants.csv'
    if variant_path.is_file():
        with variant_path.open(encoding='utf-8-sig',newline='') as stream:
            variants=[dict(r) for r in csv.DictReader(stream) if r.get('hotel_main_id')==key]
    return {'hotel_name':hotel_name,'status':'historical_reference','official_rooms':official,
       'historical_manual_variants':variants,
       'reference_count':len(refs),'reference_rooms':refs if include_reference else [],
       'reference_notice':'Trip/Ctrip source access status is unresolved; reference rows are not admitted as planning facts.',
       'availability':'unknown','notice':'Historical room configurations and scoped prices do not establish present availability.'}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--profile',type=Path,default=PROFILE)
    ap.add_argument('--tool',choices=('catalog_list','catalog_search','catalog_entity','catalog_preflight','reference_search','intercity_search','goto','room_options'))
    ap.add_argument('--args-file',type=Path);args=ap.parse_args();info=configure(args.profile)
    if not args.tool:print(json.dumps(info,ensure_ascii=False,indent=2));return
    if not args.args_file:ap.error('--args-file required')
    kw=json.loads(args.args_file.read_text(encoding='utf-8-sig'))
    if args.tool=='room_options':result=room_options(profile=args.profile,**kw)
    else:
        from sandbox_adapter import Sandbox
        result=getattr(Sandbox('G3'),args.tool)(**kw)
    print(json.dumps({'configuration':info,'result':result},ensure_ascii=False,allow_nan=False))
if __name__=='__main__':main()
