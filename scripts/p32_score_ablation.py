"""P32 ablation scoring: gap recall / verdict agreement without derived hints."""
from __future__ import annotations

import json
from pathlib import Path

from p31_common import read_json, write_json
from p32_score import canonical_static, score_gaps, split_order

ROOT = Path(__file__).resolve().parents[1]
P31 = ROOT / "results/p31_five_city_96"
P32 = ROOT / "results/p32_llm_96"
UIDS = ["E01", "E10", "D01", "N01", "D06", "D10", "D18", "N12", "N21", "N24", "N28", "D30"]


def main():
    tasks = {t["uid"]: t for t in read_json(P31 / "tasks/all_96.json")}
    rows = []
    for uid in UIDS:
        d = read_json(P32 / "ablation/out" / f"{uid}_static.json")
        t = tasks[uid]
        g = score_gaps(t, d.get("gaps"))
        order, _, ok = split_order(t, d.get("order"))
        st = canonical_static(t, order, d.get("lunch_after")) if ok else None
        rows.append({"uid": uid, "verdict": d.get("verdict"),
                     "canonical": st["verdict"] if st else None,
                     "recall": g["recall"], "precision": g["precision"],
                     "miss": g["miss"], "extra": g["extra"]})
    summary = {
        "tasks": rows,
        "avg_recall": round(sum(r["recall"] for r in rows) / len(rows), 3),
        "avg_precision": round(sum(r["precision"] for r in rows) / len(rows), 3),
        "verdict_match": sum(1 for r in rows if r["verdict"] == r["canonical"]),
        "perfect": sum(1 for r in rows if r["recall"] == 1.0 and r["precision"] == 1.0
                       and r["verdict"] == r["canonical"]),
    }
    write_json(P32 / "ablation/summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
