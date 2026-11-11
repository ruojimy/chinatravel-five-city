"""Field-usability campaign: measure L1 coverage and enrich missing fields.

status  -- count records whose L1 static fields are all present, compare to
           collector_agent/xian_single_city/field_targets.json.
enrich  -- for records missing L1 fields, query Baidu place search+detail and
           Amap business; write an --enrich jsonl for xian_ingest.py.

All provider responses are saved as raw bytes; nothing is estimated.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CITY = "西安"
TARGETS = ROOT / "collector_agent/xian_single_city/field_targets.json"
TIME_RE = re.compile(r"(\d{2}:\d{2})-(\d{2}:\d{2})")
TAG_RE = re.compile(r"<[^>]+>")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def norm(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").replace("（", "(").replace("）", ")")).lower()


def load_config() -> dict:
    return json.loads(TARGETS.read_text(encoding="utf-8"))


def rows(conn, kind: str):
    return [(rid, name, json.loads(payload)) for rid, name, payload in conn.execute(
        f"select id, name, payload from records where city='{CITY}' and kind=? order by id",
        (kind,))]


def l1_complete(payload: dict, keys: list[str]) -> bool:
    data = payload.get("data") or {}
    return all(data.get(k) not in (None, "") for k in keys)


def compute_status(snapshot: Path) -> dict:
    import sqlite3
    cfg = load_config()
    conn = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)
    out = {}
    for kind, keys in cfg["L1_static_fields"].items():
        records = rows(conn, kind)
        complete = [rid for rid, _, p in records if l1_complete(p, keys)]
        coverage = {}
        for key in keys:
            coverage[key] = sum(
                1 for _, _, p in records if (p.get("data") or {}).get(key) not in (None, ""))
        missing = {}
        for rid, name, p in records:
            gaps = [k for k in keys if (p.get("data") or {}).get(k) in (None, "")]
            if gaps:
                missing[rid] = {"name": name, "gaps": gaps}
        target = cfg["completion_target"][kind]
        out[kind] = {
            "records": len(records), "l1_complete": len(complete),
            "target": target, "delta": max(0, target - len(complete)),
            "progress_pct": round(100 * len(complete) / target, 1) if target else None,
            "field_coverage": coverage, "pending_records": len(missing),
        }
    conn.close()
    status = {
        "snapshot": str(snapshot.relative_to(ROOT)).replace("\\", "/"),
        "checked_at": now_iso(),
        "by_kind": out,
        "complete": all(v["l1_complete"] >= v["target"] for v in out.values()),
    }
    return status


def print_status(status: dict) -> None:
    print(f"snapshot {status['snapshot']}  checked_at {status['checked_at']}")
    print(f"{'类别':<16}{'L1齐备':>9}{'目标':>8}{'差额':>8}{'进度':>9}{'待补记录':>10}")
    for kind, row in status["by_kind"].items():
        print(f"{kind:<16}{row['l1_complete']:>9}{row['target']:>8}{row['delta']:>8}"
              f"{str(row['progress_pct']) + '%':>9}{row['pending_records']:>10}")
    print("complete:", status["complete"])


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    import math
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 1)


def bd09_to_wgs(lat, lon):
    sys.path.insert(0, str(ROOT / "scripts"))
    from xian_api_collect import bd09_to_wgs84
    wlon, wlat = bd09_to_wgs84(float(lon), float(lat))
    return wlat, wlon


def baidu_call(cred, path: str, params: dict) -> tuple[bytes, dict]:
    from shorttrip.dynamic.baidu import sign
    base = {**params, "ak": cred.ak, "output": "json"}
    base["sn"] = sign(path, base, cred.sk)
    url = "https://api.map.baidu.com" + path + "?" + urllib.parse.urlencode(base)
    with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "ShortTripFields/1.0"}),
            timeout=25) as response:
        raw = response.read(4 * 1024 * 1024)
    return raw, json.loads(raw.decode("utf-8", errors="replace"))


def amap_call(key: str, params: dict) -> tuple[bytes, dict]:
    url = "https://restapi.amap.com/v5/place/text?" + urllib.parse.urlencode(
        {**params, "key": key})
    with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "ShortTripFields/1.0"}),
            timeout=25) as response:
        raw = response.read(4 * 1024 * 1024)
    return raw, json.loads(raw.decode("utf-8", errors="replace"))


def parse_fields(info: dict, kind: str, current: dict) -> dict:
    out = {}
    hours = TIME_RE.findall(str(info.get("shop_hours") or ""))
    if len(hours) == 1:
        start, end = hours[0]
        if int(start[:2]) < 24 and int(end[:2]) < 24:
            out["opentime"], out["endtime"] = start, end
    tag = " ".join(str(info.get(k) or "") for k in
                   ("tag", "classified_poi_tag", "content_tag", "level"))
    tag = TAG_RE.sub(" ", tag)
    segments = [s.strip() for s in re.split(r"[;；,，\s]+", tag) if s.strip()]
    if kind == "restaurant" and segments:
        cuisine = next((s for s in segments if s not in ("美食", "餐饮", "餐厅", "其他")), None)
        if cuisine and len(cuisine) <= 20:
            out["cuisine"] = cuisine
    if kind == "attraction" and segments:
        theme = next((s for s in segments if s not in ("旅游景点", "其他", "景区")), None)
        if theme and len(theme) <= 20:
            out["type"] = theme
    if kind == "accommodation":
        facility = str(info.get("inner_facility") or "").strip()
        level = str(info.get("level") or "").strip()
        combined = "；".join(x for x in (level, facility[:80]) if x)
        if combined:
            out["featurehoteltype"] = combined
    return {k: v for k, v in out.items() if current.get(k) in (None, "")}


def enrich(args) -> dict:
    import sqlite3
    cfg = load_config()
    keys = cfg["L1_static_fields"][args.kind]
    run_dir = Path(args.run)
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    raw_dir = run_dir / "raw_api"
    out_dir = run_dir / "staging" / args.worker
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    snapshot = Path(args.snapshot)
    if not snapshot.is_absolute():
        snapshot = ROOT / snapshot
    conn = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)
    pending = []
    for rid, name, payload in rows(conn, args.kind):
        gaps = [k for k in keys if (payload.get("data") or {}).get(k) in (None, "")]
        if gaps:
            pending.append((rid, name, payload.get("data") or {}, gaps))
    conn.close()
    batch = pending[args.offset:args.offset + args.limit]

    from shorttrip.dynamic.baidu import load_credentials
    cred = load_credentials(ROOT / ".secrets/baidu.key")
    amap_key = (ROOT / ".secrets/amap.key").read_text(encoding="ascii").strip()
    items, log = [], []
    for index, (rid, name, data, gaps) in enumerate(batch):
        quote = name
        raw_path = None
        info = {}
        try:
            raw_s, search = baidu_call(cred, "/place/v2/search", {
                "query": name, "region": CITY, "scope": "2", "page_size": "3", "page_num": "0"})
            results = search.get("results") or []
            chosen, basis, distance = [], "name", None
            for r in results:
                if norm(r.get("name")) == norm(name):
                    chosen = [r]; break
            if not chosen and data.get("lat") is not None and data.get("lon") is not None:
                best = None
                for r in results:
                    loc = r.get("location") or {}
                    if not loc.get("lat") or not loc.get("lng"):
                        continue
                    try:
                        rlat, rlon = bd09_to_wgs(loc["lat"], loc["lng"])
                        d = haversine_m(float(data["lat"]), float(data["lon"]), rlat, rlon)
                    except (TypeError, ValueError):
                        continue
                    if d <= 200 and (best is None or d < best[1]):
                        best = (r, d)
                if best:
                    chosen, basis, distance = [best[0]], "coordinate_match", best[1]
            if chosen:
                uid = chosen[0].get("uid")
                if uid:
                    raw_d, detail = baidu_call(cred, "/place/v2/detail",
                                              {"uid": uid, "scope": "2"})
                    result = detail.get("result") or {}
                    info = result.get("detail_info") or {}
                    matched_name = result.get("name") or ""
                    raw_text = raw_d.decode("utf-8", errors="replace")
                    name_in_raw = norm(name) in re.sub(r"\s+", "", raw_text).lower()
                    if not name_in_raw and basis != "coordinate_match":
                        # 记录名必须逐字出现在原始响应里，与 xian_verify.py 口径一致
                        info = {}
                        log.append({"name": name, "ok": False,
                                    "reason": "name_not_in_raw", "returned": matched_name})
                    else:
                        quote = matched_name or name
                        f = raw_dir / f"field_{args.worker}_baidu_{args.kind}_{args.offset + index:05d}.json"
                        f.write_bytes(raw_d)
                        raw_path = str(f.relative_to(ROOT)).replace("\\", "/")
        except Exception as exc:  # noqa: BLE001
            log.append({"name": name, "ok": False, "error": type(exc).__name__})

        if not info:
            try:
                raw_a, amap = amap_call(amap_key, {
                    "keywords": name, "region": CITY, "city_limit": "true",
                    "page_size": "3", "show_fields": "business"})
                pois = [p for p in (amap.get("pois") or []) if norm(p.get("name")) == norm(name)]
                raw_text = raw_a.decode("utf-8", errors="replace")
                if pois and norm(name) not in re.sub(r"\s+", "", raw_text).lower():
                    pois = []
                if pois:
                    b = pois[0].get("business") or {}
                    hours = TIME_RE.findall(str(b.get("opentime_today") or ""))
                    if len(hours) == 1 and int(hours[0][0][:2]) < 24 and int(hours[0][1][:2]) < 24:
                        info = {"shop_hours": "-".join(hours[0])}
                    if args.kind == "restaurant" and (b.get("keytag") or b.get("rectag")):
                        info["tag"] = b.get("keytag") or b.get("rectag")
                    if args.kind == "attraction" and b.get("keytag"):
                        info["tag"] = b["keytag"]
                    quote = pois[0].get("name") or name
                    f = raw_dir / f"field_{args.worker}_amap_{args.kind}_{args.offset + index:05d}.json"
                    f.write_bytes(raw_a)
                    raw_path = str(f.relative_to(ROOT)).replace("\\", "/")
            except Exception as exc:  # noqa: BLE001
                log.append({"name": name, "ok": False, "amap_error": type(exc).__name__})

        fields = parse_fields(info, args.kind, data) if info else {}
        if fields and raw_path:
            items.append({
                "kind": args.kind, "name": name, "aliases": [],
                "data": fields,
                "source": {
                    "url": "https://api.map.baidu.com/place/v2/detail"
                    if "baidu" in raw_path else "https://restapi.amap.com/v5/place/text",
                    "publisher": "百度地图开放平台" if "baidu" in raw_path else "高德开放平台",
                    "authority": "baidu_place_api" if "baidu" in raw_path else "amap_place_api",
                    "licence_status": "provider_terms_pending_review",
                    "trust_status": "provider_listing",
                    "published_at": None, "observed_at": None,
                },
                "evidence": {"raw_path": raw_path, "quote": quote,
                             "locator": f"detail_info / business 字段（补齐 {','.join(gaps)}）",
                             "identity_basis": basis, "identity_distance_m": distance,
                             "matched_name": quote if basis == "coordinate_match" else None},
                "notes": "仅取单一营业区间与平台类目标签；价格/房态属运行时依赖，不静态固化",
            })
        log.append({"name": name, "ok": bool(fields), "gaps": gaps,
                    "filled": list(fields), "raw_path": raw_path})
        time.sleep(max(args.sleep, 0.6))
        if len(log) >= args.max_calls:
            break

    out = out_dir / f"enrich_{args.kind}_{args.offset}.jsonl"
    out.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n",
                   encoding="utf-8")
    (out_dir / f"api_log_{args.kind}_{args.offset}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in log) + "\n", encoding="utf-8")
    return {"kind": args.kind, "offset": args.offset, "pending": len(pending),
            "attempted": len(batch), "enrich_items": len(items),
            "out": str(out.relative_to(ROOT)).replace("\\", "/"),
            "checked_at": now_iso()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("status")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("enrich")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--worker", default="field_enrich")
    p.add_argument("--kind", required=True,
                   choices=["attraction", "restaurant", "accommodation"])
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--limit", type=int, default=60)
    p.add_argument("--max-calls", type=int, default=60)
    p.add_argument("--sleep", type=float, default=0.7)
    args = parser.parse_args()

    snapshot = Path(args.snapshot)
    if not snapshot.is_absolute():
        snapshot = ROOT / snapshot
    if args.command == "status":
        status = compute_status(snapshot)
        if args.json:
            print(json.dumps(status, ensure_ascii=False, indent=1))
        else:
            print_status(status)
    else:
        print(json.dumps(enrich(args), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
