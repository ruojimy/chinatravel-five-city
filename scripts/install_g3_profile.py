"""Install a validated snapshot as a new immutable repository G3 profile."""
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
import argparse,json,os,shutil
from g3_sandbox import configure,REPO

def sha(p):return sha256(p.read_bytes()).hexdigest()

def copy_path(path):
    # Staging adds a long suffix to nested sandbox paths on Windows. Preserve
    # their absolute spelling with the extended-length filesystem prefix.
    value=str(Path(path).resolve())
    if os.name=='nt' and not value.startswith('\\\\?\\'):
        return '\\\\?\\UNC\\'+value[2:] if value.startswith('\\\\') else '\\\\?\\'+value
    return value

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',type=Path,required=True)
    ap.add_argument('--name',required=True)
    ap.add_argument('--legacy-anchors',type=Path,
                    help='Earlier captured Amap endpoint evidence to pin into the new profile')
    a=ap.parse_args()
    if not a.name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in a.name):
        raise ValueError('profile name must contain letters, numbers, underscores or hyphens')
    source=a.source.resolve();base=(REPO/'data/sandbox_profiles').resolve();target=base/a.name
    if target.exists():raise FileExistsError('profile already exists; old snapshots are immutable')
    before=configure(source,environ={});base.mkdir(parents=True,exist_ok=True)
    staging=base/('.'+a.name+'.partial-'+uuid4().hex)
    shutil.copytree(copy_path(source),copy_path(staging),ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.tmp'))
    snapshot=staging/'data_integration/dynamic_snapshot_v2.json'
    if a.legacy_anchors:
        anchors=a.legacy_anchors.resolve()
        if not anchors.is_file():raise FileNotFoundError(anchors)
        raw=anchors.read_bytes()
        if b'"key"' in raw.lower() or b'?key=' in raw.lower() or b'&key=' in raw.lower():
            raise ValueError('anchor evidence may contain a credential; refusing to copy')
        dest=snapshot.parent/'amap_sample_prefetch_20261115.json'
        if dest.exists():raise FileExistsError('legacy anchor evidence already exists')
        dest.write_bytes(raw)
        data=json.loads(snapshot.read_text(encoding='utf-8-sig'))
        data['evidence_files'].append({'path':dest.name,'sha256':sha(dest)})
        snapshot.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    checked=configure(staging,environ={})
    inventory={p.relative_to(staging).as_posix():sha(p) for p in staging.rglob('*')
               if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.tmp')
               and p.name not in ('profile_file_hashes.json','profile_install_receipt.json')}
    inventory_path=staging/'profile_file_hashes.json'
    inventory_path.write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    receipt={'installed_utc':datetime.now(timezone.utc).isoformat(),
             'source':str(source),'source_snapshot_sha256':before['snapshot_sha256'],
             'installed_snapshot_sha256':checked['snapshot_sha256'],
             'inventory_sha256':sha(inventory_path),'inventory_files':len(inventory),
             'legacy_anchors_added':bool(a.legacy_anchors),
             'boundary':'Immutable source-evidence profile; date-specific fares and availability remain conditional.'}
    (staging/'profile_install_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    configure(staging,environ={})
    # A failed copy/check stays at its unique .partial path for investigation.
    if target.exists():raise FileExistsError('profile was created concurrently')
    os.rename(staging,target)
    print(json.dumps({'profile':str(target),'snapshot_sha256':checked['snapshot_sha256']},ensure_ascii=False))

if __name__=='__main__':main()
