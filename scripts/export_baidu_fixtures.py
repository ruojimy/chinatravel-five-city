"""Freeze the real Baidu responses we captured into replayable fixtures.

Why: the account's daily quota is nearly exhausted (user, 2026-10-21). Nothing in
this project should need a live call to keep working. Every response that was
actually received is stored once, keyed by (query, region) or uid, and the
pipeline replays it. A fixture is *evidence*, never a substitute for a test: the
replay mode is always labelled in reports as "replayed capture", never "live".

Input : results/baidu_raw/*.json   (written by scripts/probe_baidu_fields.py)
Output: data/baidu_fixtures/{search,detail}/*.json + index.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "baidu_raw"
OUT = ROOT / "data" / "baidu_fixtures"


def slug(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", str(text)).strip("_")


def main() -> int:
    (OUT / "search").mkdir(parents=True, exist_ok=True)
    (OUT / "detail").mkdir(parents=True, exist_ok=True)
    index = {"captured_at": "2026-10-21", "mode": "replay", "searches": {}, "details": {}}

    for path in sorted(RAW.glob("search_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        stem = path.stem[len("search_"):]
        city, _, name = stem.partition("_")
        v2 = payload.get("v2") or {}
        if str(v2.get("status")) != "0":
            continue
        record = {
            "kind": "search",
            "query": name,
            "region": city,
            "captured_at": "2026-10-21",
            "source_file": str(path.relative_to(ROOT)),
            "raw": v2,
        }
        target = OUT / "search" / f"{slug(city)}__{slug(name)}.json"
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        index["searches"][f"{city}|{name}"] = str(target.relative_to(OUT))

    for path in sorted(RAW.glob("detail_v2_*.json")):
        uid = path.stem[len("detail_v2_"):]
        payload = json.loads(path.read_text(encoding="utf-8"))
        if str(payload.get("status")) != "0":
            continue
        record = {
            "kind": "detail",
            "uid": uid,
            "captured_at": "2026-10-21",
            "source_file": str(path.relative_to(ROOT)),
            "raw": payload,
        }
        target = OUT / "detail" / f"{uid}.json"
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        index["details"][uid] = str(target.relative_to(OUT))

    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"searches={len(index['searches'])} details={len(index['details'])} -> {OUT}")
    for key in index["searches"]:
        print("  search:", key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
