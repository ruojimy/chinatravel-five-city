"""Live/final aggregation for the ShortTrip + Qwen3.5-4B Q8 three-arm benchmark.

Safe to run at any time: it only reads per-case status files and writes a
progress snapshot. When all arms are terminal it also emits a Markdown report.

Usage:
  .venv/Scripts/python.exe -B -X utf8 scripts/summarize_shorttrip_benchmark.py
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = Path(os.environ.get("SHORTTRIP_RUNS", ROOT.parent / "shorttrip-runs"))
ARMS = ("G1_native", "G2_ext10", "G3_ext11")
SPLITS = ("easy", "medium", "human")
ARM_LABEL = {"G1_native": "原生 10 城", "G2_ext10": "扩展 10 城", "G3_ext11": "扩展 11 城"}
DATA_LABEL = {"G1_native": "官方原生沙盒", "G2_ext10": "catalog_v1_1",
              "G3_ext11": "catalog_v1_1 + xian11"}
TERMINAL = {"generated", "no_feasible_candidate", "timed_out_with_candidates",
            "timed_out_no_candidates", "failed"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def checkout(arm: str) -> Path | None:
    p = RUNS / "ACTIVE_CHECKOUTS.json"
    if not p.exists():
        return None
    v = read(p).get(arm)
    return Path(v) if v and Path(v).exists() else None


def empty_bucket():
    return {"target": 0, "done": 0, "states": Counter(),
            "official_pass": 0, "c_rule_pass": 0, "combined_pass": 0}


def main() -> int:
    summary = {"updated_at": datetime.now(timezone.utc).isoformat(), "arms": {},
               "state": "running"}
    lines = [
        "# ShortTrip + Qwen3.5-4B Q8 三组基准实验\n",
        "模型：`Qwen/Qwen3.5-4B` Q8_0 GGUF（`Qwen3.5-4B-Q8_0.gguf`，4,610,580,288 B，"
        "sha256 `5b25856e…3a833`），llama.cpp b12248 CUDA 12.4，`--reasoning off`、"
        "16K/slot、`-np 6`、别名 `qwen3.5-4b-q8`，单实例顺序跑三组。\n",
        "抽样：固定 seed 20261111，每组 1/10（native easy 30 / medium 15 / human 15 = 60；"
        "xian11 3/3/3 = 9，30 道 chain 与单目标规划器不兼容未计分）。\n",
        "| 组 | 数据层 | split | 完成/目标 | generated | 官方三关全过 | C组规则通过 | 共同通过 |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    all_terminal = True
    totals = {arm: empty_bucket() for arm in ARMS}
    for arm in ARMS:
        c = checkout(arm)
        if not c:
            lines.append(f"| {arm} | — | — | 0/0 | 0 | 0 | 0 | 0 |")
            all_terminal = False
            continue
        out = c / "experiments/c_only"
        manifest = read(out / "manifest.json")
        buckets = {s: empty_bucket() for s in SPLITS}
        for case in manifest["cases"]:
            buckets[case["split"]]["target"] += 1
        totals[arm]["target"] = sum(b["target"] for b in buckets.values())
        for f in sorted((out / "status").glob("*.json")):
            try:
                s = read(f)
            except json.JSONDecodeError:
                continue
            split = s.get("split") if s.get("split") in SPLITS else "easy"
            for bucket in (buckets[split], totals[arm]):
                bucket["done"] += 1
                bucket["states"][s.get("state") or "unknown"] += 1
                ev = s.get("evaluation") or {}
                audit = s.get("new_rule_audit") or {}
                bucket["official_pass"] += bool(ev.get("all_pass"))
                bucket["c_rule_pass"] += bool(audit.get("all_pass"))
                bucket["combined_pass"] += bool(s.get("combined_pass"))
        for split in SPLITS:
            b = buckets[split]
            if not b["target"]:
                continue
            if b["done"] < b["target"]:
                all_terminal = False
            lines.append(
                f"| {arm} | {DATA_LABEL[arm]} | {split} | {b['done']}/{b['target']} | "
                f"{b['states'].get('generated', 0)} | {b['official_pass']} | "
                f"{b['c_rule_pass']} | {b['combined_pass']} |")
        t = totals[arm]
        if t["target"]:
            lines.append(
                f"| **{arm} 合计** | {DATA_LABEL[arm]} | all | {t['done']}/{t['target']} | "
                f"{t['states'].get('generated', 0)} | {t['official_pass']} | "
                f"{t['c_rule_pass']} | {t['combined_pass']} |")
        summary["arms"][arm] = {
            "checkout": str(c), "target": t["target"], "done": t["done"],
            "states": dict(t["states"]),
            "passes": {"official_all_pass": t["official_pass"],
                       "c_rule_pass": t["c_rule_pass"],
                       "combined_pass": t["combined_pass"]},
            "by_split": {s: {"target": buckets[s]["target"], "done": buckets[s]["done"],
                             "states": dict(buckets[s]["states"]),
                             "official_all_pass": buckets[s]["official_pass"],
                             "c_rule_pass": buckets[s]["c_rule_pass"],
                             "combined_pass": buckets[s]["combined_pass"]}
                         for s in SPLITS},
        }
    summary["state"] = "complete" if all_terminal else "running"
    lines += ["", f"状态：**{summary['state']}**　更新：{summary['updated_at']}", ""]

    rb = (RUNS / "RULE_BASELINE_G1_1of10.json")
    if rb.exists():
        d = read(rb)
        by = d["by_split"]
        lines += ["## 规则规划器对照（P34 ConstraintPlannerV2，纯规则、0 LLM token）",
                  "",
                  f"同一冻结 60 题：三关全过 **{d['total']['passes']['all_ok']}/{d['total']['found']} = "
                  f"{100 * d['total']['passes']['all_ok'] / max(d['total']['found'], 1):.1f}%**"
                  f"（easy {by['easy']['passes']['all_ok']}/30、"
                  f"medium {by['medium']['passes']['all_ok']}/15、"
                  f"human {by['human']['passes']['all_ok']}/15）。", ""]
    lines += [
        "## 口径边界", "",
        "- 每组 1/10：native 60/604（9.93%），xian11 9/90（10%）；easy/medium/human 均覆盖，G1/G2 共用同一批 UID 配对。",
        "- G3 的 30 道 `shorttrip-dynamic-v1` 多城串联题与 ShortTrip 单目标规划器不兼容，未计入 LLM 组成绩。",
        "- 扩展组只替换 attractions/restaurants/accommodations 三类实体表；POI / 地铁 / 跨城沿用同一官方 release，"
        "因为题目 DSL 引用精确 TrainID/FlightID。",
        "- 第 11 城数据来自 snapshot_v17；景点 price 12.3%、餐厅 69.5%、住宿 40.4% 为已知开放缺口。",
        "- 官方三关成绩来自 ShortTrip worker 自带的独立评估；C 组规则为其扩展检查，两者并列不混算。",
        "- 每题一次提交即终态，driver 对已有产物不重跑；中断后重跑 runner 即续跑。",
        "- 规则规划器绑定原生沙盒，因此只作 G1 对照；G2/G3 无同构规则规划器。", "",
    ]
    (RUNS / "BENCHMARK_PROGRESS.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RUNS / "BENCHMARK_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
