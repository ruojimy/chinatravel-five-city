"""Exact, evidence-backed place relationships and secondary attraction types."""
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def evidence():
    path = Path(__file__).resolve().parents[3] / 'runtime/grounded_places.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def attraction_types(activity, city, primary):
    name = activity.get('position')
    values = {primary} if primary else set()
    values.update(row['category'] for row in evidence().get('secondary_types', [])
                  if row['city'] == city and row['name'] == name)
    return values


def visit_names(city, kind, position):
    registered = {position}
    registered.update(row['name'] for row in evidence().get('visit_relations', [])
                      if (row['city'], row['kind'], row['position']) == (city, kind, position))
    return registered


def registered_visit(city, kind, position, target):
    return target in visit_names(city, kind, position)


def is_registered_target(city, kind, target):
    return any((r['city'], r['kind'], r['name']) == (city, kind, target)
               for r in evidence().get('visit_relations', []))
