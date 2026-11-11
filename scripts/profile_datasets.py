"""Inspect the ChinaTravel query release and sandbox tables.

Writes a structured report to reproduction/notes/dataset_profile.json and prints a
compact human summary.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
NOTES = ROOT / "notes"
NOTES.mkdir(exist_ok=True)

QUERY_FILES = [
    "query/easy.csv",
    "query/medium.csv",
    "query/human.csv",
    "query/human1000.csv",
    "query/preference_base50.csv",
    "query/phase2/competition_test.csv",
]

TABLES = ["attractions", "accommodations", "restaurants", "poi", "trains", "flights", "subway_stations"]


def profile_queries() -> dict:
    out = {}
    for rel in QUERY_FILES:
        df = pd.read_csv(RAW / rel)
        info = {
            "rows": len(df),
            "columns": list(df.columns),
            "dtypes": {c: str(t) for c, t in df.dtypes.items()},
        }
        for col in ("start_city", "target_city"):
            if col in df.columns:
                info[f"{col}_counts"] = df[col].value_counts().to_dict()
        for col in ("days", "people_number"):
            if col in df.columns:
                info[f"{col}_range"] = [int(df[col].min()), int(df[col].max())]
                info[f"{col}_counts"] = {str(k): int(v) for k, v in df[col].value_counts().sort_index().items()}
        if "hard_logic_py" in df.columns:
            import ast

            def n_constraints(value):
                try:
                    parsed = ast.literal_eval(value) if isinstance(value, str) else value
                    return len(parsed) if isinstance(parsed, list) else -1
                except Exception:
                    return -1

            counts = df["hard_logic_py"].map(n_constraints)
            info["hard_logic_py_count"] = {
                "min": int(counts.min()),
                "max": int(counts.max()),
                "mean": round(float(counts.mean()), 2),
                "bad": int((counts < 0).sum()),
            }
        out[rel] = info
    return out


def profile_sandbox() -> dict:
    out = {}
    for lang in ("zh", "en"):
        out[lang] = {}
        for table in TABLES:
            path = RAW / f"sandbox/parquet/{lang}/{table}.parquet"
            df = pd.read_parquet(path)
            info = {
                "rows": len(df),
                "columns": list(df.columns),
                "dtypes": {c: str(t) for c, t in df.dtypes.items()},
                "nulls": {c: int(v) for c, v in df.isna().sum().items() if v},
            }
            for city_col in ("city", "City"):
                if city_col in df.columns:
                    info["city_counts"] = df[city_col].value_counts().to_dict()
            out[lang][table] = info
    return out


def sample_records() -> dict:
    df = pd.read_csv(RAW / "query/human.csv")
    row = df.iloc[0].to_dict()
    return {"human.csv row 0": {k: (v if not isinstance(v, str) or len(v) < 1200 else v[:1200] + "...") for k, v in row.items()}}


def main() -> int:
    report = {
        "queries": profile_queries(),
        "sandbox": profile_sandbox(),
        "sample": sample_records(),
    }
    (NOTES / "dataset_profile.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    for rel, info in report["queries"].items():
        print(f"\n=== {rel}  rows={info['rows']}")
        print("  columns:", ", ".join(info["columns"]))
        if "hard_logic_py_count" in info:
            print("  hard_logic_py count:", info["hard_logic_py_count"])
        if "days_counts" in info:
            print("  days:", info["days_counts"], " people:", info.get("people_number_counts"))
        if "target_city_counts" in info:
            print("  target cities:", info["target_city_counts"])

    for lang in ("zh", "en"):
        print(f"\n=== sandbox [{lang}]")
        for table, info in report["sandbox"][lang].items():
            print(f"  {table:18} rows={info['rows']:5}  cols={info['columns']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
