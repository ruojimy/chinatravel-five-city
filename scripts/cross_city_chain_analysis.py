"""Cross-city chain donors: use same-brand branches in the other 10 cities.

Xi'an unknown hotels with a chain brand but no priced Xi'an branch can borrow
from the extended catalog (7,732 hotels across 10 cities). Donor prices are
normalized by the city's hotel median so a Beijing branch does not directly set
a Xi'an price.

Output: results/cross_city_chain_analysis_20261111.json (no writes).
"""
from __future__ import annotations

import csv
import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XIAN = ROOT / "data/xian11_merged_sandbox/accommodations/xian/accommodations.csv"
CATALOG = ROOT / "data/catalog_v1_1_20261022/catalog.sqlite3"
OUT = ROOT / "results/cross_city_chain_analysis_20261111.json"

BRANDS = [
    "希尔顿欢朋", "智选假日", "维也纳国际", "锦江之星", "城市便捷", "格林豪泰",
    "银座佳驿", "驿家365", "都市118", "凯里亚德", "喆啡", "丽枫", "希岸", "非繁",
    "潮漫", "白玉兰", "康铂", "轻住", "云酒店", "速8", "莫泰", "怡莱", "海友",
    "星程", "宜必思", "美居", "诺富特", "万怡", "福朋", "雅乐轩",
    "汉庭", "如家", "7天", "全季", "桔子", "亚朵", "维也纳", "尚客优", "布丁",
    "派酒店", "oyo", "索菲特", "威斯汀", "万豪", "希尔顿", "洲际", "凯悦",
]
BRANDS = sorted({b.lower() for b in BRANDS}, key=len, reverse=True)
EN_BRANDS = {
    "hilton": "希尔顿", "marriott": "万豪", "westin": "威斯汀", "sofitel": "索菲特",
    "holiday inn": "智选假日", "ibis": "宜必思", "novotel": "诺富特", "mercure": "美居",
    "hyatt": "凯悦", "intercontinental": "洲际", "hampton": "希尔顿欢朋",
}


def brand_of(name: str, en: str = "") -> str | None:
    text = f"{name} {en}".lower()
    for tok, label in EN_BRANDS.items():
        if tok in text:
            return label
    for b in BRANDS:
        if b in text:
            return b
    return None


def main() -> int:
    xian = list(csv.DictReader(open(XIAN, encoding="utf-8-sig")))
    for r in xian:
        r["price_f"] = float(r["price"]) if float(r["price"]) > 0 else None
        r["brand"] = brand_of(r["name"], r.get("hotelname_en") or "")
    xi_known = [r["price_f"] for r in xian if r["price_status"] == "source_value" and r["price_f"]]
    xi_med = statistics.median(xi_known)

    con = sqlite3.connect(f"file:{CATALOG.as_posix()}?mode=ro", uri=True)
    donors = []
    for city, payload in con.execute("select city,payload from records where kind='accommodation'"):
        d = json.loads(payload).get("data") or {}
        name, en, price = d.get("name"), d.get("hotelname_en") or "", d.get("price")
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        donors.append({"city": city, "name": name, "price": price,
                       "brand": brand_of(name or "", en)})
    con.close()

    city_med = {}
    by_city = defaultdict(list)
    for d in donors:
        by_city[d["city"]].append(d["price"])
    for c, vals in by_city.items():
        city_med[c] = statistics.median(vals)
    print(f"catalog donors={len(donors)} cities={len(city_med)} xi_median={xi_med:.0f}")
    print("city medians:", {c: round(v) for c, v in sorted(city_med.items())})

    unknown = [r for r in xian if r["price_status"] == "unknown"]
    brand_unknown = [r for r in unknown if r["brand"]]
    print(f"unknown={len(unknown)} with_brand={len(brand_unknown)}")

    by_brand = defaultdict(list)
    for d in donors:
        if d["brand"]:
            by_brand[d["brand"]].append(d)

    rows = []
    for r in brand_unknown:
        ds = by_brand.get(r["brand"], [])
        if not ds:
            continue
        norm = [d["price"] * xi_med / city_med[d["city"]] for d in ds]
        rows.append({
            "name": r["name"], "brand": r["brand"], "n_donors": len(ds),
            "cities": dict(Counter(d["city"] for d in ds)),
            "raw_median": statistics.median(d["price"] for d in ds),
            "norm_median": statistics.median(norm),
            "norm_range": [min(norm), max(norm)],
            "examples": [(d["city"], d["name"], d["price"]) for d in ds[:3]],
        })
    rows.sort(key=lambda x: -x["n_donors"])
    for row in rows[:30]:
        print(f"  {row['name'][:30]:<32} brand={row['brand']:<8} donors={row['n_donors']:3d} "
              f"raw_med={row['raw_median']:>6.0f} norm_med={row['norm_median']:>6.0f} cities={row['cities']}")

    report = {"xi_median": xi_med, "city_medians": city_med,
              "unknown": len(unknown), "with_brand": len(brand_unknown),
              "coverable": len(rows), "rows": rows}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\ncoverable={len(rows)} wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
