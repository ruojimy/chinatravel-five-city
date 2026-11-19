"""Shared catalog fields for the V20 sandbox adapter and native scorer."""
from functools import lru_cache
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
ATTRACTION_ALIASES = {
    '博物馆': '博物馆/纪念馆', '纪念馆': '博物馆/纪念馆', 'history_museum': '博物馆/纪念馆',
    '美术馆': '美术馆/艺术馆', '艺术馆': '美术馆/艺术馆',
}
CUISINE_ALIASES = {
    '陕菜': '陕西菜', '湖南菜': '湘菜', '四川菜': '川菜', '福建菜': '闽菜',
    '广东菜': '粤菜', '韩国菜': '韩国料理', '日本菜': '日本料理',
}
RESTAURANT_GENERIC = {'中餐', '中餐厅', '西餐', '餐饮相关场所', '特色/地方风味餐厅',
                      '餐厅', '自助餐', '私房菜', '购物相关场所', '农副产品'}
ATTRACTION_GENERIC = {'旅游景点', '风景名胜', '公园广场', '国家级景点', '省级景点', '休闲场所',
                      '科教文化场所'}


@lru_cache(maxsize=1)
def evidence():
    return json.loads((ROOT / 'classification_evidence.json').read_text(encoding='utf8'))


def category_value(label):
    return ATTRACTION_ALIASES.get(label, label)


def cuisine_value(label):
    return CUISINE_ALIASES.get(label, label)


def normalize(kind, city, record_id, name, data):
    """Use values after V19 source-masking, before computing eligibility."""
    patch = evidence()['patches'].get(record_id)
    if patch and patch['name'] != name:
        raise ValueError(f'Source identity changed for {record_id}')
    changed_fields = {}
    if patch:
        for key, value in patch.get('fields', {}).items():
            if data.get(key) is None:
                data[key] = changed_fields[key] = value
    if kind not in ('attraction', 'restaurant'):
        return {'evidence': patch, 'filled_fields': changed_fields} if patch else None
    key = 'type' if kind == 'attraction' else 'cuisine'
    original = data.get(key)
    labels = list((patch or {}).get('labels', []))
    mapped_codes = {}
    if kind == 'attraction' and city in ('西安', '厦门') and isinstance(original, str) and re.fullmatch(
            r'\d{6}(?:\s*\|\s*\d{6})*', original):
        taxonomy = evidence()['taxonomy']
        for code in re.split(r'\s*\|\s*', original):
            parts = taxonomy['codes'].get(code)
            if parts:
                mapped_codes[code] = parts
                if code.startswith(('11', '14', '08')):
                    labels.append(parts[-1])
    elif isinstance(original, str):
        labels.append(original)
    canonical = category_value if kind == 'attraction' else cuisine_value
    values = list(dict.fromkeys(canonical(label) for label in labels))
    data['category_values' if kind == 'attraction' else 'cuisine_values'] = values
    if values and (original is None or mapped_codes or (patch and kind == 'restaurant' and original in RESTAURANT_GENERIC)):
        data[key] = values[0]
        if data[key] != original:
            changed_fields[key] = data[key]
    broad = ATTRACTION_GENERIC if kind == 'attraction' else RESTAURANT_GENERIC
    return {'field': key, 'original_value': original, 'values': values,
            'status': 'specific' if set(values) - broad else 'broad' if values else 'unknown',
            'mapped_codes': mapped_codes, 'taxonomy_source': evidence()['taxonomy']['source'] if mapped_codes else None,
            'evidence': patch, 'filled_fields': changed_fields}


@lru_cache(maxsize=1)
def dated():
    return json.loads((ROOT / 'dated_transport.json').read_text(encoding='utf8'))['observations']


def transport_observations(origin, destination, mode, travel_date, seat_code):
    """Return explicitly date-scoped observations outside V19's priced records."""
    if not travel_date:
        return []
    seats = {'O': '二等座', 'M': '一等座', '1': '硬座', '3': '硬卧', '4': '软卧'}
    return [{**row, 'status': 'date_scoped_display_observation', 'strict_budget_eligible': False}
            for row in dated()
            if (row['origin'], row['destination'], row['departure'][:10]) == (origin, destination, travel_date)
            and mode in ('any', row['mode'])
            and (row['mode'] == 'airplane' or seat_code is None or row['seat'] == seats.get(seat_code, seat_code))]
