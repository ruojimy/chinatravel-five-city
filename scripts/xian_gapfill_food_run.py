"""Gap-fill Xi'an restaurants (cuisine/opentime/endtime) and attractions (opentime/endtime).

One target name -> one public source lookup -> local raw artifact -> verbatim quote.

Sources (each capped at 100 live requests per domain, 2s min interval):
  ctrip : m.ctrip.com globalsearch (1 call) + food detail page (1 call)
  amap  : restapi.amap.com/v3/place/text?extensions=all (1 call)
  baidu : api.map.baidu.com/place/v2/search?scope=2   (1 call)

Identity: candidate accepted only when the normalised name matches AND the
candidate point is within 200 m of the catalog point. Catalog coordinates are
WGS-84 (verified: WGS84->GCJ02 conversion moves a sample from 463 m to 1 m), so
we test both datums and keep the smaller distance.

Usage:
  python scripts/xian_gapfill_food_run.py --kind restaurant --source ctrip --limit 20
  python scripts/xian_gapfill_food_run.py --kind attraction --source amap --limit 30
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import quote as urlquote

import requests

ROOT = Path(__file__).resolve().parents[1]
RUN = "results/xian_gapfill_20261109"
RAW_DIR = ROOT / RUN / "raw" / "food"
STAGE = ROOT / RUN / "staging" / "food" / "items.jsonl"
STATE = RAW_DIR / "_budget_state.json"
RUNLOG = ROOT / RUN / "staging" / "food" / "_run_log.jsonl"
OBSERVED_AT = "2026-11-09"
CITY = "西安"
CITY_ID_CTRIP = "10"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
DOMAIN_CAP = 100
MIN_INTERVAL = 2.0

# ---------------------------------------------------------------- geo helpers
A = 6378245.0
EE = 0.00669342162296594323


def _tl(x, y):
    r = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    r += (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
    r += (20 * math.sin(y * math.pi) + 40 * math.sin(y / 3 * math.pi)) * 2 / 3
    r += (160 * math.sin(y / 12 * math.pi) + 320 * math.sin(y * math.pi / 30)) * 2 / 3
    return r


def _tg(x, y):
    r = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    r += (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
    r += (20 * math.sin(x * math.pi) + 40 * math.sin(x / 3 * math.pi)) * 2 / 3
    r += (150 * math.sin(x / 12 * math.pi) + 300 * math.sin(x / 30 * math.pi)) * 2 / 3
    return r


def wgs2gcj(lat: float, lon: float) -> tuple[float, float]:
    dlat = _tl(lon - 105, lat - 35)
    dlon = _tg(lon - 105, lat - 35)
    rl = lat / 180 * math.pi
    m = 1 - EE * math.sin(rl) ** 2
    sm = math.sqrt(m)
    dlat = (dlat * 180) / ((A * (1 - EE)) / (m * sm) * math.pi)
    dlon = (dlon * 180) / (A / sm * math.cos(rl) * math.pi)
    return lat + dlat, lon + dlon


def hav(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371000
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(min(1.0, h)))


# ------------------------------------------------------------- name identity
def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").strip()


def split_name(name: str) -> tuple[str, str]:
    s = nfkc(name)
    m = re.search(r"[（(]([^（()）]*)[)）]\s*$", s)
    branch = nfkc(m.group(1)) if m else ""
    base = re.sub(r"\s*[（(][^（()）]*[)）]\s*$", "", s)
    base = re.sub(r"[\s·•\-—_]+", "", base)
    return base, re.sub(r"\s+", "", branch)


ADMIN_PREFIX = ("陕西省", "西安市", "陕西", "西安")


def strip_admin(base: str) -> str:
    for pref in ADMIN_PREFIX:
        if base.startswith(pref) and len(base) - len(pref) >= 4:
            return base[len(pref):]
    return base


def name_score(target: str, cand: str) -> int | None:
    """0 = full match, 1 = same base different/no branch, None = no match."""
    tb, tbr = split_name(target)
    cb, cbr = split_name(cand)
    tb, cb = strip_admin(tb), strip_admin(cb)
    if tb == cb and tbr == cbr:
        return 0
    if tb == cb:
        return 1
    # catalog base often carries a descriptor the platform drops (or vice versa)
    if tb and (tb in cb or cb in tb) and abs(len(tb) - len(cb)) <= 2:
        return 2
    return None


def point_distance(target_ll: tuple[float, float], cand_ll: tuple[float, float]) -> tuple[float, str]:
    d_gcj = hav(wgs2gcj(*target_ll), cand_ll)
    d_raw = hav(target_ll, cand_ll)
    if d_gcj <= d_raw:
        return d_gcj, "catalog_wgs84_to_gcj02"
    return d_raw, "catalog_already_gcj02"


# ------------------------------------------------------------------ hours
PAIR = re.compile(r"(\d{1,2})[:：](\d{2})\s*[-–—~至]\s*(\d{1,2})[:：](\d{2})")
DAY_PREFIX = re.compile(r"^\s*(?:周[一二三四五六日天末]\s*至\s*周[一二三四五六日天末]|每天|每日|周[一二三四五六日天])\s*")
ONLY_PAIRS = re.compile(r"^\d{1,2}[:：]\d{2}\s*[-–—~至]\s*\d{1,2}[:：]\d{2}"
                        r"(?:\s*[,，、;；]\s*\d{1,2}[:：]\d{2}\s*[-–—~至]\s*\d{1,2}[:：]\d{2})*$")


def parse_hours(text: str) -> dict | None:
    """Accept only a single clean day window (optionally split into services).

    Seasonal ("3月至10月"), holiday-override and 'open 24h' strings are rejected:
    a single opentime/endtime cannot represent them without inventing a value.
    """
    if not text:
        return None
    raw = re.sub(r"\s+", " ", str(text)).strip()
    if re.search(r"\d{1,2}\s*月|旺季|淡季|节假日|至\d{1,2}月", raw):
        return None
    core = DAY_PREFIX.sub("", raw).strip()
    if not ONLY_PAIRS.match(core):
        return None
    pairs = PAIR.findall(core)
    if not pairs:
        return None
    h1, m1 = int(pairs[0][0]), pairs[0][1]
    h2, m2 = int(pairs[-1][2]), pairs[-1][3]
    if h1 > 24 or h2 > 24:
        return None
    open_t = f"{h1:02d}:{m1}"
    end_raw = f"{h2:02d}:{m2}"
    if open_t == "00:00" and end_raw in ("00:00", "24:00"):
        return None  # 24h venue: no meaningful opening window
    if end_raw == "24:00":
        return None  # cannot be written as HH:MM without inventing a value
    if open_t == end_raw:
        return None
    return {"opentime": open_t, "endtime": end_raw, "quote": raw}


# ---------------------------------------------------------------- cuisine
GENERIC = {
    "中餐厅", "中餐馆", "餐厅", "餐馆", "餐饮", "餐饮服务", "美食", "小吃快餐", "快餐厅",
    "休闲餐饮", "其他", "其它", "综合", "地方菜", "特色菜", "美食;中餐厅", "中餐", "饭馆",
    "food", "restaurant",
}
EXTRA_CUISINE = {
    "火锅", "烧烤", "烤肉", "涮肉", "铜锅涮肉", "面馆", "凉皮", "肉夹馍", "泡馍", "清真",
    "茶餐厅", "西餐", "咖啡", "甜品", "披萨", "汉堡", "料理", "日式料理", "韩式料理",
    "串串", "麻辣烫", "卤味", "饺子", "包子", "米线", "螺蛳粉", "海鲜", "酸菜鱼", "铁板烧",
    "自助餐", "小吃", "陕菜", "西北菜", "川菜", "粤菜", "湘菜", "东北菜", "本帮菜",
}
CUISINE_RE = re.compile(r"^[\u4e00-\u9fa5]{1,4}菜$")


def clean_cuisine(raw: str) -> str | None:
    v = nfkc(raw).strip(" ;,，、|")
    if not v or v in GENERIC:
        return None
    if v in EXTRA_CUISINE or CUISINE_RE.match(v):
        return v
    return None


def pick_cuisine(candidates: list[str]) -> str | None:
    for c in candidates:
        got = clean_cuisine(c)
        if got:
            return got
    return None


# ---------------------------------------------------------------- transport
class Budget:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def spend(self, domain: str) -> bool:
        row = self.data.setdefault(domain, {"calls": 0, "last": 0.0})
        if row["calls"] >= DOMAIN_CAP:
            return False
        wait = MIN_INTERVAL - (time.time() - row["last"])
        if wait > 0:
            time.sleep(wait)
        row["calls"] += 1
        row["last"] = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        return True

    def left(self, domain: str) -> int:
        return DOMAIN_CAP - self.data.get(domain, {}).get("calls", 0)


def get(domain: str, url: str, budget: Budget, *, params=None, headers=None, timeout=25):
    if not budget.spend(domain):
        return None, {"error": "budget_exhausted", "domain": domain}
    try:
        r = requests.get(url, params=params, headers=headers or {"User-Agent": UA,
                                                               "Accept-Language": "zh-CN,zh;q=0.9"},
                         timeout=timeout, allow_redirects=True)
        return r, {"status": r.status_code, "bytes": len(r.content),
                   "final_url": r.url}
    except Exception as exc:
        return None, {"error": type(exc).__name__, "detail": str(exc)[:200]}


def slug(name: str) -> str:
    h = hashlib.sha256(name.encode("utf-8")).hexdigest()[:10]
    return re.sub(r"[^\w\u4e00-\u9fa5]+", "_", name)[:40] + "_" + h


# ------------------------------------------------------------------ sources
def lookup_ctrip(name: str, budget: Budget, raw_dir: Path, target_ll=None):
    """returns (candidate dict, meta) or (None, meta)"""
    q = urlquote(f"{CITY}{name}")
    url = f"https://m.ctrip.com/restapi/h5api/globalsearch/search?action=json&keyword={q}"
    r, meta = get("m.ctrip.com", url, budget, headers={"User-Agent": MOBILE_UA})
    if r is None or r.status_code != 200:
        return None, meta
    try:
        payload = r.json()
    except Exception:
        return None, {**meta, "error": "non_json"}
    items = [d for d in (payload.get("data") or []) if d.get("type") == "food"]
    meta["n_candidates"] = len(items)
    if not items:
        return None, {**meta, "error": "no_food_result"}
    best, best_score, best_d, best_datum = None, None, None, None
    for it in items[:8]:
        sc = name_score(name, it.get("word") or "")
        if sc is None:
            continue
        dist, datum = 1e9, "no_target_coord"
        if target_ll and it.get("lat") and it.get("lon"):
            dist, datum = point_distance(target_ll, (it["lat"], it["lon"]))
        elif sc != 0:
            continue
        if sc == 1 and dist > 200:
            continue
        if sc == 2 and dist > 150:
            continue
        if sc == 0 and dist > 200:
            continue
        if best_score is None or (sc, dist) < (best_score, best_d):
            best, best_score, best_d, best_datum = it, sc, dist, datum
    if best is None:
        return None, {**meta, "error": "no_name_match"}
    district = best.get("districtId") or 7
    detail_url = f"https://m.ctrip.com/webapp/gourmet/food/fooddetail/{district}/{best['id']}.html"
    r2, meta2 = get("m.ctrip.com", detail_url, budget, headers={"User-Agent": MOBILE_UA})
    if r2 is None or r2.status_code != 200:
        return None, {**meta2, "error": "detail_failed", "detail_url": detail_url}
    html = r2.text
    out = raw_dir / f"{slug(name)}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r2.content)
    hours = None
    m = re.search(r'restTagDesc">([^<]{3,80})</span>', html)
    if m:
        hours = parse_hours(m.group(1))
    if hours is None:
        m = re.search(r'"WeekdayDtoList":(\[.*?\])\s*,\s*"', html, re.S)
        if m:
            try:
                wd = json.loads(m.group(1))
                opens = [f"{int(x['StartTime'].split(':')[0]):02d}:{x['StartTime'].split(':')[1]}"
                         for x in wd if x.get("StartTime")]
                ends = [f"{int(x['EndTime'].split(':')[0]):02d}:{x['EndTime'].split(':')[1]}"
                        for x in wd if x.get("EndTime")]
                if opens and ends:
                    hours = {"opentime": opens[0], "endtime": ends[0],
                             "quote": f"周一至周日 {opens[0]}-{ends[0]}"}
            except Exception:
                hours = None
    cuisines = re.findall(r'"Cuisine":\[\{"Id":\d+,"Name":"([^"]+)"', html)
    if not cuisines:
        cuisines = re.findall(r'averagePrice">([^<]{2,10})</span>', html)
    cuisine = pick_cuisine(cuisines)
    if hours and hours["quote"] not in re.sub(r"\s+", " ", html).replace("&nbsp;", " "):
        hours = None  # quote must be reproducible from this raw file
    return {
        "name_on_source": best.get("word"),
        "lat": best.get("lat"), "lon": best.get("lon"),
        "hours": hours, "cuisine": cuisine,
        "url": detail_url, "publisher": "携程", "authority": "travel_marketplace_display",
        "raw": out, "identity": best_score,
        "distance_m": None if best_d is None or best_d > 1e8 else round(best_d),
        "datum": best_datum,
    }, {**meta, **meta2, "ok": True}


def lookup_amap(name: str, budget: Budget, raw_dir: Path, target_ll=None, poi_types="050000"):
    params = {"key": open(ROOT / ".secrets/amap.key").read().strip(),
              "keywords": strip_admin(split_name(name)[0]),
              "offset": 10, "page": 1, "extensions": "all"}
    if target_ll:  # around search: branch-level results near the catalog point
        glat, glon = wgs2gcj(*target_ll)
        params.update({"location": f"{glon:.6f},{glat:.6f}", "radius": 1500, "sortrule": "distance"})
        url = "https://restapi.amap.com/v3/place/around"
    else:
        params.update({"city": CITY, "citylimit": "true"})
        url = "https://restapi.amap.com/v3/place/text"
    if poi_types:
        params["types"] = poi_types
    r, meta = get("restapi.amap.com", url, budget, params=params)
    if r is None or r.status_code != 200:
        return None, meta
    try:
        payload = r.json()
    except Exception:
        return None, {**meta, "error": "non_json"}
    if payload.get("status") != "1":
        return None, {**meta, "error": "amap_status_" + str(payload.get("info"))}
    pois = payload.get("pois") or []
    meta["n_candidates"] = len(pois)
    best, best_score, best_dist, best_datum = None, None, None, None
    for p in pois:
        try:
            lon, lat = [float(x) for x in p["location"].split(",")]
        except Exception:
            continue
        sc = name_score(name, p.get("name") or "")
        if sc is None:
            continue
        dist, datum = (1e9, "no_target_coord")
        if target_ll:
            dist, datum = point_distance(target_ll, (lat, lon))
        elif sc != 0:
            continue
        if sc == 1 and dist > 200:
            continue
        if sc == 2 and dist > 150:
            continue
        if sc == 0 and dist > 200:
            continue
        if best_score is None or (sc, dist) < (best_score, best_dist):
            best, best_score, best_dist, best_datum = p, sc, dist, datum
    if best is None:
        return None, {**meta, "error": "no_name_match"}
    out = raw_dir / f"{slug(name)}.amap.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"query": params["keywords"], "target": name,
                               "poi": best, "response_count": payload.get("count")},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    ext = best.get("biz_ext") or {}
    hours = None
    for key in ("opentime2", "open_time"):
        if ext.get(key):
            hours = parse_hours(ext[key])
            if hours:
                break
    tpath = [x for x in (best.get("type") or "").split(";") if x]
    cuisine = pick_cuisine(list(reversed(tpath)))
    if not hours and not cuisine:
        return None, {**meta, "error": "no_hours_no_cuisine"}
    return {
        "name_on_source": best.get("name"),
        "lat": float(best["location"].split(",")[1]),
        "lon": float(best["location"].split(",")[0]),
        "hours": hours, "cuisine": cuisine, "address": best.get("address"),
        "url": ("https://www.amap.com/place/" + str(best.get("id"))),
        "publisher": "高德地图", "authority": "map_poi_display",
        "raw": out, "identity": best_score, "distance_m": round(best_dist),
        "datum": best_datum,
    }, {**meta, "ok": True}


def lookup_baidu(name: str, budget: Budget, raw_dir: Path, target_ll=None, query_type=None):
    sys.path.insert(0, str(ROOT / "src"))
    from shorttrip.dynamic.baidu import (load_credentials, sign_variants, HOST, SEARCH_V2,
                                        bd09_to_gcj02, gcj02_to_bd09)
    params = {"query": strip_admin(split_name(name)[0]), "region": CITY,
              "city_limit": "true", "page_size": 10, "page_num": 0, "scope": 2,
              "output": "json"}
    if target_ll:  # circular search near the catalog point (baidu expects bd09ll)
        glat, glon = wgs2gcj(*target_ll)
        blat, blon = gcj02_to_bd09(glat, glon)
        params.update({"location": f"{blat:.6f},{blon:.6f}", "radius": 1500})
    if query_type:
        params["tag"] = query_type
    if not budget.spend("api.map.baidu.com"):
        return None, {"error": "budget_exhausted"}
    try:
        creds = load_credentials(ROOT / ".secrets/baidu.key")
        qt = dict(params, ak=creds.ak)
        best = None
        chunk = None
        body = {}
        for style in ("md5_urlenc", "md5_raw"):
            sn = sign_variants(SEARCH_V2, qt, creds.sk).get(style)
            q = dict(qt, sn=sn)
            r = requests.get(HOST + SEARCH_V2, params=q, timeout=25,
                             headers={"User-Agent": "ShortTripAssistant/1.0 (course project; POI verification)"})
            body = r.json()
            if body.get("status") == 0:
                chunk = body
                break
        if chunk is None:
            return None, {"error": "baidu_status", "body": str(body)[:200]}
    except Exception as exc:
        return None, {"error": type(exc).__name__, "detail": str(exc)[:200]}
    results = chunk.get("results") or []
    for p in results:
        sc = name_score(name, p.get("name") or "")
        if sc is None:
            continue
        loc = p.get("location") or {}
        dist, datum = 1e9, "no_target_coord"
        if target_ll and loc.get("lat"):
            lng, lat = bd09_to_gcj02(float(loc["lng"]), float(loc["lat"]))
            dist, datum = point_distance(target_ll, (lat, lng))
            datum = "baidu_bd09_to_gcj02+" + datum
        elif sc != 0:
            continue
        if sc == 1 and dist > 200:
            continue
        if sc == 2 and dist > 150:
            continue
        if sc == 0 and dist > 200:
            continue
        if best is None or (sc, dist) < (best[0], best[1]):
            best = (sc, dist, datum, p)
    if best is None:
        return None, {"error": "no_name_match", "n_candidates": len(results)}
    sc, dist, datum, p = best
    out = raw_dir / f"{slug(name)}.baidu.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"query": params["query"], "target": name, "poi": p},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    info = p.get("detail_info") or {}
    hours = parse_hours(str(info.get("shop_hours") or ""))
    tags = []
    for key in ("classified_poi_tag", "label", "tag"):
        tags += [x for x in re.split(r"[;,、|]", str(info.get(key) or "")) if x]
    cuisine = pick_cuisine(tags)
    if not hours and not cuisine:
        return None, {"error": "no_hours_no_cuisine"}
    return {
        "name_on_source": p.get("name"),
        "lat": (p.get("location") or {}).get("lat"),
        "lon": (p.get("location") or {}).get("lng"),
        "hours": hours, "cuisine": cuisine, "address": p.get("address"),
        "url": f"https://api.map.baidu.com/place/v2/detail?uid={p.get('uid')}&output=html",
        "publisher": "百度地图", "authority": "map_poi_display",
        "raw": out, "identity": sc, "distance_m": round(dist), "datum": datum,
    }, {"ok": True, "n_candidates": len(results)}


# ------------------------------------------------------------------- driver
def load_done() -> set[tuple[str, str]]:
    done = set()
    if STAGE.exists():
        for line in STAGE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                it = json.loads(line)
                done.add((it["kind"], it["name"]))
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["restaurant", "attraction"], required=True)
    ap.add_argument("--source", choices=["ctrip", "amap", "baidu"], required=True)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    target_csv = ROOT / RUN / "targets" / f"{args.kind}_missing.csv"
    rows = list(csv.DictReader(open(target_csv, encoding="utf-8-sig")))
    done = load_done()
    tried = set()
    if RUNLOG.exists():
        for line in RUNLOG.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                tried.add((rec.get("source"), rec.get("name")))
    rows = [r for r in rows if (args.kind, r["name"]) not in done
            and (args.source, r["name"]) not in tried]
    rows = [r for r in rows if r["lat"] and r["lon"]][args.offset:]
    if args.kind == "attraction":
        # ticketed sites publish hours; parks/streets/squares mostly do not
        def prio(r):
            n = r["name"]
            good = sum(w in n for w in ("博物馆", "博物院", "纪念馆", "遗址", "景区", "寺", "庙",
                                        "宫", "陵", "塔", "楼", "馆", "园", "苑", "观", "城"))
            bad = sum(w in n for w in ("公园", "广场", "街区", "市场", "停车场", "小区"))
            return (bad - good * 2, -len(r["missing"]))
        rows.sort(key=prio)
    else:
        # prefer rows missing the whole trio
        rows.sort(key=lambda r: -len(r["missing"].split(",")))
    budget = Budget(STATE)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    STAGE.parent.mkdir(parents=True, exist_ok=True)
    stats = Counter()
    seen = 0
    for row in rows:
        if seen >= args.limit:
            break
        name = row["name"]
        ll = (float(row["lat"]), float(row["lon"])) if row["lat"] else None
        missing = [m.strip() for m in row["missing"].split(",")]
        if args.source == "ctrip":
            if budget.left("m.ctrip.com") < 2:
                stats["budget_stop"] += 1
                break
            cand, meta = lookup_ctrip(name, budget, RAW_DIR, ll)
        elif args.source == "amap":
            if budget.left("restapi.amap.com") < 1:
                stats["budget_stop"] += 1
                break
            poi_types = "050000" if args.kind == "restaurant" else ""
            cand, meta = lookup_amap(name, budget, RAW_DIR, ll, poi_types)
        else:
            if budget.left("api.map.baidu.com") < 1:
                stats["budget_stop"] += 1
                break
            cand, meta = lookup_baidu(name, budget, RAW_DIR, ll)
        seen += 1
        if not cand:
            stats["fail_" + str(meta.get("error"))] += 1
            RUNLOG.parent.mkdir(parents=True, exist_ok=True)
            with open(RUNLOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"name": name, "source": args.source, "ok": False,
                                     **meta}, ensure_ascii=False) + "\n")
            continue
        data = {}
        if "opentime" in missing and cand.get("hours"):
            data["opentime"] = cand["hours"]["opentime"]
            data["endtime"] = cand["hours"]["endtime"]
            quote = cand["hours"]["quote"]
        elif "endtime" in missing and cand.get("hours"):
            data["endtime"] = cand["hours"]["endtime"]
            quote = cand["hours"]["quote"]
        else:
            quote = ""
        if args.kind == "restaurant" and "cuisine" in missing and cand.get("cuisine"):
            data["cuisine"] = cand["cuisine"]
            if not quote:
                quote = cand["cuisine"]
        if not data:
            stats["fail_no_usable_field"] += 1
            with open(RUNLOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"name": name, "source": args.source,
                                     "error": "no_usable_field", **meta, "ok": False},
                                    ensure_ascii=False) + "\n")
            continue
        rel_raw = str(cand["raw"].relative_to(ROOT)).replace("\\", "/")
        identity = f"name+coord<={int(cand.get('distance_m') or 0)}m" if cand.get("distance_m") is not None else "name exact on source"
        item = {
            "kind": args.kind,
            "name": name,
            "data": data,
            "source": {"url": cand["url"], "publisher": cand["publisher"],
                       "authority": cand["authority"],
                       "licence_status": "public_page_reuse_unverified",
                       "observed_at": OBSERVED_AT},
            "evidence": {"raw_path": rel_raw, "quote": quote, "locator": "poi info",
                         "identity_basis": identity},
            "notes": {"name_on_source": cand.get("name_on_source"),
                      "source_distance_m": cand.get("distance_m"),
                      "datum": cand.get("datum")},
        }
        with open(STAGE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
        stats["ok"] += 1
        with open(RUNLOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"name": name, "source": args.source, "ok": True,
                                 "fields": list(data), "distance_m": cand.get("distance_m"),
                                 "name_on_source": cand.get("name_on_source")},
                                ensure_ascii=False) + "\n")
        if stats["ok"] % 25 == 0:
            print(json.dumps({"checkpoint": stats["ok"]}, ensure_ascii=False), flush=True)
    print(json.dumps({"attempted": seen, "stats": dict(stats),
                      "budget": {d: budget.left(d) for d in ("m.ctrip.com", "restapi.amap.com",
                                                             "api.map.baidu.com")}},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
