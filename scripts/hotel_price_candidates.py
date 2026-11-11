"""How the comparable-price interval is built, and who else could be added.

Reproduces the exact rule from `xian_estimate_fill.py`:
  class = keyword(luxury / budget / mid) over featurehoteltype + name
  comparables = same-class hotels with an OBSERVED price, within 8 km
  interval = p25..p75 of the nearest <=12 comparables, mid = p50
  confidence = high if n>=8, medium if 4<=n<8, low otherwise

Then:
  A. leave-one-out on the 240 observed prices -> does "high" actually cover?
  B. for the 388 unknown hotels -> how many would reach high/medium/low?
"""
from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOTELS = ROOT / "data/xian11_merged_sandbox/accommodations/xian/accommodations.csv"
OUT = ROOT / "results/hotel_price_candidate_analysis.json"

LUX = ("威斯汀", "索菲特", "丽思", "万豪", "希尔顿", "洲际", "皇冠", "凯宾", "悦榕", "香格里拉",
       "瑞吉", "康莱德", "华尔道夫", "柏悦", "君悦", "凯悦", "四季", "温德姆", "豪生", "戴斯",
       "华邑", "传奇", "五星", "豪华", "泳池", "行政酒廊")
BUDGET = ("宾馆", "旅馆", "招待所", "青旅", "青年旅舍", "民宿", "公寓", "客栈", "快捷", "连锁",
          "OYO", "7天", "如家", "汉庭", "锦江之星", "城市便捷", "家庭旅馆", "旅社")


def hotel_class(name, feature):
    text = f"{feature or ''} {name or ''}"
    if any(t in text for t in LUX):
        return "luxury"
    if any(t in text for t in BUDGET):
        return "budget"
    return "mid"


def pct(values, q):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def dist(a, b, c, d):
    dx = (a - c) * 111320 * math.cos(math.radians((b + d) / 2))
    dy = (b - d) * 110540
    return math.hypot(dx, dy)


def load():
    rows = list(csv.DictReader(open(HOTELS, encoding="utf-8-sig")))
    for r in rows:
        r["price_f"] = float(r["price"])
        r["lat_f"], r["lon_f"] = float(r["lat"]), float(r["lon"])
        r["class"] = hotel_class(r["name"], r.get("featurehoteltype"))
    return rows


def estimate(target, pool, k=12):
    cands = []
    for p in pool:
        if p["class"] != target["class"] or p is target:
            continue
        d = dist(target["lat_f"], target["lon_f"], p["lat_f"], p["lon_f"])
        if d <= 8000:
            cands.append((d, p["price_f"]))
    cands.sort()
    near = [v for _, v in cands[:k]]
    if not near:
        return {"n": 0, "low": None, "high": None, "mid": None}
    return {"n": len(near), "low": pct(near, 0.25), "high": pct(near, 0.75),
            "mid": pct(near, 0.5)}


def main() -> int:
    rows = load()
    observed = [r for r in rows if r["price_status"] == "source_value"]
    unknown = [r for r in rows if r["price_status"] == "unknown"]
    print(f"observed {len(observed)}  unknown {len(unknown)}")

    # A. leave-one-out calibration of the exact rule
    buckets = defaultdict(lambda: {"n": 0, "covered": 0, "ape": []})
    for target in observed:
        e = estimate(target, observed)
        if e["n"] == 0:
            key = "0"
        elif e["n"] >= 8:
            key = ">=8 (high)"
        elif e["n"] >= 4:
            key = "4-7 (medium)"
        else:
            key = "1-3 (low)"
        b = buckets[key]
        b["n"] += 1
        if e["low"] is not None and e["low"] <= target["price_f"] <= e["high"]:
            b["covered"] += 1
        if e["mid"]:
            b["ape"].append(abs(target["price_f"] - e["mid"]) / target["price_f"])
    calibration = {}
    for key, b in sorted(buckets.items()):
        ape = sorted(b["ape"])
        calibration[key] = {
            "n": b["n"],
            "coverage_p25_p75": round(100 * b["covered"] / b["n"], 1),
            "median_ape": round(100 * (ape[len(ape) // 2] if ape else 0), 1),
        }
    print("\nleave-one-out calibration (p25-p75 interval):")
    for key, v in calibration.items():
        print(f"  {key:<14} n={v['n']:3d} coverage={v['coverage_p25_p75']:5.1f}%  median|err|={v['median_ape']:4.1f}%")

    # B. unknown hotels against the observed pool
    cand = Counter()
    examples = defaultdict(list)
    for target in unknown:
        e = estimate(target, observed)
        if e["n"] >= 8:
            key = "high"
        elif e["n"] >= 4:
            key = "medium"
        elif e["n"] >= 1:
            key = "low"
        else:
            key = "none"
        cand[key] += 1
        if len(examples[key]) < 5:
            examples[key].append({"name": target["name"], "class": target["class"],
                                  "n": e["n"], "mid": e["mid"],
                                  "range": [e["low"], e["high"]]})
    print("\nunknown 388 hotels, same rule:")
    for key in ("high", "medium", "low", "none"):
        print(f"  {key:<7} {cand[key]:3d}")

    report = {"observed": len(observed), "unknown": len(unknown),
              "calibration": calibration, "candidates": dict(cand),
              "examples": dict(examples),
              "rule": {"class": "keyword luxury/budget/mid",
                       "radius_km": 8, "nearest": 12,
                       "interval": "p25-p75", "mid": "p50",
                       "high": "n>=8", "medium": "4<=n<8", "low": "n<4"}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
