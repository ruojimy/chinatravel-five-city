"""Adopt a Trip.com detail-page price for one hotel (live fetch, evidence saved).

Parses `minPrice` first, then `priceRange` ("由 CNY41 起"). Saves the HTML under
results/xian_gapfill_20261109/raw/hotel/<id>.html, updates the main table,
the provenance sidecar and the dynamic-price queue.

Usage:
  python scripts/adopt_trip_live_price.py --hotel "书友理想国..." --hotel-id 5982271
  python scripts/adopt_trip_live_price.py --hotel "..." --hotel-id 5982271 --apply
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data/xian11_merged_sandbox/accommodations/xian/accommodations.csv"
PROV = CSV_PATH.parent / "price_provenance.csv"
QUEUE = CSV_PATH.parent / "dynamic_price_queue.csv"
RAW_DIR = ROOT / "results/xian_gapfill_20261109/raw/hotel"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def fetch(hotel_id: str, checkin: str, checkout: str) -> tuple[str, dict]:
    url = (f"https://hk.trip.com/hotels/xi-an-hotel-detail-{hotel_id}/"
           f"?locale=zh-CN&curr=CNY&checkin={checkin}&checkout={checkout}")
    last = None
    resp = None
    for attempt in range(4):
        try:
            resp = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"},
                                timeout=30)
            resp.raise_for_status()
            break
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 + 2 * attempt)
    if resp is None:
        raise RuntimeError(f"trip.com fetch failed after retries: {last}")
    text = resp.text.replace('\\"', '"')
    price = None
    basis = None
    m = re.search(r'"minPrice"\s*:\s*([\d.]+)', text)
    if m:
        price, basis = float(m.group(1)), "minPrice"
    if price is None:
        m = re.search(r'priceRange"\s*:\s*"[^"]*?CNY\s*([\d.]+)', text) or \
            re.search(r"CNY\s*([\d.]+)\s*起", text)
        if m:
            price, basis = float(m.group(1)), "price_range_starting"
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw = RAW_DIR / f"{hotel_id}.html"
    raw.write_text(resp.text, encoding="utf-8")
    return url, {"price": price, "basis": basis, "raw_path": str(raw.relative_to(ROOT)).replace("\\", "/"),
                 "http": resp.status_code}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hotel", required=True)
    ap.add_argument("--hotel-id", required=True)
    ap.add_argument("--checkin", default="2026-11-20")
    ap.add_argument("--checkout", default="2026-11-21")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    url, got = fetch(args.hotel_id, args.checkin, args.checkout)
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    out = {"hotel": args.hotel, "url": url, **got, "checkin": args.checkin,
           "checkout": args.checkout, "observed_at": stamp}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if not args.apply or not got["price"]:
        return 0 if got["price"] else 1

    with CSV_PATH.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    target = next(r for r in rows if r["name"] == args.hotel)
    target["price"] = f"{got['price']:.1f}"
    target["price_status"] = "source_value"
    with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    if PROV.exists():
        with PROV.open(encoding="utf-8-sig", newline="") as fh:
            preader = csv.DictReader(fh)
            pfields = list(preader.fieldnames or [])
            prows = list(preader)
        for row in prows:
            if row["name"] == args.hotel:
                row.update(price=f"{got['price']:.1f}", price_status="source_value",
                           method=f"trip_com:{got['basis']}", observed_at=stamp,
                           source_url=url)
        with PROV.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=pfields)
            writer.writeheader()
            writer.writerows(prows)

    if QUEUE.exists():
        with QUEUE.open(encoding="utf-8-sig", newline="") as fh:
            qreader = csv.DictReader(fh)
            qfields = list(qreader.fieldnames or [])
            qrows = [r for r in qreader if r["name"] != args.hotel]
        with QUEUE.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=qfields)
            writer.writeheader()
            writer.writerows(qrows)
    print(json.dumps({"applied": args.hotel, "price": got["price"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
