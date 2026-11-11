"""Stream an add-on archive and verify all entries against SHA256."""
from pathlib import Path
import hashlib,json,sys,zipfile
ROOT=Path(__file__).resolve().parents[1];PROJECT=ROOT.parent
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.freshness import utcnow
from shorttrip.travel_catalog import digest_file
def main():
    destination=PROJECT/'静态数据扩容与完整入库合约_20261022.zip'
    if destination.exists():raise FileExistsError('Preserve previous delivery')
    selected=set()
    for folder in [ROOT/'src/shorttrip',ROOT/'results/p12_expansion',
       ROOT/'data/expansion_catalog_v1_1_20261022',ROOT/'data/expansion_v1_20261022',
       PROJECT/'.agents/skills/travel-live-retrieval']:
        for p in folder.rglob('*'):
            if not p.is_file() or '__pycache__' in p.parts or p.name=='staging.sqlite3':continue
            if folder==ROOT/'src/shorttrip' and p.suffix!='.py':continue
            selected.add(p)
    selected.update((ROOT/'scripts').glob('p12_*.py'))
    selected.update([ROOT/'scripts/travel_data.py',ROOT/'scripts/download_data.py',ROOT/'STATE.md',
       ROOT/'报告/12_扩容数据完整合约与独立模型验证.md',ROOT/'tests/test_expansion_contract.py',
       ROOT/'tests/test_expansion_store.py',ROOT/'tests/test_legacy_load_gates.py',ROOT/'tests/test_freshness_live.py'])
    paths=sorted(selected)
    entries={p.relative_to(PROJECT).as_posix():{'bytes':p.stat().st_size,'sha256':digest_file(p)} for p in paths}
    manifest={'created_at':utcnow(),'mode':'incremental existing-workspace delivery','entries':entries,
        'exclusions':['.secrets','virtual environments','staging.sqlite3','old baseline SQLite','failed build SQLite'],
        'real_planning_ready_records':0,'real_planning_ready_doubling_completed':False}
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
        for p in paths:z.write(p,p.relative_to(PROJECT).as_posix())
        z.writestr('DELIVERY_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    failures=[]
    with zipfile.ZipFile(destination) as z:
        crc=z.testzip()
        for name,proof in entries.items():
            h=hashlib.sha256();size=0
            with z.open(name) as f:
                for block in iter(lambda:f.read(1024*1024),b''):h.update(block);size+=len(block)
            if h.hexdigest()!=proof['sha256'] or size!=proof['bytes']:failures.append(name)
    verification={'checked_at':utcnow(),'archive':destination.name,'bytes':destination.stat().st_size,
       'sha256':digest_file(destination),'entry_count':len(entries)+1,'crc_first_failure':crc,
       'sha256_mismatches':failures,'all_ok':crc is None and not failures,'excluded_baseline_files':264,
       'network_requests':0,'streaming_verification':True}
    (PROJECT/'静态数据扩容与完整入库合约_20261022.delivery_verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(verification,ensure_ascii=False))
    if not verification['all_ok']:raise SystemExit(1)
if __name__=='__main__':main()
