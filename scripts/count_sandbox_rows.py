"""Count sandbox rows per city (attractions / restaurants / accommodations) and
write a markdown table to notes/sandbox_counts.md."""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "ChinaTravel/chinatravel/environment/database"
OUT = ROOT / "notes/sandbox_counts.md"

CITY_CN = {
    "beijing": "北京", "chengdu": "成都", "chongqing": "重庆", "guangzhou": "广州",
    "hangzhou": "杭州", "nanjing": "南京", "shanghai": "上海", "shenzhen": "深圳",
    "suzhou": "苏州", "wuhan": "武汉",
}


def count(path: Path) -> int:
    with open(path, encoding="utf-8-sig") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def main() -> int:
    rows = []
    for slug, cn in CITY_CN.items():
        attraction = DB / "attractions" / slug / "attractions.csv"
        restaurant = DB / "restaurants" / slug / f"restaurants_{slug}.csv"
        hotel = DB / "accommodations" / slug / "accommodations.csv"
        poi = DB / "poi" / slug / "poi.json"
        import json
        poi_n = len(json.loads(poi.read_text(encoding="utf-8"))) if poi.exists() else 0
        rows.append({
            "city": cn,
            "attractions": count(attraction) if attraction.exists() else 0,
            "restaurants": count(restaurant) if restaurant.exists() else 0,
            "hotels": count(hotel) if hotel.exists() else 0,
            "poi": poi_n,
        })

    header = "| 城市 | 景点 | 餐厅 | 酒店 | POI 节点 | 小计（景点+餐厅+酒店） |\n| --- | ---: | ---: | ---: | ---: | ---: |\n"
    lines = [header]
    for row in rows:
        total = row["attractions"] + row["restaurants"] + row["hotels"]
        lines.append(f"| {row['city']} | {row['attractions']} | {row['restaurants']} | "
                     f"{row['hotels']} | {row['poi']} | {total} |")
    sums = {key: sum(row[key] for row in rows) for key in ("attractions", "restaurants", "hotels", "poi")}
    n = len(rows)
    lines.append(f"| **合计** | **{sums['attractions']}** | **{sums['restaurants']}** | "
                 f"**{sums['hotels']}** | **{sums['poi']}** | "
                 f"**{sums['attractions'] + sums['restaurants'] + sums['hotels']}** |")
    lines.append(f"| **每城均值** | {sums['attractions'] / n:.0f} | {sums['restaurants'] / n:.0f} | "
                 f"{sums['hotels'] / n:.0f} | {sums['poi'] / n:.0f} | "
                 f"{(sums['attractions'] + sums['restaurants'] + sums['hotels']) / n:.0f} |")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("sums:", sums, "cities:", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
