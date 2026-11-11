"""Chain-branch price estimation: use same-brand branches with a known price.

The user's point: for a chain, another branch's price is a much better estimate
than a generic class median. This script measures how many unknown hotels can
be covered that way before writing anything.

Brand matching is an explicit keyword list (Chinese + English), longest first.
Only `source_value` branches are used as donors; the estimate is the median,
range = min..max, status = `estimated_chain_branch`.
"""
from __future__ import annotations

import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOTELS = ROOT / "data/xian11_merged_sandbox/accommodations/xian/accommodations.csv"
OUT = ROOT / "results/chain_branch_analysis_20261111.json"

BRANDS = [
    # international
    "索菲特传奇", "索菲特", "威斯汀", "丽思卡尔顿", "万豪", "喜来登", "希尔顿欢朋", "希尔顿",
    "洲际", "皇冠假日", "假日酒店", "智选假日", "凯悦", "君悦", "柏悦", "香格里拉", "瑞吉",
    "康莱德", "华尔道夫", "温德姆", "戴斯", "豪生", "雅高", "美居", "宜必思", "诺富特",
    # domestic chains
    "汉庭", "如家", "7天", "锦江之星", "城市便捷", "全季", "桔子水晶", "桔子", "亚朵",
    "维也纳国际", "维也纳", "尚客优", "格林豪泰", "格林", "布丁", "oyo", "oyo",
    "尚俭太空舱", "易休太空舱", "易休", "太空舱", "木木夕", "梦想家", "青年旅舍",
    "途家", "斯维登", "泊寓", "自如", "城家", "窝趣", "魔方", "YOU+", "安歆",
    "丽枫", "喆啡", "希岸", "非繁", "潮漫", "ZMAX", "白玉兰", "锦江", "康铂", "凯里亚德",
    "派酒店", "轻住", "云酒店", "格林东方", "都市118", "银座佳驿", "驿家365", "7天优品",
]
BRANDS = sorted(set(b.lower() for b in BRANDS), key=len, reverse=True)


def brand_of(name: str, feature: str = "") -> str | None:
    text = f"{name} {feature}".lower()
    for b in BRANDS:
        if b in text:
            return b
    return None


def main() -> int:
    rows = list(csv.DictReader(open(HOTELS, encoding="utf-8-sig")))
    for r in rows:
        r["brand"] = brand_of(r["name"], r.get("featurehoteltype") or "")
        r["price_f"] = float(r["price"]) if float(r["price"]) > 0 else None

    known = defaultdict(list)
    for r in rows:
        if r["price_f"] and r["price_status"] == "source_value" and r["brand"]:
            known[r["brand"]].append(r["price_f"])

    unknown = [r for r in rows if r["price_status"] == "unknown"]
    coverable = [r for r in unknown if r["brand"] in known]
    no_brand = [r for r in unknown if not r["brand"]]
    brand_no_branch = [r for r in unknown if r["brand"] and r["brand"] not in known]

    print(f"rows={len(rows)} unknown={len(unknown)}")
    print(f"unknown with brand & known branches: {len(coverable)}")
    print(f"unknown with brand but no priced branch: {len(brand_no_branch)}")
    print(f"unknown without brand: {len(no_brand)}")
    print("\ncoverable by brand:")
    by_brand = Counter(r["brand"] for r in coverable)
    for b, n in by_brand.most_common(25):
        vals = known[b]
        print(f"  {b:<12} unknown={n:3d} donors={len(vals):2d} price_med={statistics.median(vals):.0f} "
              f"range={min(vals):.0f}-{max(vals):.0f}")

    # hostel targets specifically
    HOSTEL = ("青旅", "青年旅舍", "旅舍", "床位", "太空舱", "胶囊")
    print("\nremaining hostel targets:")
    for r in unknown:
        if any(k in r["name"] for k in HOSTEL):
            print(f"  {r['name']} brand={r['brand']} donors={known.get(r['brand'], [])}")

    report = {
        "unknown": len(unknown), "coverable": len(coverable),
        "brand_no_branch": len(brand_no_branch), "no_brand": len(no_brand),
        "by_brand": {b: {"unknown": n, "donors": len(known[b]),
                         "median": statistics.median(known[b]),
                         "min": min(known[b]), "max": max(known[b])}
                     for b, n in by_brand.items()},
        "examples": [{"name": r["name"], "brand": r["brand"],
                      "donors": known[r["brand"]]} for r in coverable[:30]],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
