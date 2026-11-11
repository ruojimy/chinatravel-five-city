"""Stream historical CSVs and join literal source language aliases conservatively.

No translations, fuzzy names, numeric cross-provider IDs, new entities or requests.
"""
import collections, csv, gzip, hashlib, json, math, sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from shorttrip.business_archives import normalize_name as norm
from shorttrip.source_identity import language_aliases
from shorttrip.dynamic.opendata import gcj02_to_wgs84
from shorttrip.freshness import utcnow
from shorttrip.travel_catalog import digest_file
BASE = ROOT / 'results/p17_continuous/open_datasets'
OUT = BASE / 'language_alias_batch_001'


def main():
    OUT.mkdir(exist_ok=False)
    pointer = json.loads((ROOT / 'results/p15_whole_catalog/current_catalog.json').read_text())
    catalog = sqlite3.connect(ROOT / pointer['catalog'])
    records, slugs, wanted = {}, {}, collections.defaultdict(dict)
    for payload, in catalog.execute('SELECT payload FROM records'):
        r = json.loads(payload)
        if r.get('city_slug'): slugs[norm(r['city_slug'])] = r['city']
        loc = r.get('source_locator', {})
        if not r['record_id'].startswith('overture:') or not loc.get('raw_file'): continue
        # Existing historical matches are retained; this is only an incremental batch.
        if any(a['source_id'].startswith('p17-triptailor:') for a in r.get('operator_assertions', [])): continue
        lean = {k:r[k] for k in ('record_id', 'name', 'city', 'kind', 'source_locator')}
        lean['data'] = {k:r['data'].get(k) for k in ('lon', 'lat', 'hotelname_en')}
        records[r['record_id']] = lean
        wanted[loc['raw_file']][loc['raw_line']] = r['record_id']
    catalog.close()
    alias_db = sqlite3.connect(OUT / 'source_names.sqlite3')
    alias_db.executescript('PRAGMA cache_size=-4000; CREATE TABLE names(kind TEXT,city TEXT,name TEXT,entity_id TEXT,alias TEXT,raw_payload TEXT); CREATE INDEX named ON names(kind,city,name);')
    bound = 0
    for filename, ordinals in wanted.items():
        with gzip.open(ROOT / filename, 'rb') as stream:
            for ordinal, raw in enumerate(stream, 1):
                rid = ordinals.get(ordinal)
                if rid is None: continue
                content = raw.rstrip(b'\r\n'); row = json.loads(content); r = records[rid]
                if (hashlib.sha256(content).hexdigest() != r['source_locator']['raw_sha256']
                        or row['id'] != rid.removeprefix('overture:') or row['names']['primary'] != r['name']):
                    raise ValueError('Original entity evidence mismatch: ' + rid)
                for name, alias in language_aliases(row).items():
                    # Primary names were already tested. Only an additional literal alias helps.
                    if name in {norm(r['name']), norm(r['data'].get('hotelname_en'))}: continue
                    alias_db.execute('INSERT INTO names VALUES(?,?,?,?,?,?)',
                        (r['kind'], r['city'], name, rid, json.dumps(alias, ensure_ascii=False), content.decode()))
                bound += 1
    alias_db.commit()
    capture = json.loads((BASE / 'TripTailor_data_capture.json').read_text())
    candidates = collections.defaultdict(list); ambiguous_rows = []; counts = {}
    for filename, kind in [('attractions.csv', 'attraction'), ('accommodations.csv', 'accommodation'), ('restaurants.csv', 'restaurant')]:
        file = BASE / 'TripTailor_tables' / filename; digest = digest_file(file); scanned = 0; name_hits = 0
        with file.open(encoding='utf-8-sig', newline='') as stream:
            for ordinal, row in enumerate(csv.DictReader(stream), 1):
                scanned += 1; city = slugs.get(norm(row.get('city') or row.get('real_city')))
                if city is None: continue
                name = row.get('poiName') or row.get('name')
                options = alias_db.execute('SELECT entity_id,alias,raw_payload FROM names WHERE kind=? AND city=? AND name=?',
                                          (kind, city, norm(name))).fetchall()
                if not options: continue
                name_hits += 1
                try: lon, lat = float(row['longitude']), float(row['latitude'])
                except (TypeError, ValueError): continue
                if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90): continue
                converted = gcj02_to_wgs84(lon, lat); viable = {}
                for rid, alias, original in options:
                    r = records[rid]
                    distance = lambda x,y:111195 * math.hypot(y-r['data']['lat'], (x-r['data']['lon'])*math.cos(math.radians(y)))
                    distances = [distance(lon, lat), distance(*converted)]
                    if min(distances) <= 150: viable[rid] = (json.loads(alias), original, distances)
                if len(viable) != 1:
                    if len(viable) > 1: ambiguous_rows.append({'kind':kind,'source_row':ordinal,'name':name,'entity_candidates':list(viable)})
                    continue
                rid, (alias, original, distances) = next(iter(viable.items()))
                candidates[rid].append({'row':row,'ordinal':ordinal,'file':str(file.relative_to(ROOT)), 'file_sha256':digest,
                    'alias':alias,'original':original,'distances':distances})
        counts[kind] = {'scanned':scanned,'exact_alias_name_hits':name_hits}
    alias_db.close()
    sources, assertions, audit = [], [], []; skipped = 0
    for rid, options in candidates.items():
        if len(options) != 1:
            skipped += 1; audit.append({'entity_id':rid,'rejected':'multiple_historical_rows','count':len(options)}); continue
        option = options[0]; r = records[rid]; row = option['row']; kind = r['kind']; ordinal = option['ordinal']
        original_file = OUT / ('original_' + rid.removeprefix('overture:') + '.json')
        original_file.write_bytes(option['original'].encode())
        file = OUT / f'{kind}_{ordinal}.json'; raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',',':'))
        file.write_bytes(raw.encode()); sourceid = f'p17-triptailor:language_alias:{kind}:{ordinal}'
        basis = {'method':'literal_source_language_alias_city_unique_near_coordinate_candidate',
            'source_alias':option['alias'],'alias_evidence_file':str(original_file.relative_to(ROOT)),
            'alias_evidence_sha256':r['source_locator']['raw_sha256'],'original_source_locator':r['source_locator'],
            'distances_metres':option['distances'],'coordinate_system_unconfirmed':True,'entity_verified':False,
            'cross_provider_numeric_id_used':False,'row_and_entity_match_both_unique':True}
        sources.append({'source_id':sourceid,'source_url':capture['source_url'],'retrieved_at':capture['retrieved_at'],
            'observed_at':None,'source_published_at':None,'source_updated_at':None,
            'authority':'paper_author_released_historical_dataset','licence_status':'repository_licence_not_found_private_research_no_redistribution_claim',
            'representation':'saved_csv_row_serialized','content_file':file.name,'content_sha256':hashlib.sha256(raw.encode()).hexdigest(),
            'source_locator':{'csv_file':option['file'],'csv_sha256':option['file_sha256'],'csv_data_row_ordinal':ordinal,'kind':kind,
                'archive_sha256':capture['sha256'],'git_blob_sha1':capture['git_blob_sha1'],'archive_member_timestamp_is_not_fact_time':True}})
        def add(field, key, unit=None, scope=None):
            if row.get(key) in (None, ''): return
            quote = json.dumps({key:row[key]}, ensure_ascii=False, separators=(',',':'))[1:-1]
            assertions.append({'entity_id':rid,'field':field,'value':row[key],'unit':unit,'scope':scope or
                'Historical released dataset field only; source observation time and current applicability unknown.',
                'quote':quote,'source_id':sourceid,'identity_match_basis':basis,'status':'historical_paper_dataset_reference',
                'native_projection_permitted':False,'entity_verified':False})
        if kind == 'attraction':
            add('admission_reference','price','source_currency_not_explicit')
            add('opening_rules','opening_hours','local_clock_Asia/Shanghai')
            add('recommended_duration_text','reference_time','source_duration_text')
            add('experience_category_reference','tagNameList')
        elif kind == 'restaurant':
            add('average_price_reference','avg_price','source_average_per_person_currency_not_explicit')
            add('cuisine_reference','small_cate',scope='Historical publisher category; not current menu, allergy or dietary certification.')
        else:
            add('historical_average_nightly_price','avg_price','source_average_per_night_currency_not_explicit',
                'Historical average per night only, without stay dates, room, physical bed count or eligible rate plan.')
            add('hotel_segment_reference','small_cate')
        audit.append({'entity_id':rid,'name':r['name'],'city':r['city'],'kind':kind,'paper_name':row.get('poiName') or row.get('name'),**basis})
    report = {'created_at':utcnow(),'sources':sources,'assertions':assertions,'identity_audit':audit,
        'catalogue_basis':pointer,'network_requests':0,'new_entities':0,'source_clocks_refreshed':0,
        'matched_existing_entities':len(sources),'matched_by_kind':dict(collections.Counter(s['source_locator']['kind'] for s in sources)),
        'ambiguous_source_rows_rejected':ambiguous_rows,'ambiguous_entity_matches_rejected':skipped,
        'original_entities_bound':bound,'streamed_tables':counts,'currency_unconfirmed_no_native_price':True}
    (OUT / 'field_assertions.json').write_text(json.dumps(report, ensure_ascii=False, indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('matched_existing_entities','matched_by_kind','ambiguous_entity_matches_rejected','original_entities_bound','streamed_tables')}))


if __name__ == '__main__': main()
