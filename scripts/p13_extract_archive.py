"""Stream one licensed-reference CSV at a time, exact city/name binding only."""
import collections,csv,gzip,hashlib,io,json,sqlite3,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_archives import name_aliases,parse_reference
from shorttrip.freshness import canonical,utcnow
from shorttrip.travel_catalog import digest_file
OUT=ROOT/'results/p13_business_completion'
def main():
    dbpath=ROOT/'data/expansion_catalog_v1_1_20261022/catalog.sqlite3'
    db=sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True)
    index=collections.defaultdict(set)
    for rid,city,name in db.execute("SELECT id,city,name FROM records WHERE kind='attraction' AND provider_city_match=1"):
        for alias in name_aliases(name):index[(city,alias)].add(rid)
    archive=ROOT/'data/raw/p13_attractions/china-city-attraction-details-v3.zip';counts=collections.Counter()
    reference_seen=set();matched_ids=set();ambiguous=[];coverage=collections.Counter();all_stats=collections.Counter()
    references=OUT/'archive_enrichment.jsonl.gz'
    with zipfile.ZipFile(archive) as z,gzip.open(references,'wt',encoding='utf-8',newline='\n') as target:
        for info in z.infolist():
            if not info.filename.endswith('.csv'):continue
            city=Path(info.filename).stem
            with z.open(info) as raw:
                for lineno,row in enumerate(csv.DictReader(io.TextIOWrapper(raw,encoding='utf-8-sig')),start=2):
                    counts['archive_rows']+=1
                    parsed=parse_reference(row)
                    all_stats['complete_reference_operational_rows']+=parsed['complete_operational_fields']
                    for f in parsed['native_values']:all_stats[f]+=1
                    hits=set()
                    for alias in name_aliases(row.get('名字')):hits|=index.get((city,alias),set())
                    if len(hits)!=1:
                        if hits:ambiguous.append({'city':city,'name':row['名字'],'candidate_ids':sorted(hits)})
                        continue
                    rid=next(iter(hits));key=(rid,row.get('链接'))
                    if key in reference_seen:counts['duplicate_archive_rows']+=1;continue
                    reference_seen.add(key);matched_ids.add(rid)
                    facts={k:row.get(k,'') for k in ('名字','链接','地址','开放时间','建议游玩时间','门票')}
                    item={'record_id':rid,'city':city,'match':'unique_exact_name_alias_same_city_not_independent_identity_verification',
                        'source_id':'kaggle_qunar_attractions_v3','source_url':'https://www.kaggle.com/datasets/audreyhengruizhang/china-city-attraction-details',
                        'upstream_url':row.get('链接'),'archive_file':str(archive.relative_to(ROOT)),'archive_member':info.filename,
                        'csv_line_1based':lineno,'raw_facts':facts,'raw_sha256':hashlib.sha256(canonical(facts).encode()).hexdigest(),
                        'dataset_released_at':'2023-07-16T03:04:34.337Z','source_published_at':None,
                        'source_updated_at':None,'observed_at':None,'retrieved_at':'2026-10-22T11:39:53+00:00',
                        'valid_until':None,'licence_declaration':'Apache 2.0 by dataset publisher; upstream reuse not independently established',
                        'trust_status':'historical_reference_requires_current_verification',**parsed}
                    target.write(json.dumps(item,ensure_ascii=False,separators=(',',':'))+'\n')
                    counts['matched_reference_rows']+=1;counts['complete_reference_operational_rows']+=parsed['complete_operational_fields']
                    coverage.update(parsed['native_values'].keys())
    db.close()
    summary={'executed_at':utcnow(),'counts':dict(counts),'matched_unique_entities':len(matched_ids),
        'matched_field_coverage':dict(coverage),'whole_archive_parser_counts':dict(all_stats),
        'ambiguous_matches':ambiguous,'current_eligible_rows':0,'real_planning_ready_rows':0,
        'archive_sha256':digest_file(archive),'output_sha256':digest_file(references),
        'policy':'Historical source fields retained; unknown observation age, products/starting prices, source-rights ambiguity and unverified identity are not silently promoted to current native planning facts.'}
    (OUT/'archive_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ('counts','matched_unique_entities','matched_field_coverage','whole_archive_parser_counts')},ensure_ascii=False))
if __name__=='__main__':main()
