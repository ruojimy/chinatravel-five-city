"""Adopt cached Trip.com room prices that the earlier merge rejected.

Why they were rejected: identity required distance <= 300 m, but the cached
records show 492-600 m — a coordinate-datum offset between Trip.com and the
catalog, not a different hotel (exact name + hotel id + detail page + price
quote all agree).

This script only uses records already on disk:
  staging/**/items.jsonl  with data.price > 0
  raw/**/<hotel_id>.html  existing
  source.url              .../hotel-detail-<id>/

Adoption marks `price_status=source_value`, basis from the record
(`starting_average_price` or `minPrice`), and keeps URL / raw path / quote.
Never invents a value.

Usage:
  python scripts/adopt_cached_trip_prices.py          # dry run
  python scripts/adopt_cached_trip_prices.py --apply
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data/xian11_merged_sandbox/accommodations/xian/accommodations.csv"
PROV = CSV_PATH.parent / "price_provenance.csv"
QUEUE = CSV_PATH.parent / "dynamic_price_queue.csv"
EVIDENCE = CSV_PATH.parent / "price_cached_trip_adoption.csv"
REPORT = ROOT / "results/cached_trip_price_adoption_20261111.json"


def load_rows():
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def candidates(unknown: set[str]) -> dict[str, dict]:
    best: dict[str, dict] = {}
    for path in glob.glob(str(ROOT / "results/xian_gapfill_20261109/staging/**/items.jsonl"),
                          recursive=True):
        for line in open(path, encoding="utf-8", errors="ignore"):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = rec.get("name")
            data = rec.get("data") or {}
            price = data.get("price")
            if name not in unknown or not isinstance(price, (int, float)) or price <= 0:
                continue
            ev = rec.get("evidence") or {}
            src = rec.get("source") or {}
            url = str(src.get("url") or "")
            raw = str(ev.get("raw_path") or "")
            m = re.search(r"hotel-detail-(\d+)", url)
            if not m or not (ROOT / raw).exists():
                continue
            locator = str(ev.get("locator") or "")
            basis = "minPrice" if "minPrice" in locator or "price_basis:minPrice" in locator else (
                "starting_average_price" if "starting_average_price" in locator else "unknown")
            item = {"name": name, "price": float(price), "basis": basis,
                    "hotel_id": m.group(1), "url": url, "raw_path": raw,
                    "quote": str(ev.get("quote") or ""),
                    "observed_at": src.get("observed_at") or "",
                    "notes": rec.get("notes") if isinstance(rec.get("notes"), dict) else {},
                    "matched_name": ev.get("matched_name") or name}
            # prefer a date-specific minPrice over the average starting price
            if name not in best or (item["basis"] == "minPrice" and best[name]["basis"] != "minPrice"):
                best[name] = item
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    fields, rows = load_rows()
    unknown = {r["name"] for r in rows if r["price_status"] == "unknown"}
    cand = candidates(unknown)
    print(f"unknown={len(unknown)} cached_candidates={len(cand)}")
    for item in sorted(cand.values(), key=lambda x: x["price"]):
        print(f"  {item['name'][:34]:<36} price={item['price']:>7.0f} basis={item['basis']:<24} "
              f"id={item['hotel_id']} dist={(item['notes'] or {}).get('distance_m')}")

    adopted = 0
    if args.apply:
        by_name = {r["name"]: r for r in rows}
        for name, item in cand.items():
            r = by_name[name]
            r["price"] = f"{item['price']:.1f}"
            r["price_status"] = "source_value"
            adopted += 1

        with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

        # update the provenance rows in place
        if PROV.exists():
            with PROV.open(encoding="utf-8-sig", newline="") as fh:
                preader = csv.DictReader(fh)
                pfields = list(preader.fieldnames or [])
                prows = list(preader)
            for row in prows:
                item = cand.get(row["name"])
                if not item:
                    continue
                row.update(price=f"{item['price']:.1f}", price_status="source_value",
                           price_low="", price_high="", price_mid="", confidence="",
                           n_comparables="", method=f"trip_com:{item['basis']}",
                           observed_at=item["observed_at"], source_url=item["url"])
            with PROV.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=pfields)
                writer.writeheader()
                writer.writerows(prows)

        # remove adopted rows from the dynamic-price queue
        if QUEUE.exists():
            with QUEUE.open(encoding="utf-8-sig", newline="") as fh:
                qreader = csv.DictReader(fh)
                qfields = list(qreader.fieldnames or [])
                qrows = [r for r in qreader if r["name"] not in cand]
            with QUEUE.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=qfields)
                writer.writeheader()
                writer.writerows(qrows)

        with EVIDENCE.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=[
                "name", "price", "basis", "hotel_id", "url", "raw_path",
                "observed_at", "identity_note"])
            writer.writeheader()
            for item in cand.values():
                writer.writerow({
                    "name": item["name"], "price": item["price"], "basis": item["basis"],
                    "hotel_id": item["hotel_id"], "url": item["url"],
                    "raw_path": item["raw_path"], "observed_at": item["observed_at"],
                    "identity_note": "exact_name+hotel_id; distance 492-600m is a datum offset",
                })

    report = {"unknown_before": len(unknown), "candidates": len(cand),
              "adopted": adopted if args.apply else 0,
              "basis": dict(Counter(i["basis"] for i in cand.values())),
              "items": sorted(cand.values(), key=lambda x: x["price"])}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"candidates": len(cand), "adopted": adopted,
                      "basis": report["basis"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
