"""Extract partial (single-timestamp) Xi'an flights from saved Avionio boards.

The live boards show only one scheduled time per row. Unknown fields stay null
by project rule; nothing is estimated. Each row's original HTML is the quote.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROW_RE = re.compile(r'<tr class="tt-row[^"]*">(.*?)</tr>', re.S)
TIME_RE = re.compile(r'<td class="tt-t[^"]*">\s*(\d{2}:\d{2})\s*</td>')
FLIGHT_RE = re.compile(r'title=[\'"]Live status: Flight ([A-Z0-9]+)')
CITY_RE = re.compile(r'<td class="tt-ap">(.*?)</td>', re.S)
CODE_RE = re.compile(r'<td class="tt-i">.*?>([A-Z]{3})</a>', re.S)
TAG_RE = re.compile(r"<[^>]+>")


def clean(text: str) -> str:
    return TAG_RE.sub("", text).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run)
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    raw_dir = run_dir / "staging/f2/raw"
    out_dir = run_dir / "staging/reviewed"
    out_dir.mkdir(parents=True, exist_ok=True)

    used = set()
    for file in (out_dir / "flights.jsonl", out_dir / "flights2.jsonl"):
        if file.exists():
            for line in file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    used.add(json.loads(line)["name"].upper())

    items = []
    for name, direction in (("avionio_xiy_departures.html", "dep"),
                            ("avionio_xiy_arrivals.html", "arr")):
        path = raw_dir / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        for match in ROW_RE.finditer(text):
            block = match.group(1)
            flight = FLIGHT_RE.search(block)
            time = TIME_RE.search(block)
            if not flight or not time:
                continue
            fid = flight.group(1)
            if fid.upper() in used:
                continue
            used.add(fid.upper())
            city = clean(CITY_RE.search(block).group(1)) if CITY_RE.search(block) else None
            code = CODE_RE.search(block).group(1) if CODE_RE.search(block) else None
            place = f"{city} ({code})" if city and code else (city or code or "未知")
            if direction == "dep":
                data = {"FlightID": fid, "From": "西安咸阳国际机场", "To": place,
                        "BeginTime": time.group(1), "EndTime": None, "Duration": None,
                        "Cost": None}
            else:
                data = {"FlightID": fid, "From": place, "To": "西安咸阳国际机场",
                        "BeginTime": None, "EndTime": time.group(1), "Duration": None,
                        "Cost": None}
            items.append({
                "kind": "flight", "name": fid, "aliases": [], "data": data,
                "source": {
                    "url": f"https://www.avionio.com/en/airport/xiy/{direction}artures"
                    if direction == "dep" else "https://www.avionio.com/en/airport/xiy/arrivals",
                    "publisher": "Avionio", "authority": "travel_marketplace_display",
                    "licence_status": "public_schedule_page", "trust_status": "reference_only",
                    "published_at": None, "observed_at": None,
                },
                "evidence": {
                    "raw_path": rel,
                    "quote": match.group(0),
                    "locator": f"{direction} 表格行 {fid}",
                },
                "notes": "当日实时看板只有单一计划时刻，EndTime/Duration 按规则留 null，不估算；仅参考级",
            })

    out = out_dir / "flights_partial.jsonl"
    out.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n",
                   encoding="utf-8")
    print(json.dumps({"items": len(items),
                      "out": str(out.relative_to(ROOT)).replace("\\", "/")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
