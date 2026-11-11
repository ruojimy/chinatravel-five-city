"""Validate gap-fill items before they are merged into a catalog snapshot.

Checks, per item:
  * kind / name exist in the Xi'an catalog and the field is allowed for that kind
  * the field is currently null (never overwrite a known value)
  * raw_path exists and the verbatim quote appears in the raw bytes or its tag-stripped text
  * the value is well-formed and its digits/text appear in the quote
  * source url is present

Usage:
  python scripts/xian_gapfill_validate.py --items results/<run>/staging/hotel/items.jsonl \
      [--snapshot results/xian_claude_20261108_145612/snapshot_v4/catalog.sqlite3]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CITY = "西安"
ALLOWED = {
    "attraction": {"opentime", "endtime", "price", "type", "lat", "lon"},
    "restaurant": {"opentime", "endtime", "cuisine", "price", "lat", "lon"},
    "accommodation": {"price", "numbed", "featurehoteltype", "hotelname_en", "lat", "lon"},
    "poi": {"position"},
    "metro_station": {"line", "position"},
    "train": {"Duration", "BeginTime", "EndTime", "Cost"},
    "flight": {"Duration", "BeginTime", "EndTime", "Cost"},
}
TIME_FIELDS = {"opentime", "endtime", "BeginTime", "EndTime"}
NUM_FIELDS = {"price", "numbed", "Duration", "Cost"}


def norm(text: str) -> str:
    return re.sub(r"[\s\u3000]+", "", text or "").lower()


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def digits(text: str) -> str:
    return re.sub(r"[^0-9.]", "", text or "")


def load_catalog(snapshot: Path) -> dict[tuple[str, str], dict]:
    conn = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)
    out = {}
    for kind, name, payload in conn.execute(
            f"select kind, name, payload from records where city='{CITY}'"):
        try:
            out[(kind, name)] = json.loads(payload)
        except json.JSONDecodeError:
            out[(kind, name)] = {}
    conn.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--snapshot", default="results/xian_claude_20261108_145612/snapshot_v4/catalog.sqlite3")
    ap.add_argument("--out-accepted", default=None)
    args = ap.parse_args()

    items_path = Path(args.items)
    if not items_path.is_absolute():
        items_path = ROOT / items_path
    catalog = load_catalog((ROOT / args.snapshot) if not Path(args.snapshot).is_absolute() else Path(args.snapshot))

    stats = Counter()
    accepted_rows = []
    rejects = []
    seen = set()
    per_field = defaultdict(Counter)

    for line_no, line in enumerate(items_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            rejects.append({"line": line_no, "reason": f"bad_json:{exc}"})
            continue
        kind = item.get("kind")
        name = (item.get("name") or "").strip()
        data = item.get("data") or {}
        src = item.get("source") or {}
        ev = item.get("evidence") or {}

        if kind not in ALLOWED or not name:
            rejects.append({"line": line_no, "reason": "bad_kind_or_name", "kind": kind, "name": name})
            continue
        record = catalog.get((kind, name))
        if record is None:
            rejects.append({"line": line_no, "reason": "not_in_catalog", "kind": kind, "name": name})
            continue
        current = record.get("data") or {}
        fields = {k: v for k, v in data.items() if v not in (None, "")}
        if not fields:
            rejects.append({"line": line_no, "reason": "empty_data", "name": name})
            continue
        bad = [k for k in fields if k not in ALLOWED[kind] or k not in (record.get("data") or {})]
        if bad:
            rejects.append({"line": line_no, "reason": "field_not_allowed", "name": name, "fields": bad})
            continue
        known = [k for k in fields if current.get(k) not in (None, "")]
        if known:
            rejects.append({"line": line_no, "reason": "already_known", "name": name, "fields": known})
            continue

        raw_path = ev.get("raw_path")
        quote = (ev.get("quote") or "").strip()
        if not raw_path or not quote:
            rejects.append({"line": line_no, "reason": "missing_raw_or_quote", "name": name})
            continue
        path = Path(raw_path)
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            rejects.append({"line": line_no, "reason": "raw_not_found", "name": name, "raw": raw_path})
            continue
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        if norm(quote) not in norm(text) and norm(quote) not in norm(strip_tags(text)):
            rejects.append({"line": line_no, "reason": "quote_not_verbatim", "name": name, "quote": quote[:60]})
            continue
        if not (src.get("url") or "").strip():
            rejects.append({"line": line_no, "reason": "missing_source_url", "name": name})
            continue

        bad_value = []
        for key, value in fields.items():
            if key in TIME_FIELDS and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(value)):
                bad_value.append((key, "bad_time"))
            elif key in NUM_FIELDS:
                try:
                    num = float(value)
                except (TypeError, ValueError):
                    bad_value.append((key, "not_numeric"))
                    continue
                if num <= 0:
                    bad_value.append((key, "not_positive"))
                if key in {"price", "numbed", "Cost"} and digits(str(value)) not in digits(quote):
                    bad_value.append((key, "value_not_in_quote"))
            elif key == "Duration" and digits(str(value)) not in digits(quote):
                bad_value.append((key, "value_not_in_quote"))
            elif key in {"opentime", "endtime"} and str(value) not in quote:
                # 24:00 is not a valid HH:MM; the merge step maps it to 23:59.
                if key == "endtime" and str(value) == "23:59" and "24:00" in quote:
                    continue
                bad_value.append((key, "time_not_in_quote"))
        if bad_value:
            rejects.append({"line": line_no, "reason": "value_mismatch", "name": name, "detail": bad_value})
            continue

        for key in fields:
            if (kind, name, key) in seen:
                rejects.append({"line": line_no, "reason": "duplicate_field", "name": name, "field": key})
            seen.add((kind, name, key))
            per_field[kind][key] += 1
        stats["accepted"] += 1
        accepted_rows.append(item)

    summary = {
        "items": str(items_path.relative_to(ROOT)).replace("\\", "/") if items_path.is_relative_to(ROOT) else str(items_path),
        "accepted": stats["accepted"],
        "rejected": len(rejects),
        "by_kind_field": {k: dict(v) for k, v in per_field.items()},
        "rejected_detail": rejects[:50],
    }
    if args.out_accepted:
        Path(args.out_accepted).write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in accepted_rows) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if not rejects else 1


if __name__ == "__main__":
    sys.exit(main())
