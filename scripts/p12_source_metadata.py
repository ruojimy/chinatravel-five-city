"""Save declared licenses and clock policies, independently of fact freshness."""
from pathlib import Path
import collections,gzip,hashlib,json,shutil,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.freshness import POLICIES,VERSION,utcnow
from shorttrip.travel_catalog import digest_file
OUT=ROOT/'data/expansion_catalog_v1_1_20261022'
def main():
    import requests
    licence_dir=OUT/'licences';licence_dir.mkdir(exist_ok=True)
    links={'CDLA-Permissive-2.0':'https://cdla.dev/permissive-2-0/',
      'Apache-2.0':'https://www.apache.org/licenses/LICENSE-2.0.txt',
      'CC0-1.0':'https://creativecommons.org/publicdomain/zero/1.0/legalcode.txt'}
    captures=[]
    for licence,url in links.items():
        path=licence_dir/(licence+('.html' if licence=='CDLA-Permissive-2.0' else '.txt'))
        if not path.exists():
            try:
                response=requests.get(url,timeout=20,headers={'User-Agent':'ShortTripResearch/1.0 (licence documentation only)'})
                response.raise_for_status();path.write_bytes(response.content)
                captures.append({'licence':licence,'url':response.url,'retrieved_at':utcnow(),'saved':True,
                    'file':str(path.relative_to(ROOT)),'sha256':digest_file(path)})
            except Exception as exc:captures.append({'licence':licence,'url':url,'saved':False,'error':type(exc).__name__})
        else:captures.append({'licence':licence,'url':url,'saved':True,'cache':True,'sha256':digest_file(path)})
    source_card=ROOT/'data/raw/sandbox/README.md';target=licence_dir/'ChinaTravel-dataset-card.md'
    shutil.copy2(source_card,target)
    counts=collections.Counter();providers=collections.Counter()
    with gzip.open(OUT/'records.jsonl.gz','rt',encoding='utf-8') as f:
        for line in f:
            record=json.loads(line)
            for source in record['source_locator']['providers']:
                counts[source.get('license')]+=1;providers[source.get('dataset')]+=1
    registry={'recorded_at':utcnow(),'overture_places_20261021':{
       'source_name':'Overture Maps Foundation, places release 2026-10-21.0',
       'source_url':'https://docs.overturemaps.org/guides/places/',
       'attribution_url':'https://docs.overturemaps.org/attribution/',
       'access_method':'Anonymous S3 regional GeoParquet slice selected using STAC',
       'authority':'open_aggregate_dataset','independence_group':'overture_aggregate',
       'fact_accuracy_probability':None,'source_observation_time_unknown':True,
       'release_date_is_not_observation':True,'licence_status':'allowed',
       'row_source_licences':dict(counts),'row_provider_mentions':dict(providers),
       'required_attribution':'Overture Maps Foundation, overturemaps.org; original provider and per-row license retained in sources.',
       'license_urls':links,'network_paused_after_429':True,
       'supports_only_source_snapshot':['name','coordinates','category','provider_locality'],
       'does_not_supply':['current_hours','current_prices','hotel_beds','weather','live_route_duration','live_route_fare']},
       'chinatravel_sandbox':{'source_name':'LAMDA-NeSy/ChinaTravel-Sandbox','release':'2026.08.2',
        'source_url':'https://huggingface.co/datasets/LAMDA-NeSy/ChinaTravel-Sandbox',
        'declared_licence':'CC-BY-4.0','licence_declaration_evidence':'data/raw/sandbox/README.md',
        'declaration_sha256':digest_file(source_card),'checked_local_card':True,'live_remote_hash_verified_this_stage':False,
        'source_fact_observation_time':None,'authority':'research_benchmark_not_live_operator',
        'citation':'Shao et al., ChinaTravel, ICLR 2026; https://github.com/LAMDA-NeSy/ChinaTravel',
        'policy_note':'New local license evidence updates this sidecar only; old P11 snapshots are preserved and remain historical. A license declaration does not refresh facts.'},
       'license_document_captures':captures}
    (OUT/'source_registry.json').write_text(json.dumps(registry,ensure_ascii=False,indent=2),encoding='utf-8')
    policies={'version':VERSION,'recorded_at':utcnow(),'policies':{k:{'ttl_seconds':v[0],'mandatory_dynamic':v[1]} for k,v in POLICIES.items()},
       'unknown_clock':'valid_until=null and retrieval required; never substitute release/download/import date',
       'native_units':{'price':'CNY per person for attraction/restaurant; CNY per room-night for accommodation',
          'Duration':'hours','recommendmintime':'hours','recommendmaxtime':'hours','numbed':'beds per room',
          'route_duration_claim':'minutes','route_fare_claim':'CNY'},
       'note':'Policy TTLs are project defaults, not source guarantees. Date/occupancy/room-type context remains necessary.'}
    (OUT/'policy_snapshot.json').write_text(json.dumps(policies,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))
    manifest['metadata_files']=[{'file':str(p.relative_to(ROOT)),'sha256':digest_file(p),'bytes':p.stat().st_size}
        for p in (OUT/'source_registry.json',OUT/'policy_snapshot.json')]
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'licence_documents_saved':sum(x['saved'] for x in captures),'licenses':list(counts),
        'metadata_files':len(manifest['metadata_files']),'no_overture_retry':True},ensure_ascii=False))
if __name__=='__main__':main()
