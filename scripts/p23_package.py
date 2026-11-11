"""Package the audited P23 run without credentials or third-party databases."""
import hashlib, json, zipfile
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p23_scaled_llm'

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
    validation=json.loads((OUT/'validation.json').read_text(encoding='utf-8'))
    if not validation['all_pass']:raise ValueError('validation failed')
    archive=OUT/'P23_扩大测试与检索交付.zip'
    if archive.exists():raise FileExistsError('Archive already exists; preserve delivered evidence')
    sources=[ROOT/'scripts'/name for name in ('p23_prepare.py','p23_run.py','p23_retrieve.py','p23_plan.py','p23_analyze.py','p23_validate.py','p23_package.py')]
    sources += [ROOT/'src/shorttrip'/name for name in ('__init__.py','intent_planner.py','intent_planner_v2.py','planner.py','env.py','plan.py','checker.py')]
    sources += [ROOT/'tests/test_intent_planner.py']
    files=sorted(p for p in OUT.rglob('*') if p.is_file() and p.name not in ('manifest.json','delivery_receipt.json') and p.suffix!='.zip' and '__pycache__' not in p.parts)+sources
    records=[{'file':p.relative_to(ROOT).as_posix(),'sha256':digest(p),'bytes':p.stat().st_size} for p in files]
    dependencies=[]
    for split in ('easy','medium','human','competition_test'):
        for p in sorted((ROOT/'ChinaTravel/chinatravel/data'/split).glob('*.json')):
            dependencies.append({'file':p.relative_to(ROOT).as_posix(),'sha256':digest(p),'bytes':p.stat().st_size})
    for folder in ('evaluation','symbol_verification','environment/tools'):
        for p in sorted((ROOT/'ChinaTravel/chinatravel'/folder).rglob('*.py')):
            dependencies.append({'file':p.relative_to(ROOT).as_posix(),'sha256':digest(p),'bytes':p.stat().st_size})
    manifest=OUT/'manifest.json'
    save(manifest,{'at':datetime.now(timezone.utc).isoformat(),'path_base':str(ROOT),'files':records,
        'external_dependencies_not_in_zip':dependencies,
        'dependency_scope':'Official query and evaluator/tool code fingerprints; full database tables and Python runtime not bundled or exhaustively fingerprinted',
        'excludes':['manifest itself','delivery receipt','ZIP itself','third-party databases','credentials']})
    packed=files+[manifest]
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in packed:z.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as z:
        bad=z.testzip();assert bad is None,bad
        assert len(z.namelist())==len(packed)==len(set(z.namelist()))
        for r in records:assert hashlib.sha256(z.read(r['file'])).hexdigest()==r['sha256'],r['file']
        assert hashlib.sha256(z.read(manifest.relative_to(ROOT).as_posix())).hexdigest()==digest(manifest)
    receipt={'at':datetime.now(timezone.utc).isoformat(),'archive':archive.name,'sha256':digest(archive),
        'bytes':archive.stat().st_size,'archive_entries':len(packed),'manifest_files':len(records),
        'manifest_sha256':digest(manifest),'zip_crc_and_all_manifest_hashes_pass':True,
        'existing_workspace_required':True,'official_databases_included':False,'credentials_included':False}
    save(OUT/'delivery_receipt.json',receipt);print(json.dumps(receipt,ensure_ascii=True))

if __name__=='__main__':main()
