"""Fill restaurant prices from Amap `business.cost` (per-capita).

Restaurant `price` in ChinaTravel is per-person (`cost = price * people`), so
Amap's per-capita `cost` is the same unit. Two modes:
  --validate N   compare Amap cost with N existing prices (no writes)
  --apply        fill the `-1` rows, writing a provenance sidecar

Only exact-name matches with 5 <= cost <= 2000 are accepted. A sidecar
`restaurant_price_provenance.csv` records source=amap, matched name, cost and
timestamp; the main table keeps its 9 columns.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data/xian11_merged_sandbox/restaurants/xian/restaurants_xian.csv"
PROV = CSV_PATH.parent / "restaurant_price_provenance.csv"
REPORT = ROOT / "results/restaurant_price_fill_20261111.json"
UA = "ShortTripAssistant/1.0 (restaurant price fill)"


def amap_key() -> str:
    return (ROOT / ".secrets/amap.key").read_text(encoding="ascii").strip()


def amap_cost(name: str) -> dict:
    params = {"key": amap_key(), "keywords": name, "region": "西安",
              "city_limit": "true", "show_fields": "business",
              "page_size": "3", "page": "1"}
    url = "https://restapi.amap.com/v5/place/text?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    pois = body.get("pois") or []
    best = next((p for p in pois if p.get("name") == name), None)
    cost = None
    if best:
        raw = ((best.get("business") or {}).get("cost") or "").strip()
        try:
            cost = float(raw)
        except ValueError:
            cost = None
    return {"status": body.get("status"), "matched": (best or {}).get("name"),
            "cost": cost, "poi_type": (best or {}).get("type")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.35)
    args = ap.parse_args()

    with CSV_PATH.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)

    priced = [r for r in rows if float(r["price"]) > 0]
    missing = [r for r in rows if float(r["price"]) <= 0]
    report = {"total": len(rows), "priced": len(priced), "missing": len(missing)}

    if args.validate:
        step = max(1, len(priced) // args.validate)
        sample = priced[::step][: args.validate]
        ratios, hits, got = [], 0, 0
        for r in sample:
            try:
                a = amap_cost(r["name"])
            except Exception as exc:  # noqa: BLE001
                a = {"error": f"{type(exc).__name__}: {exc}"}
            if a.get("cost"):
                got += 1
                ratio = a["cost"] / float(r["price"])
                ratios.append(ratio)
                hits += 0.7 <= ratio <= 1.3
            time.sleep(args.sleep)
        ratios.sort()
        report["validation"] = {
            "sample": len(sample), "amap_cost_present": got,
            "within_30pct": hits,
            "median_ratio": round(ratios[len(ratios) // 2], 2) if ratios else None,
            "p10_ratio": round(ratios[len(ratios) // 10], 2) if ratios else None,
            "p90_ratio": round(ratios[9 * len(ratios) // 10], 2) if ratios else None,
        }
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0

    if not args.apply:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0

    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    prov_rows, filled, failed = [], 0, []
    for r in missing:
        try:
            a = amap_cost(r["name"])
        except Exception as exc:  # noqa: BLE001
            a = {"error": f"{type(exc).__name__}: {exc}"}
        ok = (a.get("matched") == r["name"] and a.get("cost") is not None
              and 5 <= a["cost"] <= 2000)
        if ok:
            r["price"] = f"{a['cost']:.1f}"
            filled += 1
            prov_rows.append({"name": r["name"], "price": r["price"],
                              "price_status": "source_value", "source": "amap_v5_place_text",
                              "matched_name": a["matched"], "observed_at": stamp,
                              "poi_type": a.get("poi_type") or ""})
        else:
            failed.append({"name": r["name"], "matched": a.get("matched"),
                           "cost": a.get("cost"), "error": a.get("error")})
        report["filled"] = filled
        report["failed"] = len(failed)
        report["failed_sample"] = failed[:10]
        time.sleep(args.sleep)

    with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with PROV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["name", "price", "price_status", "source",
                                               "matched_name", "observed_at", "poi_type"])
        writer.writeheader()
        writer.writerows(prov_rows)
    report["provenance"] = str(PROV.relative_to(ROOT)).replace("\\", "/")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
