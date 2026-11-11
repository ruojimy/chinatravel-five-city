"""Fill restaurant cuisine / opening hours from Amap, rotating three endpoints.

Endpoints rotate per request so a single endpoint's rate limit is not the
bottleneck:
  0  /v5/place/text    keyword search, city limited
  1  /v5/place/around  radius search around the catalog coordinate (GCJ-02)
  2  /v3/place/text    legacy keyword search, extensions=all

Every accepted value is backed by the saved JSON response and a verbatim quote.
Identity is name-first: exact normalised name, then containment with branch
tokens, then <=150 m plus high string similarity. No match -> no item.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from p31_common import parse_amap_hours, wgs84_to_gcj02  # noqa: E402
from _keys import amap_keys  # noqa: E402

RUN = ROOT / "results/xian_gapfill_20261109"
KEYS = amap_keys()

GENERIC = {"餐饮相关", "餐饮服务", "中餐厅", "综合酒楼", "其他", "美食", "餐厅"}
CUISINE_MAP = {
    "四川菜(川菜)": "川菜", "火锅店": "火锅", "清真菜馆": "清真菜", "快餐厅": "快餐",
    "咖啡厅": "咖啡", "糕饼店": "糕点", "面馆": "面馆", "小吃快餐": "小吃快餐",
    "茶餐厅": "茶餐厅", "日本料理": "日料", "西餐厅": "西餐", "烧烤": "烧烤",
}


def norm(s: str) -> str:
    s = re.sub(r"[A-Za-z0-9\s\-'’|]", "", s or "")
    return re.sub(r"[\s\-·、,，.。()（）]", "", s).lower()


def branch_tokens(name: str) -> list[str]:
    return [t for t in re.findall(r"[（(]([^）)]+)[）)]", name or "") if len(t) >= 2]


def coord_of(row: dict) -> tuple[float, float] | None:
    try:
        return float(row["lat"]), float(row["lon"])
    except (TypeError, KeyError, ValueError):
        return None


def dist_m(a, b, c, d) -> float:
    import math
    dx = (a - c) * 111320 * math.cos(math.radians((b + d) / 2))
    dy = (b - d) * 110540
    return math.hypot(dx, dy)


def call(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ShortTripAssistant/1.0"}),
                                timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def endpoints(name: str, coord, key: str, types: str = "050000") -> list[tuple[str, str, str]]:
    base = "https://restapi.amap.com"
    text_q = urllib.parse.urlencode({
        "keywords": name, "region": "西安", "city_limit": "true",
        "page_size": 5, "show_fields": "business", "key": key})
    out = [(f"{base}/v5/place/text?{text_q}", "v5_place_text", "")]
    if coord:
        lat, lon = wgs84_to_gcj02(*coord)
        around_q = urllib.parse.urlencode({
            "location": f"{lon:.6f},{lat:.6f}", "radius": 1200, "types": types,
            "page_size": 10, "show_fields": "business", "key": key})
        out.append((f"{base}/v5/place/around?{around_q}", "v5_place_around", f"{lon:.6f},{lat:.6f}"))
    v3_q = urllib.parse.urlencode({
        "keywords": name, "city": "西安", "offset": 5, "extensions": "all", "key": key})
    out.append((f"{base}/v3/place/text?{v3_q}", "v3_place_text", ""))
    return out


def pick(pois: list[dict], name: str, coord) -> tuple[dict | None, str]:
    tn = norm(name)
    best = None
    for p in pois:
        cn = norm(p.get("name") or "")
        if not cn:
            continue
        if tn == cn:
            return p, "exact_name"
        if tn and (tn in cn or cn in tn):
            bt, bc = branch_tokens(name), branch_tokens(p.get("name") or "")
            if bt and bc and not any(a in b or b in a for a in bt for b in bc):
                continue
            best = best or (p, "name_contains")
            continue
        if coord:
            try:
                plon, plat = map(float, (p.get("location") or "").split(","))
            except ValueError:
                continue
            dd = dist_m(coord[0], coord[1], plat, plon)
            if dd <= 150 and difflib.SequenceMatcher(None, tn, cn).ratio() >= 0.85:
                best = best or (p, f"name_fuzzy+{int(dd)}m")
    return best if best else (None, "no_match")


def cuisine_of(poi: dict) -> str | None:
    tp = poi.get("type") or ""
    parts = [x for x in tp.split(";") if x]
    if not parts:
        return None
    last = parts[-1]
    label = CUISINE_MAP.get(last, last)
    label = re.sub(r"[（(].*?[）)]", "", label).strip()
    if not label or label in GENERIC:
        return None
    return label


def hours_of(poi: dict) -> str | None:
    biz = poi.get("business") or {}
    text = biz.get("opentime_week") or biz.get("opentime_today")
    if text:
        return str(text)
    ext = poi.get("biz_ext") or {}
    if isinstance(ext, str):
        try:
            ext = json.loads(ext)
        except json.JSONDecodeError:
            ext = {}
    for key in ("opentime2", "open_time", "opentime", "opentime_week"):
        if ext.get(key):
            return str(ext[key])
    return None


def hhmm(minutes: int) -> str:
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default="results/xian_gapfill_20261109/snapshot_v14/catalog.sqlite3")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.35)
    ap.add_argument("--tag", default="amap")
    ap.add_argument("--kind", default="restaurant", choices=["restaurant", "attraction"])
    ap.add_argument("--keys", default="")
    args = ap.parse_args()

    global KEYS
    if args.keys:
        KEYS = [k.strip() for k in args.keys.split(",") if k.strip()]
    prefix = "food" if args.kind == "restaurant" else "attr"
    types = "050000" if args.kind == "restaurant" else "110000"
    out_dir = RUN / "staging" / f"{prefix}_{args.tag}"
    raw_dir = RUN / "raw" / f"{prefix}_{args.tag}"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(ROOT / args.snapshot))
    targets = []
    for n, pl in con.execute("select name,payload from records where city='西安' and kind=?", (args.kind,)):
        d = json.loads(pl)["data"]
        if args.kind == "restaurant":
            if not d.get("cuisine") or not d.get("opentime"):
                targets.append({"name": n, "data": d})
        elif not d.get("opentime"):
            targets.append({"name": n, "data": d})
    con.close()

    done = set()
    items_path = out_dir / "items.jsonl"
    log_path = out_dir / "run_log.jsonl"
    if items_path.exists():
        for line in items_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["name"])
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["restaurant"])

    todo = [t for t in targets if t["name"] not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(json.dumps({"targets": len(targets), "already": len(done), "todo": len(todo)}, ensure_ascii=False))

    stats = {"requests": 0, "matched": 0, "cuisine": 0, "hours": 0, "items": 0,
             "by_endpoint": {}, "errors": []}
    for i, row in enumerate(todo):
        name, data = row["name"], row["data"]
        coord = coord_of(data)
        key = KEYS[i % len(KEYS)]
        eps = endpoints(name, coord, key, types)
        url, label, _ = eps[i % len(eps)]
        entry = {"restaurant": name, "endpoint": label, "url": url}
        try:
            payload = call(url)
            stats["requests"] += 1
            stats["by_endpoint"][label] = stats["by_endpoint"].get(label, 0) + 1
            if str(payload.get("status")) != "1":
                info = payload.get("info")
                stats["errors"].append({"name": name, "endpoint": label, "info": info})
                entry.update({"result": "api_error", "info": info})
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                if "LIMIT" in str(info).upper() or "QUOTA" in str(info).upper():
                    print(json.dumps({"stopped": "quota", "info": info}, ensure_ascii=False))
                    break
                time.sleep(args.delay)
                continue
        except Exception as exc:  # noqa: BLE001
            stats["errors"].append({"name": name, "endpoint": label, "error": type(exc).__name__})
            time.sleep(args.delay)
            continue

        pois = payload.get("pois") or []
        poi, basis = pick(pois, name, coord)
        if poi and args.kind == "restaurant":
            tp = poi.get("type") or ""
            catering = tp.startswith("餐饮") or "餐饮" in tp or "美食" in tp
            named_eatery = bool(re.search(r"餐厅|饭店|酒楼|宴会厅|美食|小吃|面馆|火锅|烧烤", name))
            if not catering and not named_eatery:
                poi, basis = None, "non_catering_type"
        if not poi:
            entry.update({"result": "no_match", "pois": len(pois)})
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            time.sleep(args.delay)
            continue

        stats["matched"] += 1
        slug = re.sub(r"[^\w\u4e00-\u9fff]+", "_", name)[:40] + "__" + hashlib.sha1(
            (name + label).encode("utf-8")).hexdigest()[:8]
        raw_file = raw_dir / f"{slug}.amap.json"
        raw_file.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        rel_raw = str(raw_file.relative_to(ROOT)).replace("\\", "/")
        poi_url = f"https://www.amap.com/place/{poi.get('id')}" if poi.get("id") else url

        def emit(fields: dict, quote: str, locator: str) -> None:
            item = {
                "kind": args.kind,
                "name": name,
                "data": fields,
                "source": {"url": poi_url, "publisher": "高德地图",
                           "authority": "map_poi_display",
                           "licence_status": "public_page_reuse_unverified",
                           "observed_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")},
                "evidence": {"raw_path": rel_raw, "quote": quote, "locator": locator,
                             "identity_basis": f"{basis};{label}"},
                "notes": {"name_on_source": poi.get("name"), "amap_type": poi.get("type")},
            }
            with items_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
            stats["items"] += 1

        if args.kind == "restaurant" and not data.get("cuisine"):
            label_c = cuisine_of(poi)
            if label_c and label_c in (poi.get("type") or ""):
                emit({"cuisine": label_c}, label_c, "poi type")
                stats["cuisine"] += 1

        if not data.get("opentime"):
            text = hours_of(poi)
            regular = re.split(r"\d{2,4}-\d{1,2}(?:-\d{1,2})?\s*[至到]", text or "")[0].strip()
            window = parse_amap_hours(regular) if regular else None
            if text and window:
                start, end = window
                if end >= 24 * 60:
                    end = 24 * 60 - 1
                emit({"opentime": hhmm(start), "endtime": hhmm(end)}, text, "poi business hours")
                stats["hours"] += 1

        entry.update({"result": "hit", "basis": basis, "poi": poi.get("name")})
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        time.sleep(args.delay)

        if (i + 1) % 50 == 0:
            print(json.dumps({"progress": i + 1, **{k: v for k, v in stats.items() if k != "errors"}},
                             ensure_ascii=False))

    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
