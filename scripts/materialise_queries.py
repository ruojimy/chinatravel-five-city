"""Materialise the released query CSVs into the repo's local-split layout and
print a few full records for manual inspection.

Output layout (inside the cloned repo):
    chinatravel/data/<split>/<uid>.json    # one JSON object per query
and mirrored copies under reproduction/query_sets/<split>/.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "query"
REPO_DATA = ROOT / "ChinaTravel" / "chinatravel" / "data"
MIRROR = ROOT / "query_sets"

SPLITS = [
    "easy",
    "medium",
    "human",
    "human1000",
    "preference_base50",
    "preference0_base50",
    "preference5_base50",
    "phase2/competition_test",
]


def _json_default(obj):
    if hasattr(obj, "item"):
        return obj.item()
    return str(obj)

ORACLE_COLS = ["hard_logic", "hard_logic_py", "hard_logic_nl"]


def decode_oracle(value):
    """The release stores DSL fields as Python reprs, not JSON."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        pass
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value


def load_split(rel: str) -> pd.DataFrame:
    return pd.read_csv(RAW / f"{rel}.csv")


def main() -> int:
    summary = []
    for rel in SPLITS:
        split = rel.split("/")[-1]
        out_dir = REPO_DATA / split
        out_dir.mkdir(parents=True, exist_ok=True)
        mirror_dir = MIRROR / split
        mirror_dir.mkdir(parents=True, exist_ok=True)
        df = load_split(rel)
        for _, row in df.iterrows():
            record = {k: v for k, v in row.items() if pd.notna(v)}
            for key in ORACLE_COLS:
                if key in record:
                    record[key] = decode_oracle(record[key])
            payload = json.dumps(record, ensure_ascii=False, indent=2, default=_json_default)
            (out_dir / f"{record['uid']}.json").write_text(payload, encoding="utf-8")
            (mirror_dir / f"{record['uid']}.json").write_text(payload, encoding="utf-8")
        summary.append((rel, len(df), len(list(out_dir.glob("*.json")))))

    lines = ["| split | rows | materialised |", "| --- | --- | --- |"]
    for rel, n, m in summary:
        lines.append(f"| {rel} | {n} | {m} |")
    (ROOT / "notes" / "materialised_splits.md").write_text("\n".join(lines), encoding="utf-8")

    # A full example record for manual inspection.
    human = load_split("human")
    row = human.iloc[0]
    example = {k: row[k] for k in human.columns}
    example["hard_logic_py"] = decode_oracle(example["hard_logic_py"])
    (ROOT / "notes" / "example_query_human.json").write_text(
        json.dumps(example, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8"
    )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

