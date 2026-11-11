"""Catalogue the DSL constraint families across all released splits.

For every split we count which concept predicates appear in `hard_logic_py`, and
store one representative constraint per (predicate-signature) family so we can
design a deterministic solver and new benchmark variants.
"""
from __future__ import annotations

import ast
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "query"
NOTES = ROOT / "notes"

FUNC_NAMES = [
    "day_count", "people_count", "start_city", "target_city", "allactivities",
    "allactivities_count", "activity_position", "activity_cost", "activity_type",
    "activity_tickets", "activity_transports", "activity_price", "activity_time",
    "poi_recommend_time", "poi_distance", "metro_tickets", "taxi_cars", "room_count",
    "room_type", "restaurant_type", "attraction_type", "accommodation_type",
    "innercity_transport_type", "innercity_transport_cost", "innercity_transport_price",
    "innercity_transport_start_time", "innercity_transport_end_time",
    "innercity_transport_distance", "intercity_transport_type", "dayactivities",
    "activity_start_time", "activity_end_time", "intercity_transport_origin",
    "intercity_transport_destination", "innercity_transport_time",
]

SPLITS = ["easy", "medium", "human", "preference_base50", "phase2/competition_test"]


def decode(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return ast.literal_eval(value)
    return value


def signature(constraint: str) -> str:
    """A coarse structural signature: which predicates and which operators."""
    used = sorted({name for name in FUNC_NAMES if re.search(rf"\b{name}\s*\(", constraint)})
    ops = []
    for token, label in [
        ("==", "eq"), ("!=", "ne"), ("<=", "le"), (">=", "ge"),
        ("<", "lt"), (">", "gt"), ("in ", "in"), ("not in", "notin"),
        ("return", "def"),
    ]:
        if token in constraint:
            ops.append(label)
    return "|".join(used) or "unknown"


def main() -> int:
    report = {}
    families = defaultdict(list)
    for rel in SPLITS:
        df = pd.read_csv(RAW / f"{rel}.csv")
        counter = Counter()
        for _, row in df.iterrows():
            for constraint in decode(row["hard_logic_py"]):
                sig = signature(constraint)
                counter[sig] += 1
                if len(families[sig]) < 3:
                    families[sig].append({"split": rel, "uid": row["uid"], "code": constraint})
        report[rel] = {"n_queries": len(df), "n_constraints": sum(counter.values()),
                       "families": dict(counter.most_common())}

    (NOTES / "constraint_families.json").write_text(
        json.dumps({"counts": report, "examples": families}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = ["# DSL constraint families", ""]
    for rel in SPLITS:
        info = report[rel]
        lines.append(f"## {rel}  ({info['n_queries']} queries, {info['n_constraints']} constraints)")
        lines.append("")
        lines.append("| signature | count |")
        lines.append("| --- | --- |")
        for sig, n in info["families"].items():
            lines.append(f"| `{sig}` | {n} |")
        lines.append("")
    lines.append("## Representative constraints")
    for sig, items in families.items():
        lines.append(f"### `{sig}`")
        for item in items:
            code = item["code"].replace("\n", "\\n")
            lines.append(f"- {item['split']}/{item['uid']}: `{code}`")
        lines.append("")
    (NOTES / "constraint_families.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"families={len(families)} -> notes/constraint_families.md")
    for rel in SPLITS:
        print(rel, report[rel]["n_constraints"], "constraints;", len(report[rel]["families"]), "families")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
