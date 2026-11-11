"""Build a stratified 40-POI sample for TAG collection, straight from the sandbox.

Stratification follows the task spec: several cities, several themes (sandbox
``type``), several price bands and both high- and low-recognition venues. The
sample is a *plan*: it lists what should be fetched. Which of them actually have
evidence is decided by the collector, never by hope.

Writes datasets/tag_sample/pois.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.env import get_env  # noqa: E402

OUT = ROOT / "datasets" / "tag_sample" / "pois.json"
CITIES = ["广州", "上海", "北京", "杭州", "成都", "南京", "重庆", "武汉", "苏州"]
PER_CITY = 5  # 45 attempts, print 40 usable


def main() -> int:
    env = get_env("zh")
    rows: list[dict] = []
    for city in CITIES:
        try:
            table = env.attraction_table(city)
        except Exception as exc:  # noqa: BLE001
            print(f"{city}: skip ({exc})")
            continue
        if table is None or table.empty:
            continue
        frame = table.copy()
        # A-level venues first (cheap signal of "notable"), then price spread.
        frame["price"] = frame["price"].astype(float)
        frame = frame.sort_values(["price", "name"])
        picked = []
        # one free/cheap, one mid, one expensive, two most expensive named venues
        bands = [(0.0, 0.0), (0.01, 80.0), (80.01, 1e9)]
        for low, high in bands:
            subset = frame[(frame["price"] >= low) & (frame["price"] <= high)]
            if not subset.empty:
                picked.append(subset.iloc[len(subset) // 2])
        picked += [frame.iloc[-1], frame.iloc[-2]] if len(frame) >= 2 else []
        for row in picked:
            rows.append({
                "local_poi_id": f"sandbox:{city}:{row['name']}",
                "city": city,
                "name": str(row["name"]),
                "type": str(row["type"]),
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "price": float(row["price"]),
                "opentime": str(row["opentime"]),
                "endtime": str(row["endtime"]),
                "recommendmintime": float(row["recommendmintime"]),
                "sample_reason": f"city={city};price_band={row['price']};type={row['type']}",
            })

    # Guarantee that the venues we already hold a captured Baidu response for are
    # in the sample, otherwise the replay-mode run would exercise nothing. Marked
    # so the report can separate "sampled" from "forced-in for coverage".
    forced: list[dict] = []
    for city, name in (("广州", "广州塔"), ("北京", "故宫博物院")):
        table = env.attraction_table(city)
        match = table[table["name"].astype(str) == name]
        if match.empty:
            print(f"  WARN forced POI not in sandbox: {city} {name}")
            continue
        row = match.iloc[0]
        forced.append({
            "local_poi_id": f"sandbox:{city}:{name}",
            "city": city,
            "name": name,
            "type": str(row["type"]),
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "price": float(row["price"]),
            "opentime": str(row["opentime"]),
            "endtime": str(row["endtime"]),
            "recommendmintime": float(row["recommendmintime"]),
            "sample_reason": f"city={city};fixture_covered(forced)",
        })

    seen = {row["local_poi_id"] for row in forced}
    unique: list[dict] = list(forced)
    for row in rows:
        if row["local_poi_id"] in seen:
            continue
        seen.add(row["local_poi_id"])
        unique.append(row)
    unique = unique[:42]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": "2026-10-21",
        "n": len(unique),
        "cities": sorted({row["city"] for row in unique}),
        "types": sorted({row["type"] for row in unique}),
        "price_range": [min(row["price"] for row in unique), max(row["price"] for row in unique)],
        "note": "分层抽样计划：多城市 × 多类型 × 多价位；实际可取证数量由采集器决定，不预设",
        "pois": unique,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT} n={len(unique)} cities={len(payload['cities'])} types={len(payload['types'])}")
    for row in unique[:8]:
        print("  ", row["city"], row["name"], row["price"], row["type"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
