"""P34: aggregate official-eval numbers for V2 and compare with P33 / the paper."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CT = ROOT / "ChinaTravel"
OUT = ROOT / "results/p34_v2_planner"

PAPER_FPR = {  # Table 3/17, FPR = all-pass rate (see results/p33_native_planner/paper_baselines.md)
    "easy": {"NeSy Planning (DeepSeek-V3)": 52.6, "NeSy Planning* (Oracle Translation)": 74.0,
             "best pure LLM (ReAct one-shot)": 5.33},
    "medium": {"NeSy Planning (DeepSeek-V3)": 46.7, "NeSy Planning* (Oracle Translation)": 54.0},
    "human": {"NeSy Planning (DeepSeek-V3)": 37.0, "NeSy Planning* (Oracle Translation)": 45.4},
}


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def rates(split: str, method: str) -> dict | None:
    base = CT / f"eval_res/splits_{split}_p33/{method}"
    if not base.exists():
        return None
    schema = read_csv(base / "schema.csv")
    common = read_csv(base / "commonsense.csv")
    logical = read_csv(base / "logical_py.csv")
    if not schema:
        return None
    ccols = [c for c in common[0] if c != "data_id"]
    lcols = [c for c in logical[0] if c != "data_id"]
    s_pass = {r["data_id"] for r in schema if str(r["schema"]) == "1"}
    c_pass = {r["data_id"] for r in common if all(str(r[c]) in ("0", "0.0", "") for c in ccols)}
    l_pass = {r["data_id"] for r in logical if all(str(r[c]) != "0" for c in lcols)}
    all_pass = s_pass & c_pass & l_pass
    n = len(schema)
    return {
        "split": split, "method": method, "queries": n,
        "schema": round(100 * len(s_pass) / n, 2),
        "commonsense": round(100 * len(c_pass) / n, 2),
        "hard": round(100 * len(l_pass) / n, 2),
        "all_pass": round(100 * len(all_pass) / n, 2),
        "s_uids": sorted(s_pass), "c_uids": sorted(c_pass), "l_uids": sorted(l_pass),
        "all_uids": sorted(all_pass),
    }


def main() -> int:
    rows = []
    for split in ("easy", "medium", "human"):
        old = rates(split, f"ShortTrip_{split}")
        fixed = rates(split, f"ShortTrip_{split}_fix")
        v2 = rates(split, f"ShortTripV2_{split}")
        rows.append({"split": split, "old": old, "old_fix": fixed, "v2": v2,
                     "paper": PAPER_FPR[split]})

    table = ["| split | 版本 | schema | commonsense | hard DSL | **三关全过** |", "| --- | --- | ---: | ---: | ---: | ---: |"]
    for row in rows:
        split = row["split"]
        for label, key in (("P33 旧规划器", "old"), ("P33 + room_type 修复", "old_fix"), ("**P34 新规划器 V2**", "v2")):
            item = row[key]
            if not item:
                continue
            table.append(f"| {split} | {label} | {item['schema']} | {item['commonsense']} | "
                         f"{item['hard']} | **{item['all_pass']}** |")
        paper = row["paper"]
        table.append(f"| {split} | 论文 NeSy (DeepSeek-V3) | - | - | - | {list(paper.values())[0]} |")
        table.append(f"| {split} | 论文 NeSy* (Oracle 翻译) | - | - | - | {list(paper.values())[1]} |")

    gains = {}
    for row in rows:
        if row["old"] and row["v2"]:
            gains[row["split"]] = {
                "vs_old": round(row["v2"]["all_pass"] - row["old"]["all_pass"], 2),
                "vs_old_fix": round(row["v2"]["all_pass"] - row["old_fix"]["all_pass"], 2)
                if row["old_fix"] else None,
                "vs_paper_nesy": round(row["v2"]["all_pass"] - list(row["paper"].values())[0], 2),
                "vs_paper_nesy_oracle": round(row["v2"]["all_pass"] - list(row["paper"].values())[1], 2),
            }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "aggregate.json").write_text(json.dumps(
        {"rows": rows, "gains": gains, "paper_note": "FPR = all-pass; see paper_baselines.md"},
        ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "table.md").write_text("\n".join(table) + "\n", encoding="utf-8")
    print("\n".join(table))
    print("\ngains:", json.dumps(gains, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
