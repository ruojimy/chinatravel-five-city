"""Merge gap-fill item files into one validated enrich batch.

- normalises 00:00-24:00 closing time to endtime 23:59 (documented approximation)
- de-duplicates per (kind, name, field), keeping the higher-authority source
- keeps one evidence record per emitted item (never mixes sources)
- writes conflicts and a per-field summary
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "results" / "xian_gapfill_20261109"
SOURCES = [
    RUN / "staging/recovery/items.jsonl",
    RUN / "staging/food/items.jsonl",
    RUN / "staging/hotel/items.jsonl",
    RUN / "staging/hotel2/items.jsonl",
    RUN / "staging/transport/items.jsonl",
]
RANK = {
    "government_published_list": 100,
    "municipal_culture_tourism_bureau_public_table": 95,
    "carrier_published_schedule": 90,
    "airport_official_schedule": 88,
    "public_timetable": 85,
    "amap_place_api": 80,
    "baidu_place_api": 78,
    "travel_marketplace_display": 60,
    "provider_snapshot": 60,
    "community_structured_data": 50,
    "historical_reference": 30,
}


def rank(item: dict) -> int:
    return RANK.get((item.get("source") or {}).get("authority"), 40)


def main() -> int:
    owner: dict[tuple[str, str, str], dict] = {}
    conflicts = []
    counts = Counter()
    added_24h = 0
    emitted: dict[int, dict] = {}

    for path in SOURCES:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            data = dict(item.get("data") or {})
            quote = (item.get("evidence") or {}).get("quote") or ""
            if (item.get("kind") == "attraction" and "opentime" in data
                    and "endtime" not in data and "24:00" in quote):
                data["endtime"] = "23:59"
                item["notes"] = ((item.get("notes") or "") + " | 24h_close_normalized_24:00_to_23:59").strip(" |")
                added_24h += 1

            keep = {}
            for field, value in data.items():
                key = (item["kind"], item["name"], field)
                counts[(item["kind"], field)] += 1
                if key not in owner:
                    owner[key] = {"value": value, "rank": rank(item), "url": (item.get("source") or {}).get("url")}
                    keep[field] = value
                    continue
                prev = owner[key]
                if prev["value"] == value:
                    continue
                if rank(item) > prev["rank"]:
                    conflicts.append({"key": list(key), "kept": value, "dropped": prev["value"],
                                      "kept_url": (item.get("source") or {}).get("url"), "dropped_url": prev["url"]})
                    owner[key] = {"value": value, "rank": rank(item), "url": (item.get("source") or {}).get("url")}
                    keep[field] = value
                else:
                    conflicts.append({"key": list(key), "kept": prev["value"], "dropped": value,
                                      "kept_url": prev["url"], "dropped_url": (item.get("source") or {}).get("url")})
            if keep:
                out = dict(item)
                out["data"] = keep
                emitted[id(out)] = out

    out_dir = RUN / "staging/merged"
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(item, ensure_ascii=False) for item in emitted.values()]
    (out_dir / "items.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "conflicts.json").write_text(json.dumps(conflicts, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    summary = {
        "items": len(emitted),
        "fields": len(owner),
        "added_24h_endtime": added_24h,
        "by_kind_field": {f"{k[0]}.{k[1]}": v for k, v in sorted(counts.items())},
        "conflicts": len(conflicts),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
