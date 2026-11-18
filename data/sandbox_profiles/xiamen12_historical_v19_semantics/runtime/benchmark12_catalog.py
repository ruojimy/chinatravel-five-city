"""Catalog evidence helpers installed alongside the repaired sandbox adapter."""
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path


@lru_cache(maxsize=None)
def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def places(db):
    return _read(db.parent / 'benchmark12_evidence/places.json')


@lru_cache(maxsize=None)
def city_aliases(db, city, kind):
    return {alias: item for alias, item in places(db)['aliases'].get(city, {}).items()
            if item['kind'] == kind}


def grade(db, kind, csv_path, row):
    section = _read(db.parent / 'benchmark12_evidence/xiamen_grades.json')['kinds'][kind]
    if section['csv_sha256'] != csv_digest(csv_path):
        return None
    item = section['records'].get(row['id'])
    return item if item and item['name'] == row['name'] else None


@lru_cache(maxsize=None)
def csv_digest(path):
    return sha256(path.read_bytes()).hexdigest()


def aliases_for_row(db, city, kind, row):
    return [{'name': alias, 'source_url': item['source'], 'evidence': 'profile_curated_name'}
            for alias, item in city_aliases(db, city, kind).items()
            if (item['name'], item['record_id']) == (row['name'], row['id'])]


def resolve_endpoint(sandbox, city, value):
    """Resolve only pinned aliases and routable catalog IDs."""
    if not isinstance(value, str) or not value.strip():
        return None
    if value.split(':', 1)[0] in ('attraction', 'restaurant', 'accommodation') and ':' in value:
        # Location checks must not trigger a second dynamic provider request.
        parts = value.split(':', 2)
        if len(parts) != 3 or parts[1] != sandbox.cities[city]:
            return None
        _, _, rows, _, _, _, _ = sandbox._catalog(parts[0], city)
        indexes = [i for i, row in enumerate(rows) if row['id'] == parts[2]]
        if len(indexes) != 1:
            return None
        item = sandbox._record(parts[0], city, indexes[0])
        if not item['payload']['access']['planning_position_available']:
            return None
        return item['name']
    alias = places(sandbox.db)['aliases'].get(city, {}).get(value)
    return alias['name'] if alias else value


def search_order(record, needle):
    name = record['name'].casefold()
    aliases = {alias['name'].casefold() for alias in record['payload']['aliases']}
    return (0 if name == needle or needle in aliases else
            1 if name.startswith(needle) else 2 if needle in name else 3)
