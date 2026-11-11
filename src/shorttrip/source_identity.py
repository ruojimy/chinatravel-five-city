"""Use only literal, unqualified language names from preserved place rows."""
from .business_archives import normalize_name
import hashlib, json, math
from pathlib import Path


def language_aliases(row):
    """Never use brand-level, regional-perspective or time-qualified aliases."""
    names = row.get('names') or {}
    result = {}
    primary = names.get('primary')
    if isinstance(primary, str) and primary.strip():
        result[normalize_name(primary)] = {'value': primary, 'locator': '/names/primary'}
    for index, rule in enumerate(names.get('rules') or []):
        if (rule.get('variant') != 'language' or not rule.get('language')
                or any(rule.get(key) for key in ('perspectives', 'between', 'side'))):
            continue
        value = rule.get('value')
        if isinstance(value, str) and normalize_name(value):
            result.setdefault(normalize_name(value), {
                'value': value, 'locator': f'/names/rules/{index}/value',
                'language': rule['language'],
            })
    return result


def verify_historical_identity(row, record, basis, root):
    """Recheck literal names and geography, never numeric provider namespaces."""
    method = basis.get('method')
    label = normalize_name(row.get('poiName') or row.get('name'))
    if method == 'exact_name_city_unique_near_coordinate_candidate':
        aliases = {normalize_name(record['name']), normalize_name(record['data'].get('hotelname_en'))}
        if label not in aliases: raise ValueError('Historical row name mismatch')
    elif method == 'literal_source_language_alias_city_unique_near_coordinate_candidate':
        path = (Path(root) / basis['alias_evidence_file']).resolve()
        if not path.is_relative_to((Path(root) / 'results/p17_continuous').resolve()):
            raise ValueError('Alias evidence outside retained captures')
        raw = path.read_bytes(); original = json.loads(raw)
        digest = hashlib.sha256(raw).hexdigest()
        if (digest != record['source_locator']['raw_sha256'] or digest != basis['alias_evidence_sha256']
                or original['id'] != record['record_id'].removeprefix('overture:')
                or original['names']['primary'] != record['name']):
            raise ValueError('Alias evidence is bound to another entity')
        if language_aliases(original).get(label) != basis['source_alias']:
            raise ValueError('Historical alias is not a literal source language name')
    else:
        raise ValueError('Unapproved historical identity method')
    if record.get('city_slug') and normalize_name(row.get('city') or row.get('real_city')) != normalize_name(record['city_slug']):
        raise ValueError('Historical city mismatch')
    from .dynamic.opendata import gcj02_to_wgs84
    lon, lat = float(row['longitude']), float(row['latitude'])
    if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError('Historical coordinates invalid')
    converted = gcj02_to_wgs84(lon, lat)
    distance = lambda x,y:111195 * math.hypot(y-record['data']['lat'], (x-record['data']['lon'])*math.cos(math.radians(y)))
    distances = [distance(lon, lat), distance(*converted)]
    if not all(math.isfinite(d) for d in distances) or min(distances) > 150:
        raise ValueError('Historical row location mismatch')
    return {'coordinate_system_unconfirmed': True, 'entity_verified': False}
