"""Candidates for supplementing Xi'an hotel prices (no silent adoption).

For every hotel whose main-table price is the `-1` sentinel, apply the SAME
rule as `xian_estimate_fill.py` against the 240 OBSERVED prices:

  class      keyword(luxury/budget/mid) over featurehoteltype + name
  neighbours same class, <= 8 km, nearest 12
  interval   p25..p75, mid = p50
  confidence high if n>=8, medium if 4<=n<8, low if 1<=n<4

The leave-one-out calibration (`hotel_price_candidates.py`) shows p25-p75 only
covers ~44% of held-out prices, so this script ALSO exports a widened
`mid ± 60%` interval, whose bucket-wise coverage is 73.7-79.4%.

It writes `price_estimates_supplement.csv` only. It never edits the main table:
adoption is a separate, explicit decision.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from hotel_price_candidates import load, estimate  # noqa: E402

HOTELS = ROOT / "data/xian11_merged_sandbox/accommodations/xian/accommodations.csv"
OUT_CSV = HOTELS.parent / "price_estimates_supplement.csv"
OUT_JSON = ROOT / "results/hotel_price_supplement_20261111.json"
COVERAGE = {"4-7": 0.750, "8-11": 0.737, "12+": 0.794}


def bucket(n):
    return "12+" if n >= 12 else "8-11" if n >= 8 else "4-7" if n >= 4 else "1-3"


def main() -> int:
    rows = load()
    observed = [r for r in rows if r["price_status"] == "source_value"]
    unknown = [r for r in rows if r["price_status"] == "unknown"]

    out, counts = [], Counter()
    for target in unknown:
        e = estimate(target, observed)
        n = e["n"]
        if n == 0:
            counts["none"] += 1
            continue
        mid = e["mid"]
        low60, high60 = max(10, round(mid * 0.4 / 10) * 10), max(20, round(mid * 1.6 / 10) * 10)
        level = "high" if n >= 8 else "medium" if n >= 4 else "low"
        counts[level] += 1
        out.append({
            "name": target["name"], "hotel_class": target["class"],
            "n_comparables": n, "p25": round(e["low"], 1), "p75": round(e["high"], 1),
            "mid": round(mid, 1), "interval60_low": low60, "interval60_high": high60,
            "confidence_by_n": level,
            "calibrated_coverage_60": COVERAGE.get(bucket(n), "") if n >= 4 else "",
            "recommended": "adopt_as_estimated" if n >= 8 else
                           "ranking_only" if n < 4 else "adopt_with_caution",
        })
    out.sort(key=lambda r: (-r["n_comparables"], r["name"]))

    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        writer.writeheader()
        writer.writerows(out)

    report = {"unknown": len(unknown), "candidates": dict(counts),
              "adoptable_high_n8": counts.get("high", 0),
              "adoptable_any_n4": counts.get("high", 0) + counts.get("medium", 0),
              "note": "high = n>=8 comparables, not an accuracy guarantee; "
                      "interval60 is calibrated to ~74-79% coverage",
              "csv": str(OUT_CSV.relative_to(ROOT)).replace("\\", "/")}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
