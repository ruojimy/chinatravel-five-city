"""Read-only planning tools over a specified repaired expanded sandbox.

No online retrieval is performed. Unknown or estimated values remain unknown;
the source row and any mapped aliases are retained in the returned provenance.
"""
from __future__ import annotations
import argparse
import csv
from functools import lru_cache
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import sys

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
import dynamic_runtime
import catalog_completion
import benchmark12_catalog as repaired_catalog
REPOSITORY = BASE.parents[1]
ROOTS = {'G3': Path(os.environ.get('CT_SANDBOX_ENGINE_ROOT', REPOSITORY / 'ShortTrip-upstream'))}
CITIES = {'北京':'beijing','上海':'shanghai','南京':'nanjing','苏州':'suzhou','杭州':'hangzhou',
          '深圳':'shenzhen','成都':'chengdu','武汉':'wuhan','广州':'guangzhou','重庆':'chongqing','西安':'xian'}
if os.environ.get('CHINATRAVEL_PROFILE') == 'expanded12':
    CITIES['厦门'] = 'xiamen'
FOLDERS = {'attraction':'attractions','restaurant':'restaurants','accommodation':'accommodations'}
NUMERIC = {'lat','lon','price','recommendmintime','recommendmaxtime','numbed','Cost','Duration'}
SIGNATURE = {'attraction':('lat','lon','price','opentime','endtime','recommendmintime','recommendmaxtime'),
             'restaurant':('lat','lon','price','opentime','endtime'),
             'accommodation':('lat','lon','price','numbed')}
_MISSING = {'', 'none', 'null', 'nan', 'unknown', '需确认', '-1', '-1.0'}

def _scalar(value):
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value

def _clean_numeric(value):
    if value is None or str(value).strip().lower() in _MISSING:
        return None
    try:
        n = float(value)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(n) or n < 0:
        return None
    return int(n) if n.is_integer() else n

def _clean_row(row):
    return {k: (_clean_numeric(v) if k in NUMERIC else
                None if v is None or str(v).strip().lower() in _MISSING else _scalar(v))
            for k,v in row.items()}

def _signature(kind, row):
    result = []
    for key in SIGNATURE[kind]:
        value = row.get(key)
        if key in NUMERIC:
            value = _clean_numeric(value)
            if key in ('lat', 'lon') and value is not None:
                value = round(float(value), 7)
        result.append(value)
    # Without both coordinates, do not guess that two named records coincide.
    return tuple(result) if result[0] is not None and result[1] is not None else None

def _time_valid(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,2}:\d{2}', value):
        return False
    h, m = map(int, value.split(':'))
    return (0 <= h < 24 and 0 <= m < 60) or (h == 24 and m == 0)

@lru_cache(maxsize=None)
def _sha(path):
    return sha256(path.read_bytes()).hexdigest()

def _activate(root):
    """Each CLI invocation imports only its selected copy, never frozen originals."""
    selected = str(root.resolve())
    for name in list(sys.modules):
        if name == 'chinatravel' or name.startswith('chinatravel.'):
            del sys.modules[name]
    sys.path.insert(0, selected)

@lru_cache(maxsize=None)
def _native_crosswalk(kind, slug):
    """Only pair translations linked by the same ID in both frozen native files."""
    folder = FOLDERS[kind]
    name = f'restaurants_{slug}.csv' if kind == 'restaurant' else folder + '.csv'
    evidence = BASE / 'alias_evidence'
    cn = evidence / 'database' / folder / slug / name
    en = evidence / 'database_en' / folder / slug / name
    if not cn.is_file() or not en.is_file():
        return {}
    with cn.open(encoding='utf-8-sig', newline='') as stream:
        chinese = list(csv.DictReader(stream))
    with en.open(encoding='utf-8-sig', newline='') as stream:
        english = list(csv.DictReader(stream))
    by_id = {}
    for row in chinese:
        by_id.setdefault(row.get('id'), []).append(row)
    result = {}
    for foreign in english:
        matches = by_id.get(foreign.get('id'), [])
        if len(matches) != 1 or _signature(kind, foreign) is None:
            continue
        native = matches[0]
        if _signature(kind, native) != _signature(kind, foreign):
            continue
        result.setdefault((foreign.get('name'), _signature(kind,foreign)), []).append(
            {'name':native.get('name'), 'native_id':native.get('id'),
             'source_zh_sha256':_sha(cn), 'source_en_sha256':_sha(en)})
    return result

@lru_cache(maxsize=1)
def _xian_grade_evidence():
    path = BASE / 'xian_grade_evidence_v3.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None

def _xiamen_binding_matches(kind, row, bindings, poi_names):
    if row.get('name') not in poi_names: return False
    item = bindings.get(f"{kind}:{row.get('id')}")
    if not item or item.get('name') != row.get('name') or item.get('coordinate_system') != 'WGS84': return False
    try: return float(row.get('lat')) == float(item['source_position'][0]) and float(row.get('lon')) == float(item['source_position'][1])
    except (TypeError, ValueError, KeyError, IndexError): return False


