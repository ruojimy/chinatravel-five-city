"""Split Xi'an hotel prices into observed / estimated / unknown and export it.

The planning table stores ONE number:
  - observed  -> the observed price
  - estimated -> the **midpoint** of an interval (never the interval itself)
  - unknown   -> sentinel `-1` (the loader's `dropna()` forbids empty cells)

The interval only lived in the internal v17 `hotel_price_estimates` table, and
the CSV had no marker. This script makes the status explicit and accessible:

  1. adds `price_status` to `accommodations.csv`
     (source_value / estimated / unknown), every row filled
  2. writes `price_provenance.csv` with low/high/mid, confidence, method,
     n_comparables and the observation time
  3. writes `dynamic_price_queue.csv` with the hotels still missing a price

Status is taken from the v17 payload's `field_provenance.price.status`
(authoritative); the estimate table only supplies the interval.

Usage:
  .venv/Scripts/python.exe -B -X utf8 scripts/export_hotel_price_provenance.py
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOTELS = ROOT / "data/xian11_merged_sandbox/accommodations/xian/accommodations.csv"
PROV = HOTELS.parent / "price_provenance.csv"
QUEUE = HOTELS.parent / "dynamic_price_queue.csv"
SNAP = ROOT / "results/xian_gapfill_20261109/snapshot_v17/catalog.sqlite3"
REPORT = ROOT / "results/hotel_price_provenance_20261111.json"

PUNCT = re.compile(r"[\s\u3000·•・\-—–_()（）\[\]【】{}<>《》\"'“”‘’,，.。;；:：!！?？/\\|]+")


def norm(s):
    return PUNCT.sub("", unicodedata.normalize("NFKC", str(s or "")).strip().lower())


def core(s):
    t = unicodedata.normalize("NFKC", str(s or "")).strip()
    t = re.sub(r"[（(].*?[)）]", "", t)
    t = re.split(r"\s+[A-Za-z]", t, maxsplit=1)[0]
    return norm(t)


def num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def main() -> int:
    if not SNAP.exists():
        raise SystemExit(f"missing snapshot {SNAP}")
    con = sqlite3.connect(f"file:{SNAP.as_posix()}?mode=ro", uri=True)

    def load(sql):
        out = {}
        for row in con.execute(sql):
            out[row[0]] = row[1:]
        return out

    v17_status = {}
    v17_price = {}
    v17_url = {}
    for (payload,) in con.execute(
            "select payload from records where kind='accommodation' and city='西安'"):
        d = json.loads(payload)
        name = (d.get("data") or {}).get("name")
        fp = (d.get("field_provenance") or {}).get("price") or {}
        v17_status[name] = fp.get("status")
        v17_price[name] = num((d.get("data") or {}).get("price"))
        v17_url[name] = d.get("source_url")
    observations = load("select hotel_name, price, observed_at, source_url "
                        "from hotel_price_observations order by observed_at")
    estimates = {name: {"low": num(low), "high": num(high), "mid": num(mid),
                        "confidence": conf, "n_comparables": n, "method": method,
                        "adopted": bool(adopted)}
                 for name, low, high, mid, conf, n, method, adopted in con.execute(
                     "select hotel_name, low, high, mid, confidence, n_comparables, "
                     "method, adopted from hotel_price_estimates")}
    con.close()

    by_core_status = {}
    for name, status in v17_status.items():
        by_core_status.setdefault(core(name), status)

    with HOTELS.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if "price_status" not in fields:
        fields.append("price_status")

    counts = Counter()
    provenance_rows, queue_rows = [], []
    for row in rows:
        name = row.get("name", "")
        price = num(row.get("price"))
        status = v17_status.get(name) or by_core_status.get(core(name))
        if status is None:
            status = "unknown" if price is None or price <= 0 else "legacy_unverified"
        if price is None or price <= 0:
            status = "unknown"
        row["price_status"] = status

        rec = {"name": name, "price": "" if status == "unknown" else price,
               "price_status": status, "price_low": "", "price_high": "",
               "price_mid": "", "confidence": "", "n_comparables": "", "method": "",
               "observed_at": "", "source_url": ""}
        if status == "estimated":
            est = estimates.get(name) or next(
                (e for n, e in estimates.items() if core(n) == core(name)), None)
            if est:
                rec.update(price_low=est["low"], price_high=est["high"],
                           price_mid=est["mid"], confidence=est["confidence"],
                           n_comparables=est["n_comparables"], method=est["method"])
            counts["estimated_mid_mismatch"] += bool(
                est and est["mid"] is not None and price is not None
                and abs(price - est["mid"]) > 0.01)
        elif status == "source_value":
            obs = observations.get(name) or next(
                (o for n, o in observations.items() if core(n) == core(name)), None)
            if obs:
                rec.update(observed_at=obs[1], source_url=obs[2] or v17_url.get(name) or "")
            else:
                rec["source_url"] = v17_url.get(name) or ""
        elif status == "unknown":
            queue_rows.append({"name": name, "hotelname_en": row.get("hotelname_en", ""),
                               "lat": row.get("lat", ""), "lon": row.get("lon", "")})
        provenance_rows.append(rec)
        counts[status] += 1

    with HOTELS.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    with PROV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "name", "price", "price_status", "price_low", "price_high", "price_mid",
            "confidence", "n_comparables", "method", "observed_at", "source_url"])
        writer.writeheader()
        writer.writerows(provenance_rows)

    with QUEUE.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["name", "hotelname_en", "lat", "lon"])
        writer.writeheader()
        writer.writerows(queue_rows)

    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "hotels": len(rows), "status": {k: v for k, v in counts.items() if k != "estimated_mid_mismatch"},
              "estimated_mid_mismatch": counts.get("estimated_mid_mismatch", 0),
              "queue": len(queue_rows),
              "note": "estimated rows store the interval midpoint in price; "
                      "the interval is in price_provenance.csv"}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
