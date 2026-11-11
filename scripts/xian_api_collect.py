"""Fetch Xi'an POI/venue data from Amap (GCJ02) or Baidu (BD09) and stage it.

Every call is logged with redacted params; every response is saved as wire bytes
under <run>/raw_api/. Coordinates are converted to WGS84 with the standard
inverse transform and the conversion is recorded in field provenance, so the
snapshot stays in one coordinate system.

Output: <run>/staging/<worker>/items.jsonl (ready for xian_ingest.py) and
api_log.jsonl (one line per HTTP call).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CITY = "西安"
KIND_MAP = {"poi": "poi", "metro_station": "metro_station", "attraction": "attraction",
            "restaurant": "restaurant", "accommodation": "accommodation"}
AMAP_URL = "https://restapi.amap.com/v5/place/text"
BAIDU_PATH = "/place/v2/search"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def out_of_china(lon: float, lat: float) -> bool:
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)


def _transform(lon: float, lat: float) -> tuple[float, float]:
    a = 6378245.0
    ee = 0.00669342162296594323
    dlat = (-100.0 + 2.0 * (lon - 105.0) + 3.0 * (lat - 35.0)
            + 0.2 * (lat - 35.0) ** 2 + 0.1 * (lon - 105.0) * (lat - 35.0)
            + 0.2 * math.sqrt(abs(lon - 105.0)))
    dlat += ((20.0 * math.sin(6.0 * (lon - 105.0) * math.pi)
              + 20.0 * math.sin(2.0 * (lon - 105.0) * math.pi)) * 2.0 / 3.0)
    dlat += ((20.0 * math.sin((lat - 35.0) * math.pi)
              + 40.0 * math.sin((lat - 35.0) / 3.0 * math.pi)) * 2.0 / 3.0)
    dlat += ((160.0 * math.sin((lat - 35.0) / 12.0 * math.pi)
              + 320 * math.sin((lat - 35.0) * math.pi / 30.0)) * 2.0 / 3.0)
    dlon = (300.0 + (lon - 105.0) + 2.0 * (lat - 35.0)
            + 0.1 * (lon - 105.0) ** 2 + 0.1 * (lon - 105.0) * (lat - 35.0)
            + 0.1 * math.sqrt(abs(lon - 105.0)))
    dlon += ((20.0 * math.sin(6.0 * (lon - 105.0) * math.pi)
              + 20.0 * math.sin(2.0 * (lon - 105.0) * math.pi)) * 2.0 / 3.0)
    dlon += ((20.0 * math.sin((lon - 105.0) * math.pi)
              + 40.0 * math.sin((lon - 105.0) / 3.0 * math.pi)) * 2.0 / 3.0)
    dlon += ((150.0 * math.sin((lon - 105.0) / 12.0 * math.pi)
              + 300.0 * math.sin((lon - 105.0) / 30.0 * math.pi)) * 2.0 / 3.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlon = (dlon * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    return lon + dlon, lat + dlat


def gcj02_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
    if out_of_china(lon, lat):
        return lon, lat
    wlon, wlat = lon, lat
    for _ in range(6):
        glon, glat = _transform(wlon, wlat)
        wlon -= glon - lon
        wlat -= glat - lat
    return round(wlon, 6), round(wlat, 6)


def bd09_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
    from shorttrip.dynamic.baidu import bd09_to_gcj02
    glon, glat = bd09_to_gcj02(lon, lat)
    return gcj02_to_wgs84(glon, glat)


def redact(params: dict) -> dict:
    return {k: ("[REDACTED]" if k in ("key", "ak", "sn") else v) for k, v in params.items()}


def load_amap_key() -> str:
    path = ROOT / ".secrets/amap.key"
    if path.exists():
        return path.read_text(encoding="ascii").strip()
    keys = ROOT / ".secrets/amap.keys"
    return keys.read_text(encoding="ascii").split()[0] if keys.exists() else ""


def item_record(kind: str, name: str, data: dict, url: str, raw_path: str, quote: str,
                locator: str, publisher: str, authority: str, licence: str,
                trust: str, notes: str | None = None) -> dict:
    return {
        "kind": kind,
        "name": name,
        "aliases": [],
        "data": data,
        "source": {
            "url": url, "publisher": publisher, "authority": authority,
            "licence_status": licence, "trust_status": trust,
            "published_at": None, "observed_at": None,
        },
        "evidence": {"raw_path": raw_path, "quote": quote, "locator": locator},
        # all coordinates emitted by this collector are converted to WGS84
        "coordinate_system": "WGS84",
        "notes": notes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="results/<run_id> directory")
    parser.add_argument("--worker", default="api")
    parser.add_argument("--source", choices=["amap", "baidu"], required=True)
    parser.add_argument("--kind", required=True, choices=list(KIND_MAP))
    parser.add_argument("--query", action="append", default=[])
    parser.add_argument("--queries-file")
    parser.add_argument("--types", default=None, help="Amap typecode, e.g. 110000")
    parser.add_argument("--region", default=CITY)
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--page-size", type=int, default=25)
    parser.add_argument("--max-calls", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=0.4)
    args = parser.parse_args()

    queries = list(args.query)
    if args.queries_file:
        path = Path(args.queries_file)
        if not path.is_absolute():
            path = ROOT / path
        queries += [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()]
    if not queries:
        raise SystemExit("no queries given")

    run_dir = Path(args.run)
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    raw_dir = run_dir / "raw_api"
    out_dir = run_dir / "staging" / args.worker
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    kind = KIND_MAP[args.kind]
    if args.source == "amap":
        key = load_amap_key()
        if not key:
            raise SystemExit("missing .secrets/amap.key")
        publisher, authority = "高德开放平台", "amap_place_api"
        licence, trust = "provider_terms_pending_review", "provider_listing"
    else:
        from shorttrip.dynamic.baidu import load_credentials, sign
        cred = load_credentials(ROOT / ".secrets/baidu.key")
        publisher, authority = "百度地图开放平台", "baidu_place_api"
        licence, trust = "provider_terms_pending_review", "provider_listing"

    calls = 0
    items, seen, log = [], set(), []
    stop_reason = None
    for query in queries:
        for page in range(args.pages):
            if calls >= args.max_calls or stop_reason:
                break
            if args.source == "amap":
                params = {"keywords": query, "region": args.region, "city_limit": "true",
                          "page_size": str(min(args.page_size, 25)), "page_num": str(page + 1),
                          "show_fields": "business", "key": key}
                if args.types:
                    params["types"] = args.types
                url = AMAP_URL + "?" + urllib.parse.urlencode(params)
                request = urllib.request.Request(url, headers={"User-Agent": "ShortTripCollect/1.0"})
            else:
                params = {"query": query, "region": args.region, "output": "json", "scope": "2",
                          "page_size": str(min(args.page_size, 20)), "page_num": str(page),
                          "ak": cred.ak}
                if args.types:
                    params["tag"] = args.types
                if cred.sk:
                    params["sn"] = sign(BAIDU_PATH, params, cred.sk)
                url = "https://api.map.baidu.com" + BAIDU_PATH + "?" + urllib.parse.urlencode(params)
                request = urllib.request.Request(url, headers={"User-Agent": "ShortTripCollect/1.0"})

            calls += 1
            started = time.time()
            raw = None
            for attempt in (1, 2, 3):
                try:
                    with urllib.request.urlopen(request, timeout=25) as response:
                        raw = response.read(8 * 1024 * 1024)
                except Exception as exc:  # noqa: BLE001
                    log.append({"at": now_iso(), "source": args.source, "query": query,
                                "page": page, "attempt": attempt, "ok": False,
                                "error": type(exc).__name__})
                    stop_reason = f"request_failed:{type(exc).__name__}"
                    break
                probe = json.loads(raw.decode("utf-8", errors="replace"))
                code_probe = str(probe.get("infocode")) if args.source == "amap" else str(probe.get("status"))
                if args.source == "amap" and code_probe in ("10021", "10019", "10020", "10004"):
                    time.sleep(1.5 * attempt)
                    continue
                break
            if raw is None:
                break
            elapsed = round(time.time() - started, 3)
            raw_name = f"{args.source}_{args.worker}_{int(time.time() * 1000)}_{page}.json"
            raw_path = raw_dir / raw_name
            raw_path.write_bytes(raw)
            text = raw.decode("utf-8", errors="replace")
            data = json.loads(text)
            status_ok = str(data.get("status")) == "1" if args.source == "amap" else data.get("status") == 0
            code = data.get("infocode") if args.source == "amap" else data.get("message")
            pois = (data.get("pois") if args.source == "amap" else data.get("results")) or []
            log.append({"at": now_iso(), "source": args.source, "query": query, "page": page,
                        "endpoint": AMAP_URL if args.source == "amap" else "api.map.baidu.com" + BAIDU_PATH,
                        "params": redact(params), "ok": status_ok, "code": code,
                        "count": len(pois), "raw_path": str(raw_path.relative_to(ROOT)).replace("\\", "/"),
                        "raw_sha256": sha256(raw), "elapsed_s": elapsed})
            if not status_ok:
                stop_reason = f"provider_error:{code}"
                break
            time.sleep(max(args.sleep, 0.5))

            for index, poi in enumerate(pois):
                name = str(poi.get("name") or "").strip()
                if not name or name in seen:
                    continue
                locator = poi.get("id") or poi.get("uid") or f"#{index}"
                if args.source == "amap":
                    location = str(poi.get("location") or "")
                    if "," not in location:
                        continue
                    lon, lat = (float(x) for x in location.split(",")[:2])
                    wlon, wlat = gcj02_to_wgs84(lon, lat)
                    native = "GCJ02"
                    address = poi.get("address")
                    district = poi.get("adname")
                    typecode = poi.get("typecode")
                else:
                    location = poi.get("location") or {}
                    if not location.get("lng"):
                        continue
                    wlon, wlat = bd09_to_wgs84(float(location["lng"]), float(location["lat"]))
                    native = "BD09"
                    address = poi.get("address")
                    district = (poi.get("area") or "").strip() or None
                    typecode = poi.get("tag") or poi.get("type")
                if kind == "poi":
                    payload = {"name": name, "position": [wlat, wlon]}
                elif kind == "metro_station":
                    payload = {"name": name, "position": f"{wlon},{wlat}", "line": None}
                else:
                    payload = {"name": name, "lat": wlat, "lon": wlon, "type": typecode,
                               "id": None, "opentime": None, "endtime": None, "price": None,
                               "recommendmintime": None, "recommendmaxtime": None}
                    if kind == "restaurant":
                        payload = {"name": name, "lat": wlat, "lon": wlon, "cuisine": None,
                                   "price": None, "opentime": None, "endtime": None,
                                   "recommendedfood": None}
                    if kind == "accommodation":
                        payload = {"name": name, "lat": wlat, "lon": wlon, "price": None,
                                   "numbed": None, "featurehoteltype": None, "hotelname_en": None}
                if name not in text:
                    continue
                seen.add(name)
                items.append(item_record(
                    kind, name, payload, url.split("?")[0], str(raw_path.relative_to(ROOT)).replace("\\", "/"),
                    name, f"{locator} ({args.source} page {page + 1})", publisher, authority, licence, trust,
                    notes=f"坐标由 {native} 转 WGS84（标准反算），地址={address}，区县={district}"))

    out_path = out_dir / "items.jsonl"
    with open(out_path, "w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    with open(out_dir / "api_log.jsonl", "w", encoding="utf-8") as handle:
        for row in log:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {
        "source": args.source, "kind": kind, "calls": calls,
        "items": len(items), "queries": len(queries),
        "stop_reason": stop_reason, "items_path": str(out_path.relative_to(ROOT)).replace("\\", "/"),
        "ok_calls": sum(1 for row in log if row.get("ok")),
    }
    (out_dir / "api_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
