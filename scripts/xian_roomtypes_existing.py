"""Parse already-captured Trip.com hotel detail pages into room-type rows."""
from __future__ import annotations

import json
import re
from pathlib import Path

from xian_gapfill_hotel_batch import parse_price, parse_rooms

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "results" / "xian_gapfill_20261109"
OUT = RUN / "staging" / "roomtypes_existing"
SOURCES = [RUN / "staging/hotel/items.jsonl", RUN / "staging/hotel2/items.jsonl"]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    seen = set()
    rows = []
    for src in SOURCES:
        if not src.exists():
            continue
        for line in src.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            name = item["name"]
            raw_path = item["evidence"]["raw_path"]
            if name in seen:
                continue
            seen.add(name)
            page = ROOT / raw_path
            if not page.exists():
                continue
            html = page.read_text(encoding="utf-8", errors="replace")
            price, basis = parse_price(html)
            rooms = parse_rooms(html)
            beds = [r["bed_count"] for r in rooms if r["bed_count"]]
            primary_id = None
            if beds:
                from collections import Counter
                modal, n = Counter(beds).most_common(1)[0]
                if list(Counter(beds).values()).count(n) == 1:
                    pool = [r for r in rooms if r["bed_count"] == modal]
                    pool.sort(key=lambda r: (float(re.search(r"([\d.]+)", r.get("area") or "").group(1)) if re.search(r"([\d.]+)", r.get("area") or "") else 999999))
                    primary_id = pool[0]["room_id"]
            for r in rooms:
                rows.append({
                    "hotel": name, "city": "西安",
                    "source_url": item["source"]["url"],
                    "raw_path": raw_path,
                    "observed_at": item["source"]["observed_at"],
                    "hotel_id": None, "resolved_name": name, "distance_m": None,
                    **r, "is_primary": 1 if r["room_id"] == primary_id else 0,
                    "hotel_price": price, "price_basis": basis,
                })
    out = OUT / "room_types.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print(json.dumps({"hotels": len(seen), "rooms": len(rows), "path": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
