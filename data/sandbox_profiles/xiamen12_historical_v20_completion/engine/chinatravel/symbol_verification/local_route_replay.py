"""Use the exact recorded map quote for the same endpoints and departure."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, timedelta
from functools import lru_cache
import json
import os
from pathlib import Path

_DAY = ContextVar('map_departure_day', default=None)


@contextmanager
def route_day(day):
    token = _DAY.set(day)
    try:
        yield
    finally:
        _DAY.reset(token)


@lru_cache(maxsize=1)
def map_evidence():
    path = Path(__file__).resolve().parents[3] / 'runtime/local_access.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def frozen_route(city, start, end, mode, departure):
    start_date = os.environ.get('CT_TRAVEL_START_DATE') or os.environ.get('CT_LOCAL_ROUTE_TRIAL_START_DATE')
    day = _DAY.get()
    if not start_date or type(day) is not int or day < 1:
        return None
    travel_day = date.fromisoformat(start_date) + timedelta(days=day - 1)
    hits = [r for r in map_evidence().get('routes', [])
            if (city, start, end, mode, departure)
            == tuple(r[k] for k in ('city', 'start', 'end', 'mode', 'departure'))
            and r['departure_at'][:10] == travel_day.isoformat()]
    if len(hits) > 1:
        raise ValueError('Ambiguous map route quote')
    return hits[0] if hits else None


def meal_open(city, name, start, end):
    poi = map_evidence().get('restaurant') or {}
    if (city, name) != (poi.get('city'), poi.get('name')):
        return None
    return any(opens <= start < end <= closes for opens, closes in poi['agreed_opening_windows'])
