"""Shared helpers for the P31 five-city 96-task experiment."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/p31_five_city_96"
CST = timezone(timedelta(hours=8))


def known(v):
    return v is not None and v != ""


def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def hhmm_to_min(s):
    if not known(s):
        return None
    s = str(s).strip()
    if s in ("24:00", "24:00:00"):
        return 24 * 60
    try:
        h, m = s.split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def min_to_hhmm(m):
    m = int(round(m))
    return f"{m // 60:02d}:{m % 60:02d}"


def parse_window(open_s, close_s):
    """Return (open_min, close_min) or None. Supports 00:00-24:00."""
    a, b = hhmm_to_min(open_s), hhmm_to_min(close_s)
    if a is None or b is None or b <= a:
        return None
    return a, b


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _gcj_offset(lat, lon):
    a = 6378245.0
    ee = 0.00669342162296594323

    def tf_lat(x, y):
        r = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
        r += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        r += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
        r += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
        return r

    def tf_lon(x, y):
        r = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        r += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        r += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
        r += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
        return r

    dlat = tf_lat(lon - 105.0, lat - 35.0)
    dlon = tf_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlon = (dlon * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    return lat + dlat, lon + dlon


def wgs84_to_gcj02(lat, lon):
    return _gcj_offset(float(lat), float(lon))


def entity_coord(cand):
    """Return (lat, lon, system) from a task candidate dict."""
    d = cand.get("data") or {}
    lat, lon = d.get("lat"), d.get("lon")
    if not (known(lat) and known(lon)):
        return None
    return float(lat), float(lon), cand.get("coordinate_system") or "unknown"


def parse_amap_hours(text):
    """Parse common Amap business.opentime strings into windows (minutes)."""
    if not known(text):
        return None
    t = str(text).strip()
    if "24" in t and ("小时" in t or "全天" in t):
        return (0, 24 * 60)
    if "全天" in t or "24小时" in t:
        return (0, 24 * 60)
    import re
    wins = []
    for m in re.finditer(r"(\d{1,2}):(\d{2})\s*[-–—至]\s*(\d{1,2}):(\d{2})", t):
        a = int(m.group(1)) * 60 + int(m.group(2))
        b = int(m.group(3)) * 60 + int(m.group(4))
        if b > a:
            wins.append((a, b))
    if wins:
        return (min(w[0] for w in wins), max(w[1] for w in wins))
    return None


def departure_iso(date_str, hhmm):
    return f"{date_str}T{hhmm}:00+08:00"


def load_tasks(level=None):
    if level:
        return read_json(OUT / "tasks" / f"{level}.json")
    return read_json(OUT / "tasks/all_96.json")