class Sandbox:
    def __init__(self, arm):
        arm = str(arm).upper()
        if arm not in ROOTS:
            raise ValueError('this runtime exposes the configured G3 sandbox')
        self.arm, self.root = arm, ROOTS[arm].resolve()
        db = os.environ.get('CHINATRAVEL_DATABASE_ROOT')
        if not db:
            raise ValueError('G3 requires an explicit CHINATRAVEL_DATABASE_ROOT')
        self.db = Path(db).resolve()
        self.cities = {k:v for k,v in CITIES.items() if arm == 'G3' or v != 'xian'}

    def _file(self, kind, city):
        if kind not in FOLDERS or city not in self.cities:
            raise ValueError('unsupported kind or city')
        if city == '厦门' and os.environ.get('CHINATRAVEL_PROFILE') == 'expanded12' and os.environ.get('CT_XIAMEN_DISCOVERY_ONLY') != '1':
            raise NotImplementedError('Xiamen entity data is unknown in the intercity-only expanded12 profile')
        slug = self.cities[city]
        basename = f'restaurants_{slug}.csv' if kind == 'restaurant' else FOLDERS[kind] + '.csv'
        return self.db / FOLDERS[kind] / slug / basename

    @lru_cache(maxsize=None)
    def _catalog(self, kind, city):
        path = self._file(kind, city)
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        poi_path = self.db / 'poi' / self.cities[city] / 'poi.json'
        pois = {x.get('name') for x in json.loads(poi_path.read_text(encoding='utf-8-sig')) if x.get('name')}
        bindings = {}
        if city == '厦门' and os.environ.get('CT_XIAMEN_DISCOVERY_ONLY') == '1':
            binding_path = poi_path.with_name('poi_bindings.json')
            bindings = json.loads(binding_path.read_text(encoding='utf-8-sig')) if binding_path.is_file() else {}
        def bound_source(i, row):
            if city != '厦门' or os.environ.get('CT_XIAMEN_DISCOVERY_ONLY') != '1': return row.get('name') in pois
            return _xiamen_binding_matches(kind, row, bindings, pois)
        exact = [(i,r) for i,r in enumerate(rows) if bound_source(i,r)]
        exact_row_indices = {i for i,_ in exact}
        bysig = {}
        for i, row in exact:
            key = _signature(kind, row)
            if key is not None:
                bysig.setdefault((row.get('name'),key), []).append(i)
        crosswalk = _native_crosswalk(kind, self.cities[city])
        aliases, alias_to_index, unresolved = {}, {}, []
        for i, row in enumerate(rows):
            if i in exact_row_indices:
                continue
            candidates = crosswalk.get((row.get('name'), _signature(kind,row)), [])
            matching = [(i, candidate) for candidate in candidates
                        for i in bysig.get((candidate['name'], _signature(kind,row)), [])]
            if len(matching) == 1:
                canonical, evidence = matching[0]
                aliases.setdefault(canonical, []).append({'name':row.get('name'), 'source_id':row.get('id'),
                                                           'source_row_index':i,
                                                           'evidence':'same_native_source_id_and_selected_fields',
                                                           'native_name':evidence['name'],
                                                           'native_id':evidence['native_id'],
                                                           'source_zh_sha256':evidence['source_zh_sha256'],
                                                           'source_en_sha256':evidence['source_en_sha256']})
                alias_to_index[i] = canonical
            else:
                unresolved.append(i)
        return path, poi_path, rows, exact, aliases, alias_to_index, unresolved

    @lru_cache(maxsize=None)
    def _exact_indices(self, kind, city):
        return frozenset(i for i, _ in self._catalog(kind,city)[3])

    def _record(self, kind, city, row_index):
        path, poi_path, rows, exact, aliases, alias_map, unresolved = self._catalog(kind, city)
        requested_index = row_index
        row_index = alias_map.get(row_index, row_index)
        row = rows[row_index]
        data = _clean_row(row)
        grade_info = None
        recovered = None
        if self.arm == 'G3' and city == '西安':
            evidence = _xian_grade_evidence()
            section = evidence['kinds'][kind] if evidence else None
            if section and section['csv_sha256'] == _sha(path):
                grade_info = section['records'].get(str(row.get('id')))
                if not grade_info and kind == 'accommodation':
                    recovered = dynamic_runtime.recovered_lodging_grade(str(row.get('id')), row.get('name'), _sha(path))
                    if recovered:
                        grade_info = {'grade':'L3', 'source_record_id':recovered['source_record_id'],
                                      'graded_at':None, 'non_source_fields':{},
                                      'identity_basis':'unique exact name and original coordinate; historical grade only'}
        non_source = grade_info.get('non_source_fields', {}) if grade_info else {}
        reference_fields = {}
        for field, field_status in non_source.items():
            if field in data and data[field] is not None:
                reference_fields[field] = {'value':data[field], 'status':field_status}
                data[field] = None
        record_id = f"{kind}:{self.cities[city]}:{row.get('id', '')}"
        dynamic_fields = dynamic_runtime.entity_overlay(record_id,city,row.get('name'),_sha(path))
        if dynamic_fields:
            for field,value in dynamic_fields.get('fields',{}).items():
                # Do not overwrite a still-known source value; in case of a
                # conflict retain the source and make the new observation visible.
                if data.get(field) is None:
                    data[field] = value
        completion = catalog_completion.normalize(kind, city, record_id, row.get('name'), data)
        poi_ok = row_index in self._exact_indices(kind,city)
        # Structural P0 check uses source row existence; non-source coordinates
        # are separately masked below and require a dynamic lookup before routing.
        raw_lat, raw_lon = _clean_numeric(row.get('lat')), _clean_numeric(row.get('lon'))
        lat, lon = _clean_numeric(data.get('lat')), _clean_numeric(data.get('lon'))
        raw_position_ok = (raw_lat is not None and raw_lon is not None and -90 <= raw_lat <= 90
                           and -180 <= raw_lon <= 180 and not (raw_lat == 0 and raw_lon == 0))
        effective_position_ok = (lat is not None and lon is not None and -90 <= lat <= 90
                                 and -180 <= lon <= 180 and not (lat == 0 and lon == 0))
        position_ok = raw_position_ok or effective_position_ok
        if city == '厦门' and os.environ.get('CT_XIAMEN_DISCOVERY_ONLY') == '1':
            position_ok = bool(poi_ok and raw_position_ok)
        time_ok = kind == 'accommodation' or (_time_valid(data.get('opentime')) and _time_valid(data.get('endtime')))
        xiamen_grade = repaired_catalog.grade(self.db, kind, path, row) if city == '厦门' else None
        grade_record = xiamen_grade or grade_info
        grade = grade_record['grade'] if grade_record else 'unknown_not_reconstructed'
        # L2/L3 may enter the main path only after required positional fields are
        # actually available. Derived coordinates remain reference until a
        # dynamic provider verifies them; this frozen adapter cannot do that.
        verified_position = effective_position_ok and (city != '厦门' or os.environ.get('CT_XIAMEN_DISCOVERY_ONLY') != '1' or poi_ok)
        coordinate_basis = 'historical_static_reference; live freshness unknown' if city == '厦门' and os.environ.get('CT_XIAMEN_DISCOVERY_ONLY') == '1' else 'source_profile'
        source_status = str(row.get('price_status') or '').strip().lower()
        price_reference = (reference_fields.get('price') or {}).get('value')
        if source_status.startswith('estimated'):
            price_reference = _clean_numeric(row.get('price'))
            if (dynamic_fields and 'price' in dynamic_fields.get('fields',{})
                    and dynamic_fields.get('field_provenance',{}).get('price')=='dated_room_occupancy_matched_source'):
                data['price'] = _clean_numeric(dynamic_fields['fields']['price'])
            else:
                data['price'] = None
        required_missing = []
        for field in ('lat','lon'):
            if data.get(field) is None:
                required_missing.append(field)
        if not position_ok and not any(k in required_missing for k in ('lat','lon')):
            required_missing.append('valid_position')
        if kind != 'accommodation':
            for field in ('opentime','endtime'):
                if not _time_valid(data.get(field)):
                    required_missing.append(field)
        if not poi_ok:
            required_missing.append('poi_name_link')
        if data.get('price') is None:
            required_missing.append('price')
        if kind == 'attraction':
            lo, hi = data.get('recommendmintime'), data.get('recommendmaxtime')
            if lo is None or lo <= 0:
                required_missing.append('recommendmintime')
            if hi is None or hi <= 0 or (lo is not None and hi < lo):
                required_missing.append('recommendmaxtime')
        if kind == 'accommodation' and (data.get('numbed') is None or data['numbed'] <= 0):
            required_missing.append('numbed')
        # The approved tier policy separates *visibility* from whether every
        # field needed for a particular itinerary is already resolved. P3
        # attraction price and recommended duration must not hide an otherwise
        # accessible entity; preserve missing values rather than inventing them.
        main = bool(poi_ok and position_ok and time_ok and grade != 'L4')
        unknown = [k for k,v in data.items() if v is None]
        dynamic_price = dynamic_runtime.price_overlay(record_id,city,row.get('name')) if kind == 'attraction' else None
        if dynamic_price is not None and data.get('price') is None:
            data['price'] = dynamic_price['price']
            required_missing = [field for field in required_missing if field != 'price']
            unknown = [field for field in unknown if field != 'price']
        access_mode = 'live' if os.environ.get('CT_DYNAMIC_MODE','snapshot')=='live' else 'snapshot_replay'
        status = {'main_path':main, 'position_complete':position_ok, 'time_complete':time_ok,
                  'poi_name_match':poi_ok, 'grade':'unknown_not_reconstructed',
                  'dynamic_lookup':'not_triggered_by_directory_browsing',
                  'provider_state':access_mode,
                  'unknown_fields':unknown, 'price_usable_for_static_budget':data.get('price') is not None,
                  'estimated_price_reference':price_reference,
                  'price_source_status':source_status or 'not_exposed_by_frozen_csv',
                  'qualification_boundary':'P0/P1 checks only; original L1-L4 provenance and live freshness are not established.'}
        if completion:
            status['catalog_completion'] = completion
        status['grade'] = grade
        status['planning_position_available'] = verified_position
        # A known point can be discovered or used as a waypoint while its visit
        # hours remain unknown. The scheduler still consumes only main_path.
        status['catalog_discoverable'] = main or (city == '厦门' and verified_position)
        status['needs_time_evidence'] = kind != 'accommodation' and not time_ok
        if xiamen_grade:
            status['grade_source_record_id'] = xiamen_grade['source_record_id']
            status['historical_grade_fields'] = xiamen_grade['field_status']
        area_hours = repaired_catalog.places(self.db)['public_area_hours'].get(str(row['id']))
        if city == '厦门' and kind == 'attraction' and area_hours:
            status['public_area_hours_evidence'] = area_hours
        if city == '厦门' and os.environ.get('CT_XIAMEN_DISCOVERY_ONLY') == '1':
            status['position_basis'] = 'historical_static_reference'
            status['position_freshness'] = 'unknown'
        status['planning_required_missing'] = required_missing
        status['visibility_policy'] = 'approved_P0_P1_tier; missing_P2_P3_visible_as_unknown'
        status['plan_readiness'] = 'needs_field_resolution' if required_missing else 'static_fields_present'
        status['price_assumption'] = 'not_applied_before_actual_search'
        status['grade_as_of'] = grade_info.get('graded_at') if grade_info else None
        status['dynamic_required_by_grade'] = grade in ('L2','L3')
        status['dynamic_provider_wired_in_this_adapter'] = True
        status['dynamic_mode'] = access_mode
        status['non_source_fields'] = non_source
        status['reference_fields'] = reference_fields
        status['dynamic_field_evidence'] = dynamic_fields
        if dynamic_price is not None:
            status['price_evidence'] = dynamic_price
            status['price_assumption'] = dynamic_price['status']
            status['price_usable_for_static_budget'] = True
            status['qualification_boundary'] = 'Dynamic price is conditional or user assumption, not verified for travel date.'
        if kind == 'accommodation' and source_status == 'historical_source_reference_conditional':
            status['price_source_status'] = source_status
            status['qualification_boundary'] += ' Historical displayed price or starting-price reference; unit, room and eligibility may be unspecified; current price unknown.'
            status['historical_price_context'] = {k: row.get(k) for k in ('historical_price_evidence_id','historical_price_source_url','historical_price_observed_at','historical_price_checkin','historical_price_checkout','historical_price_scope','historical_price_unit_status','historical_price_confidence_interval','numbed_source_status')}
            status['dynamic_required_by_grade'] = True
            status['dynamic_provider_wired_in_this_adapter'] = False
        if row.get('opening_segments_status') == 'historical_source_reference_freshness_unknown':
            status['historical_segmented_hours'] = True
            status['dynamic_required_by_grade'] = True
            status['dynamic_provider_wired_in_this_adapter'] = False
            status['qualification_boundary'] += ' Historical segmented hours have unknown freshness; a new date-specific lookup is required.'
        if grade_info:
            status['grade_source_record_id'] = grade_info.get('source_record_id')
            status['grade_identity_basis'] = grade_info.get('identity_basis')
            status['qualification_boundary'] = ('Historical v17 grade joined on unique name and matching P0/P1/P2; '
                                                'live freshness and dynamic retrieval are not established.')
            if recovered:
                status['qualification_boundary'] = ('Historical L3 recovered using unique name and coordinate; '
                    'the historical grade does not verify the newer price or travel dates.')
                status['recovered_price_evidence'] = recovered['subsequent_provenance_matches']
            if dynamic_price is not None:
                status['qualification_boundary'] += (' Price is a source reference without trip date or a user-authorized '
                                                     'zero assumption; it is not verified for travel date.')
        if dynamic_fields:
            status['qualification_boundary'] += (' Amap-matched fields are sourced observations with the declared '
                                                 'coordinate system; the route tool remains a static benchmark estimate.')
        payload = {'schema_version':'repaired-expanded-csv-v1','language':'zh','kind':kind,
                   'record_id':record_id,'source_id':f'{self.arm}_repaired_static_copy',
                   'city':city,'name':row.get('name'),'data':data,'access':status,
                   'aliases':aliases.get(row_index,[]) + repaired_catalog.aliases_for_row(self.db, city, kind, row),
                   'source_updated_at':None,
                   'freshness_status':'static_benchmark_snapshot','needs_live_verification':True,
                   'source_locator':{'file':str(path),'file_sha256':_sha(path),
                                     'row_index_0based':row_index,'poi_file_sha256':_sha(poi_path)},
                   'notice':'Static benchmark only. Unknown and estimated fields are not verified facts.'}
        if requested_index != row_index:
            payload['requested_alias'] = {'name':rows[requested_index].get('name'),
                                          'source_id':rows[requested_index].get('id'),
                                          'source_row_index':requested_index}
        return {'record_id':record_id,'kind':kind,'city':city,'name':row.get('name'),
                'payload':payload,'evidence_status':'benchmark_only','source_updated_at':None,
                'needs_live_verification':True}

    @lru_cache(maxsize=None)
    def _eligible(self, kind, city):
        _, _, _, exact, _, _, _ = self._catalog(kind, city)
        result = []
        for i, _ in exact:
            item = self._record(kind,city,i)
            if item['payload']['access']['main_path']:
                result.append((i,item))
        return result

    @lru_cache(maxsize=None)
    def _discoverable(self, kind, city):
        ready = self._eligible(kind, city)
        if city != '厦门':
            return ready
        ready_indices = {index for index, _ in ready}
        pending = []
        for index, _ in self._catalog(kind, city)[3]:
            if index not in ready_indices:
                record = self._record(kind, city, index)
                if record['payload']['access']['catalog_discoverable']:
                    pending.append((index, record))
        return ready + pending

    def catalog_list(self, kind, city, limit=20, offset=0):
        path, _, rows, exact, aliases, alias_map, unresolved = self._catalog(kind,city)
        items = self._discoverable(kind,city)
        limit, offset = max(1,min(int(limit),100)), max(0,int(offset))
        return {'records':[x for _,x in items[offset:offset+limit]],'returned':len(items[offset:offset+limit]),
                'catalog_total':len(items),'source_row_count':len(rows),'exact_poi_rows':len(exact),
                'aliased_rows':len(alias_map),'unresolved_rows':len(unresolved),
                'main_excluded_policy':len(exact)-len(self._eligible(kind,city)),
                'planning_catalog_total':len(self._eligible(kind,city)), 'offset':offset,
                'next_offset':offset+limit if offset+limit<len(items) else None,
                'snapshot':f'{self.arm} repaired static CSV','dynamic_lookup_performed':False}

    def catalog_search(self, kind, city, text='', limit=20, offset=0, *, category=None, cuisine=None):
        if (category is not None and kind != 'attraction') or (cuisine is not None and kind != 'restaurant'):
            raise ValueError('Category is for attractions and cuisine is for restaurants')
        needle = str(text).strip().casefold()
        hits = [record for _,record in self._discoverable(kind,city)
                if needle in json.dumps(record,ensure_ascii=False).casefold()]
        hits.sort(key=lambda record: repaired_catalog.search_order(record, needle))
        alias = repaired_catalog.city_aliases(self.db, city, kind).get(str(text).strip())
        if alias and all(item['name'] != alias['name'] for item in hits):
            reference = self.catalog_entity(f"{kind}:{self.cities[city]}:{alias['record_id']}")
            hits.insert(0, reference)
        if category is not None:
            value = catalog_completion.category_value(category)
            hits = [r for r in hits if value in r.get('payload', {}).get('data', {}).get('category_values', [])]
        if cuisine is not None:
            value = catalog_completion.cuisine_value(cuisine)
            hits = [r for r in hits if value in r.get('payload', {}).get('data', {}).get('cuisine_values', [])]
        limit, offset = max(1,min(int(limit),100)), max(0,int(offset))
        return {'records':hits[offset:offset+limit],'returned':len(hits[offset:offset+limit]),
                'match_total':len(hits),'offset':offset,'next_offset':offset+limit if offset+limit<len(hits) else None,
                'snapshot':f'{self.arm} repaired static CSV','dynamic_lookup_performed':False}

    def catalog_entity(self, record_id):
        try:
            kind, slug, num = record_id.split(':',2)
            city = next(k for k,v in self.cities.items() if v == slug)
        except (ValueError, StopIteration) as exc:
            raise KeyError(record_id) from exc
        _, _, rows, _, _, _, _ = self._catalog(kind,city)
        for i,row in enumerate(rows):
            if str(row.get('id')) == num:
                item = self._record(kind,city,i)
                if not item['payload']['access']['catalog_discoverable']:
                    access = item['payload']['access']
                    result = {'record_id':record_id,'status':'reference_only',
                            'name':item['name'], 'missing_fields':access['planning_required_missing'],
                            'position_available':access['planning_position_available'],
                            'poi_name_match':access['poi_name_match'],'grade':access['grade'],
                            'dynamic_needed':True,'dynamic_lookup':'not_run_frozen_sandbox',
                            'notice':'Reference identity only; values are not exposed to planning.'}
                    result['aliases'] = item['payload']['aliases']
                    completion = access.get('catalog_completion', {}).get('evidence')
                    if completion:
                        result['source_reference'] = completion
                    if access.get('historical_price_context'):
                        result['historical_price_reference'] = {'value':item['payload']['data'].get('price'),
                            'context':access['historical_price_context'], 'current_price':'unknown'}
                    return result
                event = dynamic_runtime.entity_access(item['payload'])
                item['payload']['access']['dynamic_access'] = event
                item['payload']['access']['dynamic_lookup'] = ('not_required' if not event.get('triggered') else
                    'snapshot_replayed' if event.get('mode') == 'frozen_snapshot_replay' else
                    'live_' + str(event.get('status','unknown')))
                return item
        raise KeyError(record_id)

    def reference_search(self, kind, city, text, limit=20, offset=0):
        """Find excluded identities without releasing unusable numeric facts."""
        needle = str(text).strip().casefold()
        if not needle:
            raise ValueError('a nonempty name is required')
        _, _, rows, _, _, _, _ = self._catalog(kind,city)
        hits = []
        for i,row in enumerate(rows):
            matching_aliases = repaired_catalog.aliases_for_row(self.db, city, kind, row)
            if not any(needle in name.casefold() for name in [row['name'], *(a['name'] for a in matching_aliases)]):
                continue
            item = self._record(kind,city,i)
            access = item['payload']['access']
            if not access['main_path']:
                hits.append({'record_id':f"{kind}:{self.cities[city]}:{row.get('id','')}",
                             'name':row.get('name'),'status':'reference_only',
                             'missing_fields':access['planning_required_missing'],
                             'position_available':access['planning_position_available'],
                             'poi_name_match':access['poi_name_match'],'grade':access['grade'],
                             'dynamic_needed':True,'dynamic_lookup':'not_run_frozen_sandbox'})
                if access.get('historical_price_context'):
                    hits[-1]['historical_price_reference'] = {'value':item['payload']['data'].get('price'),
                        'context':access['historical_price_context'], 'current_price':'unknown'}
        limit, offset = max(1,min(int(limit),100)), max(0,int(offset))
        result = {'records':hits[offset:offset+limit], 'returned':len(hits[offset:offset+limit]),
                'match_total':len(hits),'offset':offset,
                'next_offset':offset+limit if offset+limit<len(hits) else None,
                'notice':'Reference identities and missing fields.'}
        if city == '厦门' and any(name in needle for name in ('鼓浪屿', '轮渡', '三丘田', '东渡')):
            result['transport_references'] = [self.ferry_reference(city)]
        return result

    def ferry_reference(self, city='厦门'):
        return dict(repaired_catalog.places(self.db)['ferry_reference']) if city == '厦门' else None

    def catalog_preflight(self, record_id):
        item = self.catalog_entity(record_id)
        if item.get('status') == 'reference_only':
            return {'record_id':record_id,'structural_ok':False,'status':'reference_only',
                    'source_freshness':'static_benchmark_snapshot','needs_live_verification':True}
        access = item['payload']['access']
        return {'record_id':item['record_id'],'structural_ok':access['main_path'],
                'status':'conditional_unknown' if (access['planning_required_missing'] or access['dynamic_required_by_grade'])
                         else 'static_structurally_available',
                'access':access,'source_freshness':'static_benchmark_snapshot','needs_live_verification':True}

    def intercity_search(self, from_city, to_city, mode='any', travel_date=None, seat_code=None):
        if from_city not in self.cities or to_city not in self.cities:
            raise ValueError('unsupported city')
        if mode not in ('any','train','airplane'):
            raise ValueError('mode must be any, train or airplane')
        if from_city == to_city:
            return {'records':[],'returned':0,'errors':['origin equals destination']}
        _activate(self.root)
        from chinatravel.environment.tools.intercity_transport.apis import IntercityTransport
        api = IntercityTransport(lang='zh')
        out, references, conditional_records, errors = [], [], [], []
        for m in ([mode] if mode != 'any' else ['train','airplane']):
            try:
                unfiltered = api._select(from_city,to_city,m,travel_date=travel_date,seat_code=seat_code)
                frame = api.select(from_city,to_city,m,travel_date=travel_date,seat_code=seat_code)
                if isinstance(frame,str):
                    errors.append(frame); continue
                eligible_indices = set(frame.index)
                for source_index, source_row in unfiltered.iterrows():
                    if source_index in eligible_indices:
                        continue
                    raw = {k:_scalar(v) for k,v in source_row.to_dict().items()}
                    data = _clean_row(raw)
                    needed = []
                    for key in ('From','To','Cost','Duration'):
                        if data.get(key) is None or (key == 'Duration' and data[key] <= 0):
                            needed.append(key)
                    for key in ('BeginTime','EndTime'):
                        if not _time_valid(data.get(key)):
                            needed.append(key)
                    if not needed:
                        needed.append('departure_schedule')
                    ident = data.get('TrainID') if m == 'train' else data.get('FlightID')
                    references.append({'mode':m,'name':ident,'from':data.get('From'),'to':data.get('To'),
                                       'status':'reference_only','missing_fields':needed,
                                       'dynamic_needed':True,'dynamic_lookup':'not_run_frozen_sandbox'})
                    conditional_records.append({'mode':m,'name':ident,'data':data,
                                                'status':'visible_but_fields_unresolved',
                                                'missing_fields':needed,
                                                'notice':'Known fields remain visible; missing fields cannot be used as verified values.'})
                for index, row in frame.reset_index(drop=True).iterrows():
                    raw = {k:_scalar(v) for k,v in row.to_dict().items()}
                    data = _clean_row(raw)
                    ident = data.get('TrainID') if m == 'train' else data.get('FlightID')
                    unknown = [k for k in ('From','To','BeginTime','EndTime','Duration','Cost') if data.get(k) is None]
                    rid = f'{m}:{index}:{ident}'
                    payload = {'schema_version':'repaired-expanded-transport-v1','language':'zh',
                               'kind':'train' if m=='train' else 'flight','record_id':rid,'name':ident,
                               'data':data,'unknown_fields':unknown,'static_budget_eligible':data.get('Cost') is not None,
                               'dynamic_lookup':'not_run_frozen_sandbox','source_updated_at':None,
                               'freshness_status':'static_benchmark_snapshot','needs_live_verification':True,
                               'notice':'Airport display names come from FromName/ToName where present; Original columns preserve source codes.'}
                    if m == 'train':
                        from chinatravel.environment.station_aliases import station_alias_info
                        payload['station_aliases'] = {
                            'from': station_alias_info(self.root,from_city,data.get('From')),
                            'to': station_alias_info(self.root,to_city,data.get('To'))}
                        dynamic_train = dynamic_runtime.direct_train(from_city,to_city,data)
                        if dynamic_train is not None:
                            payload['dynamic_train_evidence'] = dynamic_train
                            payload['freshness_status'] = 'dynamic_observation_no_trip_date'
                            payload['notice'] = 'Direct train and seat fare from Amap; query travel date and actual seat availability remain unknown.'
                    overlay_path = BASE.parent / 'data_integration/amap_overlay_audit_20261115.json'
                    if overlay_path.is_file() and m == 'train':
                        overlay = json.loads(overlay_path.read_text(encoding='utf-8'))
                        matched = [x for x in overlay.get('applied',[]) if x['train_id']==ident
                                   and x['from']==data.get('From') and x['to']==data.get('To')
                                   and x['departure']==data.get('BeginTime') and x['arrival']==data.get('EndTime')]
                        if len(matched)==1:
                            payload['dynamic_price_evidence'] = matched[0]
                            payload['freshness_status'] = 'dynamic_observation_no_trip_date'
                            payload['notice'] = ('Price is a dynamically observed seat reference; no trip date '
                                                 'or actual seat availability was supplied or verified.')
                    if m == 'train' and data.get('CostSource') == '12306_historical_benchmark_reference':
                        payload['freshness_status'] = 'historical_conditional_benchmark'
                        payload['static_budget_eligible'] = False
                        payload['historical_benchmark_budget_eligible'] = True
                        payload['notice'] = 'Historical 12306 published fare for the recorded date/seat, used only as an undated conditional benchmark reference. Actual trip date, fare, sale and availability are unknown.'
                    if m == 'train' and data.get('CostSource') in ('12306_official_published_reference','12306_official_display_observed'):
                        payload['freshness_status'] = 'dated_display_observation' if data.get('CostSource') == '12306_official_display_observed' else 'dated_published_fare_reference'
                        payload['notice'] = ('12306 published reference and possibly a seat/price observation at a recorded time; '
                                             'current availability and actual purchase price remain unknown.')
                        payload['static_budget_eligible'] = False
                        payload['published_fare_budget_reference'] = True
                    out.append({'mode':m,'record':{'record_id':rid,'kind':payload['kind'],'city':'',
                                'name':ident,'payload':payload,'evidence_status':'benchmark_only',
                                'source_updated_at':None,'needs_live_verification':True}})
            except Exception as exc:
                errors.append(f'{m}: {type(exc).__name__}: {exc}')
        if mode in ('any','airplane') and travel_date and os.environ.get('CT_FLIGHT_REFERENCE_ROOT'):
            try:
                for item in api.reference_flights(from_city, to_city, travel_date):
                    references.append({'mode':'airplane', **item})
            except Exception as exc:
                errors.append(f'airplane reference: {type(exc).__name__}: {exc}')
        return {'records':out,'returned':len(out),'reference_records':references,
                'conditional_records':conditional_records,'conditional_total':len(conditional_records),
                'reference_total':len(references),'source':f'{self.arm} repaired static transport API',
                'dated_observations':catalog_completion.transport_observations(
                    from_city, to_city, mode, travel_date, seat_code),
                'errors':errors,'dynamic_lookup_performed':False,'real_world_availability':False,
                'dynamic_access':dynamic_runtime.transport_access(from_city,to_city,mode)}

    def goto(self, city, start, end, mode, departure, people_number=1, day=None):
        if city not in self.cities:
            raise ValueError('unsupported city')
        original = {'start': start, 'end': end}
        start, end = (repaired_catalog.resolve_endpoint(self, city, value) for value in (start, end))
        if not start or not end:
            return {'city': city, **original, 'available': False, 'legs': [],
                    'error': 'Use an exact catalog name or a routable record_id from this city.'}
        result = self._goto(city, start, end, mode, departure, people_number, day=day)
        if (start, end) != (original['start'], original['end']):
            result['requested_endpoints'] = original
        if city == '厦门' and 'Gulangyu water crossing' in (result.get('error') or ''):
            result['transport_references'] = [self.ferry_reference(city)]
        return result

    def _goto(self, city, start, end, mode, departure, people_number, *, day=None):
        if self.arm == 'G3' and city == '西安':
            # A named POI whose coordinates are explicitly derived cannot be
            # silently promoted to a verified route without dynamic retrieval.
            evidence = _xian_grade_evidence() or {}
            for section in evidence.get('kinds', {}).values():
                for info in section.get('records', {}).values():
                    if info['name'] in (start,end) and any(
                            key in info.get('non_source_fields', {}) for key in ('lat','lon')):
                        # A verified field overlay can replace an earlier derived
                        # location; everything else remains blocked for routing.
                        hits=[x for x in dynamic_runtime.load_snapshot().get('entity_overlays',[])
                              if x['city']==city and x['name']==info['name']
                              and {'lat','lon'} <= set(x.get('fields',{}))
                              and dynamic_runtime.entity_overlay(x['record_id'],city,info['name'],
                                  _sha(self._file(x['record_id'].split(':')[0],city)))]
                        if len(hits)==1:
                            continue
                        return {'city':city,'start':start,'end':end,'mode':mode,'departure':departure,
                                'available':False,'legs':[],
                                'error':'Endpoint coordinates require dynamic verification; provider not wired.',
                                'source':f'{self.arm} access gate','real_world_route_proof':False}
        _activate(self.root)
        from chinatravel.environment.tools.transportation.apis import Transportation
        from chinatravel.symbol_verification.local_route_replay import frozen_route, route_day
        evidence = None
        try:
            with route_day(day):
                result = Transportation(lang='zh').goto(city,start,end,departure,mode)
                evidence = frozen_route(city, start, end, mode, departure)
            if isinstance(result, str):
                legs, error = [], result
            elif isinstance(result, list) and all(isinstance(x,dict) for x in result):
                legs, error = result, None
            else:
                legs, error = [], f'Unexpected route result type: {type(result).__name__}'
        except Exception as exc:
            legs, error = [], f'{type(exc).__name__}: {exc}'
        if not isinstance(people_number,int) or isinstance(people_number,bool) or people_number<1:
            raise ValueError('people_number must be a positive integer')
        # Emit the exact schema-ready route and party multiplicities, while
        # retaining the native unit amount for audit and checker replay.
        prepared=[]
        for leg in legs:
            leg=dict(leg);unit=leg['cost'];leg['price']=unit
            if leg.get('mode')=='metro':
                leg['tickets']=people_number;leg['cost']=unit*people_number
            elif leg.get('mode')=='taxi':
                leg['cars']=(people_number+3)//4;leg['cost']=unit*leg['cars']
            else:leg['cost']=0
            prepared.append(leg)
        dated = {}
        if evidence and prepared:
            dated = {'source': 'Amap dated public-transit estimate',
                     'route_scope': 'exact endpoints and supplied Asia/Shanghai departure',
                     'departure_at': evidence['departure_at'], 'evidence_id': evidence['evidence_id']}
        return {'city':city,'start':start,'end':end,'mode':mode,'departure':departure,
                'people_number':people_number,'available':bool(prepared),'legs':prepared,'error':error,
                'source':f'{self.arm} static graph-distance Transportation.goto',
                'route_scope':'offline topology and estimated time/fare, not real-world route proof',
                'real_world_route_proof':False, **dated}

TOOLS = ('catalog_list','catalog_search','catalog_entity','catalog_preflight','reference_search','intercity_search','goto')
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--arm', choices=sorted(ROOTS), required=True)
    parser.add_argument('tool', choices=TOOLS)
    parser.add_argument('--args-json', required=True)
    args = parser.parse_args()
    result = getattr(Sandbox(args.arm),args.tool)(**json.loads(args.args_json))
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
