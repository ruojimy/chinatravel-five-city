"""High-throughput field refill for Xi'an records.

One API call can return 20-25 POIs with business fields. This script:
  * queries Amap v5/place/text (show_fields=business) and Baidu
    place/v2/search (scope=2) across category x keyword grids,
  * persists every raw response byte with a unique filename,
  * matches a returned POI to a catalog record ONLY by exact normalized name
    or by name similarity + <=200m coordinate identity (GCJ02/BD09 -> WGS84),
  * emits an --enrich jsonl where quote is verbatim in that raw response.

Nothing is guessed: ambiguous or 24:00 hours are skipped, and only fields
that are currently null are proposed. xian_ingest.py / xian_verify.py remain
the only gates.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from shorttrip.expansion_contract import FIELDS, OPTIONAL_VALUES  # noqa: E402
from shorttrip.dynamic.baidu import load_credentials, sign  # noqa: E402
from xian_api_collect import bd09_to_wgs84, gcj02_to_wgs84  # noqa: E402

TIME_RE = re.compile(r"(\d{2}:\d{2})-(\d{2}:\d{2})")
TAG_RE = re.compile(r"<[^>]+>")
DISTRICTS = ["碑林区", "莲湖区", "雁塔区", "新城区", "未央区", "长安区",
             "灞桥区", "临潼区", "阎良区", "高陵区", "鄠邑区", "蓝田县", "周至县"]
GRID = {
    "attraction": {
        "types": "110000",
        "keywords": ["景点", "景区", "公园", "博物馆", "纪念馆", "寺庙", "遗址",
                     "古迹", "文化园", "旅游区", "自然保护区", "古镇", "城墙", "塔"],
    },
    "restaurant": {
        "types": "050000",
        "keywords": ["陕菜", "面馆", "小吃", "火锅", "烧烤", "清真", "川菜",
                     "粤菜", "家常菜", "快餐", "海鲜", "西餐", "咖啡", "甜品"],
    },
    "accommodation": {
        "types": "100000",
        "keywords": ["酒店", "宾馆", "民宿", "客栈", "公寓", "旅馆", "度假",
                     "商务酒店", "连锁酒店", "青年旅舍", "温泉", "会议酒店"],
    },
}
AUTH = {
    "amap": ("https://restapi.amap.com/v5/place/text", "高德开放平台",
             "amap_place_api", "provider_terms_pending_review", "provider_listing"),
    "baidu": ("https://api.map.baidu.com/place/v2/search", "百度地图开放平台",
              "baidu_place_api", "api_terms", "provider_listing"),
}


def norm(text: str) -> str:
    text = (text or "").replace("（", "(").replace("）", ")").replace("－", "-").replace("—", "-")
    return re.sub(r"\s+", "", text).lower()


def haversine(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return round(2 * r * math.asin(math.sqrt(a)), 1)


def load_gaps(snapshot: Path, kinds: list[str], config: dict) -> dict[str, list[dict]]:
    import sqlite3
    conn = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)
    rows = conn.execute(
        "select id,kind,name,payload from records where city='西安'").fetchall()
    conn.close()
    l1 = config["L1_static_fields"]
    out: dict[str, list[dict]] = {k: [] for k in kinds}
    for rid, kind, name, raw in rows:
        if kind not in out:
            continue
        d = json.loads(raw)
        data = d.get("data") or {}
        missing = [k for k in l1.get(kind, []) if data.get(k) in (None, "")]
        if not missing:
            continue
        lat, lon = data.get("lat"), data.get("lon")
        pos = data.get("position")
        if isinstance(pos, list) and len(pos) == 2:
            lat, lon = pos
        elif isinstance(pos, str) and "," in pos:
            lon, lat = pos.split(",")[:2]
        out[kind].append({"id": rid, "name": name, "missing": missing,
                          "lat": float(lat) if lat not in (None, "") else None,
                          "lon": float(lon) if lon not in (None, "") else None,
                          "crs": d.get("coordinate_system")})
    return out


def amap_call(key: str, params: dict, sleep: float) -> tuple[bytes, str]:
    params = {**params, "key": key, "show_fields": "business"}
    url = "https://restapi.amap.com/v5/place/text?" + urllib.parse.urlencode(params)
    last = b""
    for attempt in (1, 2, 3):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers={"User-Agent": "ShortTripCollect/1.0"}),
                    timeout=25) as resp:
                raw = resp.read(8 * 1024 * 1024)
            probe = json.loads(raw.decode("utf-8", errors="replace"))
            if str(probe.get("infocode")) in ("10021", "10019", "10020", "10004"):
                time.sleep(1.5 * attempt)
                last = raw
                continue
            time.sleep(sleep)
            return raw, str(probe.get("infocode"))
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"__error__": type(exc).__name__}).encode(), type(exc).__name__
    return last, "qps_limited"


def baidu_call(cred, params: dict, sleep: float) -> tuple[bytes, str]:
    path = "/place/v2/search"
    params = {**params, "ak": cred.ak, "sn": sign(path, {**params, "ak": cred.ak}, cred.sk)}
    url = "https://api.map.baidu.com" + path + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "ShortTripCollect/1.0"}),
                timeout=25) as resp:
            raw = resp.read(8 * 1024 * 1024)
        probe = json.loads(raw.decode("utf-8", errors="replace"))
        time.sleep(sleep)
        return raw, str(probe.get("status"))
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"__error__": type(exc).__name__}).encode(), type(exc).__name__


def poi_coords(poi: dict, source: str) -> tuple[float, float] | None:
    loc = poi.get("location")
    if not loc:
        return None
    if isinstance(loc, dict):
        lon, lat = loc.get("lng"), loc.get("lat")
    elif isinstance(loc, str) and "," in loc:
        lon, lat = loc.split(",")[:2]
    else:
        return None
    try:
        lon, lat = float(lon), float(lat)
    except (TypeError, ValueError):
        return None
    if source == "amap":
        wlon, wlat = gcj02_to_wgs84(lon, lat)
    else:
        wlon, wlat = bd09_to_wgs84(lon, lat)
    return wlat, wlon


def extract_fields(poi: dict, kind: str, source: str, missing: list[str]) -> dict:
    business = poi.get("business") or {}
    detail = poi.get("detail_info") or {}
    out = {}
    hours_text = (business.get("opentime_today") if source == "amap"
                  else detail.get("shop_hours"))
    hours = TIME_RE.findall(str(hours_text or ""))
    if len(hours) == 1:
        start, end = hours[0]
        if int(start[:2]) < 24 and int(end[:2]) < 24:
            if "opentime" in missing:
                out["opentime"] = start
            if "endtime" in missing:
                out["endtime"] = end
    if source == "amap":
        keytag = str(business.get("keytag") or business.get("rectag") or "").strip()
        tag = str(business.get("tag") or "").strip()
    else:
        keytag = str(detail.get("label") or detail.get("classified_poi_tag") or "").strip()
        tag = str(detail.get("tag") or "").strip()
    segments = [s.strip() for s in re.split(r"[;；,，\s]+", TAG_RE.sub(" ", tag + " " + keytag)) if s.strip()]
    if kind in ("restaurant",) and "cuisine" in missing:
        blacklist = ("美食", "餐饮", "餐厅", "其他", "中餐", "小吃快餐")
        cuisine = next((s for s in segments if s not in blacklist and len(s) <= 20), None)
        if cuisine:
            out["cuisine"] = cuisine
    if kind == "attraction" and "type" in missing:
        blacklist = ("旅游景点", "其他", "景区")
        theme = next((s for s in segments if s not in blacklist and len(s) <= 20), None)
        if theme:
            out["type"] = theme
    if kind == "accommodation" and "featurehoteltype" in missing:
        if source == "amap":
            value = keytag[:40] or next((s for s in segments if len(s) <= 20), None)
        else:
            level = str(detail.get("level") or "").strip()
            facility = str(detail.get("inner_facility") or "").strip()[:60]
            value = "；".join(x for x in (level, facility) if x)[:80]
        if value and value not in ("", "酒店", "住宿", "宾馆"):
            out["featurehoteltype"] = value
    return {k: v for k, v in out.items() if k in FIELDS.get(kind, ()) and v not in (None, "")}


def run_round(args) -> dict:
    config = json.loads((ROOT / "collector_agent/xian_single_city/quality_model.json").read_text(encoding="utf-8"))
    snapshot = Path(args.snapshot)
    run_dir = Path(args.run)
    if not snapshot.is_absolute():
        snapshot = ROOT / snapshot
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    snapshot = snapshot.resolve()
    run_dir = run_dir.resolve()
    raw_dir = run_dir / "raw_bulk"
    stage = run_dir / "staging" / args.worker
    raw_dir.mkdir(parents=True, exist_ok=True)
    stage.mkdir(parents=True, exist_ok=True)
    gaps = load_gaps(snapshot, args.kinds, config)
    index = {}
    for kind, rows in gaps.items():
        by_name = {}
        for row in rows:
            by_name.setdefault(norm(row["name"]), row)
        index[kind] = {"rows": rows, "by_name": by_name}

    key = (ROOT / ".secrets/amap.key").read_text(encoding="ascii").strip()
    cred = load_credentials(ROOT / ".secrets/baidu.key")
    log, items = [], []
    calls = 0
    stop = None
    combos = []
    grids = [(k, GRID[k]) for k in args.kinds if k in GRID]
    max_kw = max((len(g["keywords"]) for _, g in grids), default=0)
    # interleave kinds so every round covers all requested classes
    for ki in range(max_kw):
        for district in DISTRICTS:
            for kind, grid in grids:
                if ki < len(grid["keywords"]):
                    combos.append((kind, grid["keywords"][ki], district))
    # rotate the grid so successive rounds see different queries
    start = args.offset % max(1, len(combos))
    combos = combos[start:] + combos[:start]
    source_cap = max(1, args.max_calls // 2)
    for source in ("amap", "baidu"):
        if stop:
            break
        source_calls = 0
        for kind, kw, district in combos:
            if source_calls >= source_cap or calls >= args.max_calls or stop:
                break
            grid = GRID[kind]
            for page in range(args.pages):
                if source_calls >= source_cap or calls >= args.max_calls:
                    break
                if source == "amap":
                    params = {"keywords": f"{district}{kw}", "types": grid["types"],
                              "region": "西安", "city_limit": "true",
                              "page_size": "25", "page_num": str(page + 1)}
                    raw, status = amap_call(key, params, args.sleep)
                    ok = status == "10000"
                    pois = (json.loads(raw.decode("utf-8", errors="replace")).get("pois") or []) if ok else []
                else:
                    params = {"query": f"{district}{kw}", "region": "西安", "output": "json",
                              "scope": "2", "page_size": "20", "page_num": str(page)}
                    raw, status = baidu_call(cred, params, args.sleep)
                    ok = status == "0"
                    pois = (json.loads(raw.decode("utf-8", errors="replace")).get("results") or []) if ok else []
                calls += 1
                source_calls += 1
                digest = hashlib.sha256(raw).hexdigest()[:12]
                rel = f"{run_dir.relative_to(ROOT).as_posix()}/raw_bulk/{args.worker}_{source}_{calls:05d}_{digest}.json"
                (ROOT / rel).write_bytes(raw)
                log.append({"source": source, "kind": kind, "query": f"{district}{kw}",
                            "page": page + 1, "status": status, "pois": len(pois), "raw": rel})
                if not ok:
                    if status in ("10021", "10019", "10020", "10004", "配额", "QPS"):
                        stop = f"provider_limit:{source}:{status}"
                    continue
                for poi in pois:
                    pname = str(poi.get("name") or "").strip()
                    if not pname:
                        continue
                    bucket = index[kind]
                    hit = bucket["by_name"].get(norm(pname))
                    basis, distance = "name", None
                    if hit is None:
                        coords = poi_coords(poi, source)
                        if coords is None:
                            continue
                        best = None
                        for row in bucket["rows"]:
                            if row["lat"] is None or row["lon"] is None:
                                continue
                            ratio = difflib.SequenceMatcher(None, norm(pname), norm(row["name"])).ratio()
                            similar = (norm(pname) in norm(row["name"]) or norm(row["name"]) in norm(pname)
                                       or ratio >= 0.68)
                            if not similar:
                                continue
                            d = haversine(row["lat"], row["lon"], coords[0], coords[1])
                            if d <= 200 and (best is None or d < best[1]):
                                best = (row, d)
                        if best is None:
                            continue
                        hit, basis, distance = best[0], "coordinate_match", best[1]
                    fields = extract_fields(poi, kind, source, hit["missing"])
                    if not fields:
                        continue
                    quote = pname if basis == "coordinate_match" else hit["name"]
                    endpoint, publisher, authority, licence, trust = AUTH[source]
                    items.append({
                        "kind": kind, "name": hit["name"], "aliases": [], "data": fields,
                        "source": {"url": endpoint, "publisher": publisher, "authority": authority,
                                   "licence_status": licence, "trust_status": trust,
                                   "published_at": None, "observed_at": None},
                        "evidence": {"raw_path": rel, "quote": quote,
                                     "locator": f"{source} 批量结果 name={pname}",
                                     "identity_basis": basis,
                                     "identity_distance_m": distance,
                                     "matched_name": pname if basis == "coordinate_match" else None},
                        "notes": f"批量补全：{source} 原始响应逐字存证；"
                                 f"身份依据={basis}" + (f"/{distance}m" if distance is not None else ""),
                    })
            if stop:
                break
    out = stage / "enrich_bulk.jsonl"
    out.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n", encoding="utf-8")
    (stage / "api_log.jsonl").write_text(
        "\n".join(json.dumps(l, ensure_ascii=False) for l in log) + "\n", encoding="utf-8")
    return {"calls": calls, "items": len(items), "stop": stop,
            "out": str(out.relative_to(ROOT)).replace("\\", "/"),
            "by_kind": {k: sum(1 for i in items if i["kind"] == k) for k in args.kinds}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--worker", default="bulk_r1")
    ap.add_argument("--kinds", nargs="+", default=["attraction", "restaurant", "accommodation"])
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--max-calls", type=int, default=60)
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--sleep", type=float, default=0.8)
    args = ap.parse_args()
    print(json.dumps(run_round(args), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
