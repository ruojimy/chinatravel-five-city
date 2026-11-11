"""Drop non-venue POIs from an Amap discovery ``items.jsonl``.

Amap keyword search returns everything that matches the string: querying
"鼓浪屿" also yields car parks, bus stops, hotels and public toilets. Xi'an hit
the same thing and cleaned it by hand; this makes the filter explicit and
reproducible.

Every kept item must carry an accepted ``typecode`` (``data.type`` for
attraction items) — items without one are dropped, never guessed. Streams the
file, so memory stays flat regardless of item count.

Usage:
    python scripts/filter_place_items.py --kind attraction --items <in.jsonl> --out <out.jsonl>
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

# Amap typecode families that are genuinely visitable venues / places to eat or stay.
ACCEPT = {
    "attraction": ("11", "1401", "1402", "1403", "0803", "0805"),
    "restaurant": ("05",),
    "accommodation": ("10",),
}
# Sub-codes inside an accepted family that are still not venues.
REJECT_SUBSTR = ("停车场", "停车点", "出入口", "售票处", "公共厕所", "服务部", "公交站",
                 "地铁站", "加油", "充电", "小区", "收费站", "派出所", "管理处", "码头")


def accepted(kind: str, typecode: str) -> bool:
    code = (typecode or "").strip()
    if not code:
        return False
    return any(code.startswith(prefix) for prefix in ACCEPT[kind])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kind", required=True, choices=list(ACCEPT))
    ap.add_argument("--items", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    src = Path(args.items)
    dst = Path(args.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    kept = dropped = no_code = 0
    reasons = collections.Counter()
    by_code = collections.Counter()
    with src.open(encoding="utf-8") as fin, dst.open("w", encoding="utf-8") as fout:
        for line in fin:
            if not line.strip():
                continue
            item = json.loads(line)
            data = item.get("data") or {}
            code = str(data.get("type") or "")
            name = str(item.get("name") or "")
            if not code:
                no_code += 1
                reasons["no_typecode"] += 1
                continue
            if not accepted(args.kind, code):
                dropped += 1
                reasons[f"type:{code[:4]}"] += 1
                continue
            if any(token in name for token in REJECT_SUBSTR):
                dropped += 1
                reasons["name_blocklist"] += 1
                continue
            kept += 1
            by_code[code[:4]] += 1
            fout.write(json.dumps(item, ensure_ascii=False) + "\n")

    summary = {
        "kind": args.kind, "in": str(src), "out": str(dst),
        "kept": kept, "dropped": dropped, "no_typecode": no_code,
        "kept_by_typecode": dict(by_code.most_common(12)),
        "drop_reasons": dict(reasons.most_common(10)),
    }
    if args.report:
        Path(args.report).write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n",
                                     encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
