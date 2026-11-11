"""Package P25 source, reports and evidence without credentials or databases."""
import hashlib,json,zipfile
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p25_reliable_retrieval'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
    assert json.loads((OUT/'validation.json').read_text(encoding='utf-8'))['all_pass']
    archive=OUT/'P25_修复与可靠条件方案.zip'
    if archive.exists():raise FileExistsError('Preserve delivered package')
    files=sorted(p for p in OUT.rglob('*') if p.is_file() and p.suffix!='.zip' and p.name not in ('manifest.json','delivery_receipt.json') and '__pycache__' not in p.parts)
    files+=sorted((ROOT/'scripts').glob('p25_*.py'))
    files+=[ROOT/'src/shorttrip'/n for n in ('retrieval_guard.py','retrieval_benchmark.py','freshness.py','live_amap.py')]
    files+=[ROOT/'tests/test_retrieval_guard.py',ROOT/'tests/test_retrieval_benchmark.py',ROOT/'报告/17_ChinaTravel原生与扩展Schema测试总结及修复报告.md',ROOT/'报告/17_测试汇总核对.json']
    records=[{'file':p.relative_to(ROOT).as_posix(),'sha256':digest(p),'bytes':p.stat().st_size} for p in files]
    manifest=OUT/'manifest.json';save(manifest,{'at':datetime.now(timezone.utc).isoformat(),'path_base':str(ROOT),'files':records,
        'scope':'Focused repair and real conditional witness; existing workspace required; credentials/databases excluded',
        'excludes':['manifest itself','ZIP itself','delivery receipt']})
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files+[manifest]:z.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None and len(z.namelist())==len(set(z.namelist()))==len(files)+1
        for row in records:assert hashlib.sha256(z.read(row['file'])).hexdigest()==row['sha256'],row['file']
    receipt={'at':datetime.now(timezone.utc).isoformat(),'archive':archive.name,'bytes':archive.stat().st_size,'sha256':digest(archive),
        'files':len(files)+1,'manifest_sha256':digest(manifest),'zip_crc_and_manifest_hashes_pass':True,'credentials_included':False,'standalone_installation':False}
    save(OUT/'delivery_receipt.json',receipt);print(json.dumps(receipt,ensure_ascii=True))
if __name__=='__main__':main()
