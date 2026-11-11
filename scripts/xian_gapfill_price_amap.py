"""Fill restaurant per-capita price from Amap `cost`.

Amap exposes the per-capita spend under `business.cost` (v5) or `biz_ext.cost`
(v3). Sampling of existing captures shows ~90% of restaurant POIs carry it, so
one pass covers most of the catalogue.

Evidence: the quote is the verbatim `"cost": "45.00"` fragment cut from the
saved response, so the number can be re-checked without trusting this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from xian_gapfill_food_amap import (KEYS, call, coord_of, endpoints, pick)  # noqa: E402

RUN = ROOT / "results/xian_gapfill_20261109"


def cost_of(poi: dict) -> str | None:
    biz = poi.get("business") or {}
    if biz.get("cost"):
        return str(biz["cost"])
    ext = poi.get("biz_ext") or {}
    if isinstance(ext, str):
        try:
            ext = json.loads(ext)
        except json.JSONDecodeError:
            ext = {}
    for key in ("cost", "price"):
        if ext.get(key):
            return str(ext[key])
    return None


def quote_for(raw_text: str, cost: str) -> str | None:
    pattern = re.compile(r'"cost"\s*:\s*"?' + re.escape(cost) + r'"?')
    m = pattern.search(raw_text)
    if m:
        return m.group(0)
    pattern = re.compile(r'"price"\s*:\s*"?' + re.escape(cost) + r'"?')
    m = pattern.search(raw_text)
    return m.group(0) if m else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default="results/xian_gapfill_20261109/snapshot_v16/catalog.sqlite3")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.2)
    ap.add_argument("--tag", default="p1")
    ap.add_argument("--keys", default="")
    ap.add_argument("--shard-index", type=int, default=0)
    ap.add_argument("--shard-count", type=int, default=1)
    args = ap.parse_args()

    global KEYS
    if args.keys:
        KEYS = [k.strip() for k in args.keys.split(",") if k.strip()]

    out_dir = RUN / "staging" / f"price_{args.tag}"
    raw_dir = RUN / "raw" / f"price_{args.tag}"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    items_path = out_dir / "items.jsonl"
    log_path = out_dir / "run_log.jsonl"

    con = sqlite3.connect(str(ROOT / args.snapshot))
    targets = []
    for n, pl in con.execute("select name,payload from records where city='西安' and kind='restaurant'"):
        d = json.loads(pl)["data"]
        if d.get("price") in (None, ""):
            targets.append({"name": n, "data": d})
    con.close()

    done = set()
    if items_path.exists():
        for line in items_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["name"])
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("error") or rec.get("result") == "api_error":
                continue  # transient failure: retry next run
            done.add(rec["restaurant"])
    todo = [t for t in targets if t["name"] not in done]
    if args.shard_count > 1:
        import hashlib as _h
        todo = [t for t in todo
                if int(_h.md5(t["name"].encode("utf-8")).hexdigest(), 16) % args.shard_count == args.shard_index]
    if args.limit:
        todo = todo[:args.limit]
    print(json.dumps({"targets": len(targets), "already": len(done), "todo": len(todo)}, ensure_ascii=False))

    stats = {"requests": 0, "matched": 0, "priced": 0, "no_cost": 0, "by_endpoint": {}, "errors": []}
    types = "050000"
    for i, row in enumerate(todo):
        name, data = row["name"], row["data"]
        key = KEYS[i % len(KEYS)]
        eps = endpoints(name, coord_of(data), key, types)
        url, label, _ = eps[i % len(eps)]
        entry = {"restaurant": name, "endpoint": label}
        try:
            payload = call(url)
            stats["requests"] += 1
            stats["by_endpoint"][label] = stats["by_endpoint"].get(label, 0) + 1
            if str(payload.get("status")) != "1":
                info = payload.get("info")
                stats["errors"].append({"name": name, "info": info})
                entry.update({"result": "api_error", "info": info})
                log_path.open("a", encoding="utf-8").write(json.dumps(entry, ensure_ascii=False) + "\n")
                time.sleep(args.delay)
                continue
        except Exception as exc:  # noqa: BLE001
            stats["errors"].append({"name": name, "error": type(exc).__name__})
            time.sleep(args.delay)
            continue

        poi, basis = pick(payload.get("pois") or [], name, coord_of(data))
        if poi:
            tp = poi.get("type") or ""
            if not (tp.startswith("餐饮") or "餐饮" in tp or "美食" in tp):
                poi, basis = None, "non_catering_type"
        if not poi:
            entry.update({"result": "no_match"})
            log_path.open("a", encoding="utf-8").write(json.dumps(entry, ensure_ascii=False) + "\n")
            time.sleep(args.delay)
            continue

        stats["matched"] += 1
        cost = cost_of(poi)
        if not cost:
            stats["no_cost"] += 1
            entry.update({"result": "no_cost", "poi": poi.get("name")})
            log_path.open("a", encoding="utf-8").write(json.dumps(entry, ensure_ascii=False) + "\n")
            time.sleep(args.delay)
            continue

        slug = re.sub(r"[^\w\u4e00-\u9fff]+", "_", name)[:40] + "__" + hashlib.sha1(
            (name + label).encode("utf-8")).hexdigest()[:8]
        raw_file = raw_dir / f"{slug}.amap.json"
        raw_text = json.dumps(payload, ensure_ascii=False, indent=1)
        raw_file.write_text(raw_text, encoding="utf-8")
        quote = quote_for(raw_text, cost)
        if not quote or len(quote) < 6:
            entry.update({"result": "quote_too_short", "cost": cost})
            log_path.open("a", encoding="utf-8").write(json.dumps(entry, ensure_ascii=False) + "\n")
            time.sleep(args.delay)
            continue

        try:
            value = round(float(cost), 1)
        except ValueError:
            time.sleep(args.delay)
            continue

        item = {
            "kind": "restaurant",
            "name": name,
            "data": {"price": value},
            "source": {"url": f"https://www.amap.com/place/{poi.get('id')}" if poi.get("id") else url,
                       "publisher": "高德地图", "authority": "map_poi_display",
                       "licence_status": "public_page_reuse_unverified",
                       "observed_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")},
            "evidence": {"raw_path": str(raw_file.relative_to(ROOT)).replace("\\", "/"),
                         "quote": quote, "locator": "poi business cost",
                         "identity_basis": f"{basis};{label}"},
            "notes": {"name_on_source": poi.get("name"), "amap_type": poi.get("type")},
        }
        items_path.open("a", encoding="utf-8").write(json.dumps(item, ensure_ascii=False) + "\n")
        stats["priced"] += 1
        entry.update({"result": "hit", "cost": value, "basis": basis})
        log_path.open("a", encoding="utf-8").write(json.dumps(entry, ensure_ascii=False) + "\n")
        time.sleep(args.delay)

        if (i + 1) % 100 == 0:
            print(json.dumps({"progress": i + 1, **{k: v for k, v in stats.items() if k != "errors"}},
                             ensure_ascii=False))

    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
