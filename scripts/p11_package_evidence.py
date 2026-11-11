"""Create a small evidence/source bundle; reference, do not duplicate, SQLite."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,zipfile
ROOT=Path(__file__).resolve().parents[1];WORK=ROOT.parent
OUT=ROOT/'results/p11_freshness_skill'

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    catalog=ROOT/'data/catalog_v1_1_20261022'
    integrity=json.loads((OUT/'catalog_integrity.json').read_text(encoding='utf-8'))
    assert integrity['records_checked']==67612 and integrity['all_source_hashes_unchanged']
    final=(OUT/'test_freshness_live.final.log').read_text(encoding='utf-8')
    assert 'Ran 36 tests' in final and '\nOK' in final
    assert 'Skill is valid!' in (OUT/'skill_validation.log').read_text(encoding='utf-8')
    write(OUT/'external_catalog_reference.json',{'path':catalog.relative_to(WORK).as_posix()+'/catalog.sqlite3',
        'bytes':(catalog/'catalog.sqlite3').stat().st_size,'sha256_at_checkpoint':digest(catalog/'catalog.sqlite3'),
        'included_in_zip':False,'note':'Full annotation database stays in workspace. Future appended claims change database bytes; source file hashes remain in manifest.'})
    names=['src/shorttrip/freshness.py','src/shorttrip/travel_catalog.py','src/shorttrip/live_amap.py',
           'src/shorttrip/candidate_matching.py','scripts/travel_data.py','scripts/p11_verify_catalog.py',
           'scripts/p11_record_secondary_checks.py','scripts/p11_package_evidence.py','tests/test_freshness_live.py',
           'data/travel_source_registry.json','报告/11_数据时效可信度与动态检索Skill.md','STATE.md','README.md']
    files=[ROOT/p for p in names]
    files.extend(p for p in catalog.iterdir() if p.is_file() and p.suffix!='.sqlite3')
    files.extend(p for p in (WORK/'.agents/skills/travel-live-retrieval').rglob('*') if p.is_file())
    files.extend(p for p in OUT.rglob('*') if p.is_file() and p.name!='artifact_manifest.json')
    files=sorted(set(files))
    # Do not print credential contents; assert the single used key is absent.
    key_path=ROOT/'.secrets/amap.key'
    secret=key_path.read_bytes().strip() if key_path.exists() else b''
    if secret:
        assert all(secret not in p.read_bytes() for p in files),'Credential found in selected evidence; no archive created'
    entries=[{'path':p.relative_to(WORK).as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)} for p in files]
    write(OUT/'artifact_manifest.json',{'created_at':datetime.now(timezone.utc).isoformat(),
        'self_excluded':True,'secret_scan_passed':True,'files':entries})
    files.append(OUT/'artifact_manifest.json')
    target=WORK/'数据时效与动态检索Skill_20261022.zip'
    with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files:z.write(p,p.relative_to(WORK).as_posix())
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        for entry in entries:assert hashlib.sha256(z.read(entry['path'])).hexdigest()==entry['sha256']
    result={'archive':target.name,'bytes':target.stat().st_size,'sha256':digest(target),
            'file_count':len(files),'crc_verified':True,'manifest_hashes_verified':True,
            'full_sqlite_stays_in_workspace':True,'credential_scan_passed':True}
    write(target.with_suffix('.delivery_verification.json'),result);print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
