"""P32 ablation: strip the derived gap hints from 12 static packs.

The main run's packs carry `missing_fields` and `static_estimate.unknown_price_items`,
which telegraph the answer.  This ablation keeps the raw data (nulls are still visible)
but removes the derived hints, so gap detection has to come from the fields themselves.
"""
from __future__ import annotations

import json
from pathlib import Path

from p31_common import read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
P32 = ROOT / "results/p32_llm_96"
ABL = P32 / "ablation/packs"
UIDS = ["E01", "E10", "D01", "N01", "D06", "D10", "D18", "N12", "N21", "N24", "N28", "D30"]


def main():
    ABL.mkdir(parents=True, exist_ok=True)
    built = []
    for uid in UIDS:
        d = read_json(P32 / "packs" / f"{uid}_static.json")
        t = d["task"]
        for c in t["candidates"]:
            c.pop("missing_fields", None)
            c["tags"] = [x for x in (c.get("tags") or [])
                         if x.get("tag") not in ("native_fields_complete",)]
        se = t.get("static_estimate") or {}
        se.pop("unknown_price_items", None)
        t["static_estimate"] = se
        d["note"] = "只有静态候选，没有 missing_fields / unknown_price_items 提示；缺口要自己逐字段检查。"
        write_json(ABL / f"{uid}_static.json", d)
        built.append(uid)
    print(json.dumps({"packs": built}, ensure_ascii=False))


if __name__ == "__main__":
    main()
