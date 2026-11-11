"""Package P24 schemas, participant episodes and minimal source evidence."""
import hashlib,json,zipfile
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p24_dynamic_feedback'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
    assert read(OUT/'validation.json')['all_pass']
    archive=OUT/'P24_新城市分层动态检索交付.zip'
    if archive.exists():raise FileExistsError('Preserve delivered archive')
    sources=[ROOT/'src/shorttrip/retrieval_benchmark.py',ROOT/'src/shorttrip/freshness.py',ROOT/'src/shorttrip/live_amap.py',ROOT/'tests/test_retrieval_benchmark.py']
    sources+=sorted((ROOT/'scripts').glob('p24_*.py'))
    live_allowed={'amap_ledger.json','source_pauses.json'}
    files=sorted(p for p in OUT.rglob('*') if p.is_file() and p.name not in ('manifest.json','delivery_receipt.json') and p.suffix!='.zip'
        and '__pycache__' not in p.parts and ('live' not in p.relative_to(OUT).parts or p.name in live_allowed))+sources
    records=[{'file':p.relative_to(ROOT).as_posix(),'sha256':digest(p),'bytes':p.stat().st_size} for p in files]
    capture_paths={e['original_capture_file'] for e in read(OUT/'private/evidence_corpus.json')['evidence'] if e.get('original_capture_file')}
    capture_paths.update(p.relative_to(ROOT).as_posix() for p in (OUT/'live').glob('*.json') if p.name not in live_allowed)
    external=[{'file':name,'sha256':digest(ROOT/name),'bytes':(ROOT/name).stat().st_size} for name in sorted(capture_paths)]
    manifest=OUT/'manifest.json'
    save(manifest,{'at':datetime.now(timezone.utc).isoformat(),'path_base':str(ROOT),'files':records,'audit_captures_not_distributed':external,
        'scope':'Contains minimal quotes, structured provider evidence, complete96case/192proposal episodes, schemas, code and failures. Full webpage tool packets stay local.',
        'external_requirements':['Existing reproduction workspace and .venv','Official ChinaTravel code/data for original preparation','Formal expansion catalog and old manifests for full integrity audit'],
        'self_excludes':['manifest','archive','delivery receipt']})
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files+[manifest]:z.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert len(z.namelist())==len(set(z.namelist()))==len(files)+1
        for r in records:assert hashlib.sha256(z.read(r['file'])).hexdigest()==r['sha256'],r['file']
        assert hashlib.sha256(z.read(manifest.relative_to(ROOT).as_posix())).hexdigest()==digest(manifest)
    receipt={'at':datetime.now(timezone.utc).isoformat(),'archive':archive.name,'sha256':digest(archive),'bytes':archive.stat().st_size,
        'entries':len(files)+1,'manifest_files':len(records),'manifest_sha256':digest(manifest),'crc_and_all_manifest_hashes_pass':True,
        'credentials_included':False,'full_web_pages_included':False,'standalone_installation':False}
    save(OUT/'delivery_receipt.json',receipt);print(json.dumps(receipt,ensure_ascii=True))
if __name__=='__main__':main()
