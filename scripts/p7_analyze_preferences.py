"""P3 step 3: analyse the pairwise human-preferences sheet.

Runs even when nothing has been rated yet — in that case it reports the protocol
status and refuses to invent metrics. Once raters fill `packets.csv`, it computes:

  * coverage (pairs with 1 / 2 / 3 ratings)
  * choice distribution, keeping "差不多" and "无法判断" separate from A/B
  * human-human agreement: observed pairwise agreement and Fleiss' kappa
  * the human majority per pair, with ties handled explicitly

The model side is deliberately *not* computed here: it needs frozen predictions
and independent reference labels. score_plan() may produce predictions; using it
to generate the reference labels would be circular. No human labels are invented.
Fleiss' kappa uses only fully rated items with the same number of raters.

Outputs
  results/p7_human_evaluation/preference_analysis.json
  results/p7_human_evaluation/preference_analysis.md
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKETS = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "datasets" / "human_preference" / "packets.csv"
PRIVATE = ROOT / "datasets" / "human_preference" / "pairs_private.json"
OUT = (Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "results" / "p7_human_evaluation")
CHOICES = {"a": "A", "b": "B", "tie": "tie", "unknown": "unknown"}
NORMALISE = {"a 更好": "a", "b 更好": "b", "差不多": "tie", "无法判断": "unknown",
             "a": "a", "b": "b", "1": "a", "2": "b", "3": "tie", "0": "unknown"}


def fleiss_kappa(table: list[list[int]]) -> float | None:
    """Fleiss' kappa for a fixed number of ratings per subject."""
    n_subjects = len(table)
    if n_subjects == 0:
        return None
    n_ratings = sum(table[0])
    if any(sum(row) != n_ratings for row in table):
        raise ValueError('Fleiss kappa requires a fixed number of ratings per item')
    if n_ratings < 2:
        return None
    p_i = []
    for row in table:
        total = sum(row)
        p_i.append((sum(count * count for count in row) - total) / (total * (total - 1)))
    p_bar = sum(p_i) / n_subjects
    k = len(table[0])
    p_j = [sum(row[j] for row in table) / (n_subjects * n_ratings) for j in range(k)]
    p_e = sum(value * value for value in p_j)
    if p_e >= 1:
        return None
    return round((p_bar - p_e) / (1 - p_e), 4)


def main() -> int:
    if not PACKETS.exists():
        print("缺少 packets.csv：先运行 scripts/p7_build_pairwise_packets.py")
        return 2
    with PACKETS.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    private = json.loads(PRIVATE.read_text(encoding="utf-8")) if PRIVATE.exists() else {"pairs": []}
    private_by_pair = {item["pair_id"]: item for item in private.get("pairs", [])}

    rater_cols = [key for key in (rows[0].keys() if rows else []) if key.endswith("_choice")]
    per_pair: list[dict] = []
    distribution = Counter()
    order = ["a", "b", "tie", "unknown"]

    for row in rows:
        votes = []
        for column in rater_cols:
            raw = (row.get(column) or "").strip().lower()
            vote = NORMALISE.get(raw)
            if vote:
                votes.append(vote)
        counted = [vote for vote in votes if vote in ("a", "b", "tie", "unknown")]
        distribution.update(counted)
        row_counts = [counted.count(key) for key in order]
        majority = None
        if counted:
            top = max(row_counts)
            winners = [order[index] for index, value in enumerate(row_counts) if value == top]
            majority = winners[0] if len(winners) == 1 else "tie"
        per_pair.append({"pair_id": row["pair_id"], "n_ratings": len(counted), "votes": counted,
                         "majority": majority,
                         "candidate_A": (private_by_pair.get(row["pair_id"]) or {}).get("candidate_A"),
                         "candidate_B": (private_by_pair.get(row["pair_id"]) or {}).get("candidate_B")})

    rated = [item for item in per_pair if item["n_ratings"] > 0]
    full = [item for item in per_pair if item["n_ratings"] == len(rater_cols)]
    agreement = None
    if full:
        agreements = []
        for item in full:
            votes = item["votes"]
            pairs = [(votes[i], votes[j]) for i in range(len(votes)) for j in range(i + 1, len(votes))]
            if pairs:
                agreements.append(sum(1 for left, right in pairs if left == right) / len(pairs))
        agreement = round(sum(agreements) / len(agreements), 4) if agreements else None

    # Partial annotation is expected in a low-burden protocol. Do not feed rows
    # with different vote counts to the fixed-rater Fleiss statistic.
    kappa_table = [[item['votes'].count(key) for key in order]
                   for item in full if item['n_ratings'] >= 2]

    report = {
        "generated_at": "2026-10-22",
        "stage": "P3 preference analysis",
        "material": {"pairs": len(rows), "raters_per_pair": len(rater_cols),
                     "source": str(PACKETS.relative_to(ROOT)) if PACKETS.is_relative_to(ROOT) else str(PACKETS)},
        "coverage": {"pairs_total": len(rows), "pairs_with_any_rating": len(rated),
                     "pairs_fully_rated": len(full),
                     "ratings_total": sum(item["n_ratings"] for item in per_pair),
                     "completion_rate": round(len(full) / len(rows), 3) if rows else 0.0},
        "distribution": {"A": distribution.get("a", 0), "B": distribution.get("b", 0),
                         "tie": distribution.get("tie", 0), "unknown": distribution.get("unknown", 0)},
        "human_human": {"observed_pairwise_agreement": agreement,
                        "fleiss_kappa": fleiss_kappa(kappa_table) if kappa_table else None,
                        "n_pairs_in_kappa": len(kappa_table),
                        "kappa_scope": "fully rated items only; partial items excluded; see coverage"},
        "model_vs_human": {
            "status": "not_computed",
            "reason": "模型预测需要与独立冻结的参考标签比较；score_plan 可以产生预测，"
                      "但不能同时生成标准答案。当前尚未连接独立参考标签与冻结预测，不计算一致率",
            "private_mapping_ready": bool(private_by_pair),
        },
        "pairs": per_pair,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "preference_analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
    md = [
        "# P3 成对偏好评价：现状",
        "",
        f"> 材料 {report['material']['pairs']} 对，每对 {report['material']['raters_per_pair']} 位评价者",
        "",
        "## 完成度",
        "",
        f"- 已评分数：**{report['coverage']['ratings_total']}**",
        f"- 有任一评分的对：{report['coverage']['pairs_with_any_rating']}/{report['material']['pairs']}",
        f"- 三位评价者全部完成的对：{report['coverage']['pairs_fully_rated']}/{report['material']['pairs']}",
        "",
        "## 选择分布",
        "",
        f"- A 更好：{report['distribution']['A']}　B 更好：{report['distribution']['B']}　"
        f"差不多：{report['distribution']['tie']}　无法判断：{report['distribution']['unknown']}",
        "",
        "## 人-人一致性",
        "",
        f"- 观察一致率：{report['human_human']['observed_pairwise_agreement']}",
        f"- Fleiss' kappa：{report['human_human']['fleiss_kappa']}",
        "",
        "## 模型-人一致率",
        "",
        f"**未计算**：{report['model_vs_human']['reason']}",
        "",
        "> 在拿到人工评分之前，本文件不报告任何“更人性化”的结论。",
    ]
    (OUT / "preference_analysis.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"coverage": report["coverage"], "distribution": report["distribution"],
                      "agreement": report["human_human"]}, ensure_ascii=False, indent=2))
    print("wrote", OUT / "preference_analysis.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
