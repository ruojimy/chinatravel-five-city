"""Convert a hotel per-capita reference into a room-price reference.

There is no empirical paired sample in our data (Amap/Baidu hotel POIs do not
carry a per-capita), so the factor is explicit and overridable:

  basis=double (default)  ordinary hotel: x2  (per-capita assumed to be for 2 people)
                          hostel/dorm:    x1  (per bed)
  basis=per_person        factor = bed count of the room (1/2/3), from room_types
                          or `numbed`; hostel -> 1

Output is always labelled `reference_per_capita` with a +/-25% range and a
confidence. It is NOT a source price and should never be written as
`price_status=source_value`.

Usage:
  python scripts/per_capita_to_room_price.py --hotel "西安W酒店" --per-capita 436
  python scripts/per_capita_to_room_price.py --batch candidates.csv --basis double
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "results/xian_gapfill_20261109/snapshot_v17/catalog.sqlite3"
HOTELS = ROOT / "data/xian11_merged_sandbox/accommodations/xian/accommodations.csv"
HOSTEL = ("青旅", "青年旅舍", "旅舍", "床位", "太空舱", "胶囊")


def hotel_row(name: str) -> dict:
    with HOTELS.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["name"] == name:
                return row
    return {}


def room_beds(name: str) -> int | None:
    if not SNAP.exists():
        return None
    con = sqlite3.connect(f"file:{SNAP.as_posix()}?mode=ro", uri=True)
    row = con.execute(
        "select min(bed_count) from room_types where hotel_name=? and bed_count is not null",
        (name,)).fetchone()
    con.close()
    return int(row[0]) if row and row[0] else None


def convert(name: str, per_capita: float, basis: str) -> dict:
    row = hotel_row(name)
    beds = room_beds(name) or (int(float(row["numbed"])) if row.get("numbed") else None)
    is_hostel = any(k in name for k in HOSTEL)
    if is_hostel:
        factor, why = 1.0, "hostel_per_bed"
    elif basis == "per_person":
        factor, why = float(max(1, beds or 1)), "room_bed_count"
    else:
        factor, why = 2.0, "double_occupancy"
    price = per_capita * factor
    return {
        "hotel": name, "per_capita": per_capita, "basis": basis,
        "factor": factor, "basis_reason": why, "beds": beds,
        "room_price_reference": round(price),
        "range": [round(price * 0.75), round(price * 1.25)],
        "price_status": "reference_per_capita",
        "confidence": "low" if not beds else "medium",
        "note": "assumption-based conversion; validate on paired data before adoption",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hotel")
    ap.add_argument("--per-capita", type=float)
    ap.add_argument("--basis", choices=["double", "per_person"], default="double")
    ap.add_argument("--batch", help="CSV with columns name,per_capita")
    ap.add_argument("--out")
    args = ap.parse_args()

    if args.batch:
        rows = list(csv.DictReader(open(args.batch, encoding="utf-8-sig")))
        out = [convert(r["name"], float(r["per_capita"]), args.basis) for r in rows]
        target = Path(args.out) if args.out else Path(args.batch).with_name("room_price_reference.csv")
        with target.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
            writer.writeheader()
            writer.writerows(out)
        print(json.dumps({"converted": len(out), "out": str(target)}, ensure_ascii=False))
        return 0

    if not args.hotel or args.per_capita is None:
        print(json.dumps({"error": "--hotel and --per-capita required"}, ensure_ascii=False))
        return 2
    print(json.dumps(convert(args.hotel, args.per_capita, args.basis),
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
