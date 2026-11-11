"""Definitive count: how many of the 240 priced hotels expose an Amap per-capita?

Concurrent (3 workers, ~3 QPS) v5 place/text with business fields. Counts:
  - any non-empty cost
  - exact-name hotel POI with cost
  - non-hotel / sub-venue matches

Writes results/amap_hotel_cost_full_scan_20261111.json
"""
from __future__ import annotations

import csv
import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOTELS = ROOT / "data/xian11_merged_sandbox/accommodations/xian/accommodations.csv"
OUT = ROOT / "results/amap_hotel_cost_full_scan_20261111.json"
UA = "ShortTripAssistant/1.0 (hotel cost full scan)"
KEY = (ROOT / ".secrets/amap.key").read_text(encoding="ascii").strip()


def query(name: str) -> dict:
    params = {"key": KEY, "keywords": name, "region": "西安", "city_limit": "true",
              "show_fields": "business", "page_size": "3", "page": "1"}
    url = "https://restapi.amap.com/v5/place/text?" + urllib.parse.urlencode(params)
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10) as r:
                body = json.loads(r.read().decode("utf-8"))
            break
        except Exception as exc:  # noqa: BLE001
            if attempt == 1:
                return {"name": name, "error": f"{type(exc).__name__}: {exc}"}
            time.sleep(0.8)
    pois = body.get("pois") or []
    best = next((p for p in pois if p.get("name") == name), None)
    raw = (((best or {}).get("business") or {}).get("cost") or "").strip()
    try:
        cost = float(raw)
    except ValueError:
        cost = None
    return {"name": name, "status": body.get("status"), "info": body.get("info"),
            "matched": (best or {}).get("name"), "cost": cost,
            "type": (best or {}).get("type")}


def main() -> int:
    rows = [r for r in csv.DictReader(open(HOTELS, encoding="utf-8-sig"))
            if r["price_status"] == "source_value"]
    t0 = time.time()
    out = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(query, r["name"]) for r in rows]
        for i, fut in enumerate(as_completed(futures), 1):
            out.append(fut.result())
            if i % 40 == 0:
                print(f"{i}/{len(rows)} {time.time()-t0:.0f}s", flush=True)
    by_name = {r["name"]: r for r in rows}
    hits = [r for r in out if r.get("cost")]
    exact_hits = [r for r in hits if r["name"] == r.get("matched")]
    report = {"scanned": len(out), "seconds": round(time.time() - t0, 1),
              "any_cost": len(hits),
              "exact_hotel_cost": len(exact_hits),
              "hits": hits,
              "errors": sum(1 for r in out if r.get("error"))}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "hits"}, ensure_ascii=False, indent=1))
    for h in hits:
        print(f"  {h['name'][:34]:<36} cost={h['cost']:>7.1f} matched={h.get('matched')} type={h.get('type')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
