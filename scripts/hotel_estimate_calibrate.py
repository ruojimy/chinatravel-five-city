"""Leave-one-out calibration for accommodation price estimates.

For every hotel that has a real observed price, hide it, rebuild the interval
with exactly the production rule (same class, <=8km, 12 nearest, p25-p75),
then check whether the hidden real price falls inside the interval.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from xian_estimate_fill import BUDGET, LUX, dist, hotel_class, pct  # noqa: E402


def main() -> int:
    snap = Path(sys.argv[1] if len(sys.argv) > 1 else
                "results/xian_gapfill_20261109/snapshot_v12/catalog.sqlite3")
    con = sqlite3.connect(str(snap))
    rows = []
    for name, pl in con.execute("select name,payload from records where city='西安' and kind='accommodation'"):
        p = json.loads(pl)
        d = p["data"]
        prov = p["field_provenance"]["price"]
        if prov.get("status") != "source_value":
            continue
        try:
            price = float(d["price"])
            lat, lon = float(d["lat"]), float(d["lon"])
        except (TypeError, ValueError, KeyError):
            continue
        rows.append({"name": name, "price": price, "lat": lat, "lon": lon,
                     "class": hotel_class(name, d.get("featurehoteltype"))})

    stats = {"in_base": 0, "in_widened": 0, "n": 0, "abs_err": [], "rel_err": []}
    by_class = defaultdict(lambda: {"n": 0, "in_base": 0, "in_widened": 0, "rel": []})
    by_band = defaultdict(lambda: {"n": 0, "in_base": 0, "in_widened": 0})
    misses = []

    for i, target in enumerate(rows):
        pool = [r for j, r in enumerate(rows) if j != i and r["class"] == target["class"]]
        cands = []
        for r in pool:
            dd = dist(target["lat"], target["lon"], r["lat"], r["lon"])
            if dd <= 8000:
                cands.append((dd, r["price"]))
        cands.sort()
        near = [v for _, v in cands[:12]]
        if len(near) >= 4:
            low, high, mid = pct(near, 0.25), pct(near, 0.75), pct(near, 0.5)
            if len(near) < 8:
                low, high = low * 0.85, high * 1.15
        else:
            vals = [r["price"] for r in pool]
            if len(vals) < 3:
                continue
            low, high, mid = pct(vals, 0.25), pct(vals, 0.75), pct(vals, 0.5)

        base_hit = low <= target["price"] <= high
        w_low, w_high = low * 0.75, high * 1.25
        wide_hit = w_low <= target["price"] <= w_high
        stats["n"] += 1
        stats["in_base"] += base_hit
        stats["in_widened"] += wide_hit
        ae = abs(mid - target["price"])
        re = ae / target["price"]
        stats["abs_err"].append(ae)
        stats["rel_err"].append(re)

        c = by_class[target["class"]]
        c["n"] += 1
        c["in_base"] += base_hit
        c["in_widened"] += wide_hit
        c["rel"].append(re)

        band = "<=100" if target["price"] <= 100 else "101-200" if target["price"] <= 200 \
            else "201-400" if target["price"] <= 400 else ">400"
        by_band[band]["n"] += 1
        by_band[band]["in_base"] += base_hit
        by_band[band]["in_widened"] += wide_hit

        if not wide_hit:
            miss = target["price"] / mid if mid else 0
            misses.append((round(miss, 2), target["name"], target["price"],
                           round(low), round(high), round(mid), len(near)))

    def rate(a, b):
        return round(a / b * 100, 1) if b else None

    print(json.dumps({
        "snapshot": str(snap),
        "holdout_n": stats["n"],
        "in_base_interval_pct": rate(stats["in_base"], stats["n"]),
        "in_widened_interval_pct": rate(stats["in_widened"], stats["n"]),
        "median_abs_error_yuan": round(pct(stats["abs_err"], 0.5), 0),
        "median_rel_error_pct": round(pct(stats["rel_err"], 0.5) * 100, 1),
        "p90_rel_error_pct": round(pct(stats["rel_err"], 0.9) * 100, 1),
        "by_class": {k: {"n": v["n"], "in_base": rate(v["in_base"], v["n"]),
                         "in_widened": rate(v["in_widened"], v["n"]),
                         "median_rel_pct": round(pct(v["rel"], 0.5) * 100, 1)}
                     for k, v in sorted(by_class.items())},
        "by_price_band": {k: {"n": v["n"], "in_base": rate(v["in_base"], v["n"]),
                              "in_widened": rate(v["in_widened"], v["n"])}
                          for k, v in sorted(by_band.items())},
        "worst_misses": sorted(misses, reverse=True)[:10],
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
