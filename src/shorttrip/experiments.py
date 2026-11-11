"""Experiment driver for the ShortTrip-on-ChinaTravel reproduction.

Runs four blocks and writes machine-readable + human-readable results:

E1  checker fidelity (mutation study on a valid plan)
E2  deterministic baseline: skeleton planner, and planner + bounded repair
E3  dataset V1 (post-confirmation repair) construction + repair metrics
E4  dataset V2 (labelled no-solution) construction + classification metrics
"""
from __future__ import annotations

import copy
import glob
import json
import random
import time
from pathlib import Path

from .checker import check_plan
from .dataset import build_repair_cases
from .env import get_env
from .infeasibility import build_infeasible_cases
from .planner import SkeletonPlanner
from .repair import RepairEngine

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT / "ChinaTravel"
RESULTS = ROOT / "results"
SPLITS = ["easy", "medium", "human", "preference_base50"]


def load_queries(split: str, limit: int) -> list[dict]:
    paths = sorted(glob.glob(str(REPO / "chinatravel" / "data" / split / "*.json")))
    queries = []
    for path in paths[:limit]:
        queries.append(json.loads(Path(path).read_text(encoding="utf-8")))
    return queries


# --------------------------------------------------------------------- E1
def mutation_study(env, query: dict, plan: dict) -> list[dict]:
    def first(plan, kind):
        for day in plan["itinerary"]:
            for activity in day["activities"]:
                if activity.get("type") == kind:
                    return activity
        return None

    def metro_leg(plan):
        for day in plan["itinerary"]:
            for activity in day["activities"]:
                for leg in activity.get("transports") or []:
                    if leg.get("mode") == "metro":
                        return leg
        return None

    mutations = {}

    def add(name, fn):
        mutations[name] = fn

    def mut_ungrounded(p):
        activity = first(p, "attraction")
        if activity:
            activity["position"] = "ShortTrip Nonexistent Attraction"
        return "attraction name not in sandbox"

    def mut_meal_time(p):
        activity = first(p, "lunch") or first(p, "dinner")
        if activity:
            activity["start_time"] = "14:00"
            activity["end_time"] = "14:30"
        return "meal starts at the closed boundary"

    def mut_leg_price(p):
        leg = metro_leg(p)
        if leg:
            leg["price"] = float(leg["price"]) + 1.0
        return "metro fare changed by 1 CNY"

    def mut_drop_tickets(p):
        leg = metro_leg(p)
        if leg:
            leg.pop("tickets", None)
        return "metro leg loses its ticket count"

    def mut_overlap(p):
        activity = first(p, "attraction")
        if activity:
            activity["start_time"] = activity["start_time"]
            day = p["itinerary"][0]["activities"]
            if len(day) > 2:
                target = day[2]
                target["start_time"] = day[1]["end_time"]
        return "activity starts before the previous one ends"

    def mut_same_position(p):
        day = p["itinerary"][0]["activities"]
        if len(day) > 2:
            day[2]["transports"] = [
                {
                    "start": day[1].get("position"),
                    "end": day[2].get("position"),
                    "mode": "walk",
                    "start_time": day[1]["end_time"],
                    "end_time": day[2]["start_time"],
                    "price": 0,
                    "cost": 0,
                    "distance": 0.1,
                }
            ]
        return "transports attached between identical positions"

    def mut_room_type(p):
        for day in p["itinerary"]:
            for activity in day["activities"]:
                if activity.get("type") == "accommodation":
                    activity["room_type"] = 99
                    return "hotel room type does not match the table"
        return "no hotel in this plan"

    def mut_unknown_type(p):
        activity = first(p, "attraction")
        if activity:
            activity["type"] = "museum"
        return "unknown activity type"

    def mut_train_id(p):
        last = p["itinerary"][-1]["activities"][-1]
        if last.get("TripID") or last.get("TrainID"):
            last["TrainID"] = "X0000"
        return "intercity train id not in the sandbox"

    add("ungrounded_attraction", mut_ungrounded)
    add("meal_time_boundary", mut_meal_time)
    add("leg_price_off_by_one", mut_leg_price)
    add("leg_missing_tickets", mut_drop_tickets)
    add("overlap", mut_overlap)
    add("same_position_transports", mut_same_position)
    add("room_type_mismatch", mut_room_type)
    add("unknown_activity_type", mut_unknown_type)
    add("intercity_id", mut_train_id)

    baseline = check_plan(query, plan)
    results = []
    for name, fn in mutations.items():
        mutated = copy.deepcopy(plan)
        note = fn(mutated)
        report = check_plan(query, mutated)
        results.append(
            {
                "mutation": name,
                "intent": note,
                "detected": (not report.commonsense_ok) or (not report.hard_ok),
                "commonsense_violations": report.commonsense_violations,
                "hard_regressions": sum(
                    1
                    for a, b in zip(baseline.hard_results, report.hard_results)
                    if a and not b
                ),
            }
        )
    return results


# --------------------------------------------------------------------- E2
def baseline_block(env, queries: dict[str, list[dict]], limits: dict[str, int]) -> dict:
    planner = SkeletonPlanner(env)
    engine = RepairEngine(env, max_evaluations=25)
    out: dict = {"splits": {}, "config": {"limits": limits}}
    for split, items in queries.items():
        rows = []
        started = time.time()
        for query in items:
            row = {"uid": query["uid"]}
            build = planner.build(query)
            row["constructed"] = build.plan is not None
            if build.report:
                row["schema_ok"] = build.report.schema_ok
                row["commonsense_ok"] = build.report.commonsense_ok
                row["hard_pass"] = build.report.hard_pass_count
                row["hard_total"] = len(build.report.hard_results)
                row["all_ok"] = build.report.all_ok
            if build.plan is None:
                rows.append(row)
                continue
            repaired = engine.repair(query, build.plan, build.report)
            row["repaired_hard_pass"] = repaired.report.hard_pass_count
            row["repaired_all_ok"] = repaired.report.all_ok
            row["repair_evaluations"] = repaired.evaluations
            rows.append(row)
        out["splits"][split] = {
            "queries": rows,
            "n": len(rows),
            "constructed": sum(1 for r in rows if r.get("constructed")),
            "commonsense_ok": sum(1 for r in rows if r.get("commonsense_ok")),
            "all_ok_before": sum(1 for r in rows if r.get("all_ok")),
            "all_ok_after": sum(1 for r in rows if r.get("repaired_all_ok")),
            "hard_pass_before": sum(r.get("hard_pass", 0) for r in rows),
            "hard_pass_after": sum(r.get("repaired_hard_pass", 0) for r in rows),
            "hard_total": sum(r.get("hard_total", 0) for r in rows),
            "seconds": round(time.time() - started, 1),
        }
    return out


# --------------------------------------------------------------------- main
def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    env = get_env("zh")
    limits = {split: 12 for split in SPLITS}

    queries = {split: load_queries(split, limits[split]) for split in SPLITS}

    # E2 first: it also produces the valid seeds used by E3/E4
    print("E2 baseline ...", flush=True)
    baseline = baseline_block(env, queries, limits)
    (RESULTS / "e2_baseline.json").write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # E1 mutation study on the first valid plan we can build
    print("E1 mutation study ...", flush=True)
    planner = SkeletonPlanner(env)
    mutation_rows = []
    for query in queries["human"] + queries["medium"] + queries["easy"]:
        build = planner.build(query)
        if build.ok:
            mutation_rows = mutation_study(env, query, build.plan)
            mutation_source = query["uid"]
            break
    (RESULTS / "e1_mutations.json").write_text(
        json.dumps(
            {"source_query": locals().get("mutation_source"), "rows": mutation_rows},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("E3 repair dataset ...", flush=True)
    repair_queries = queries["human"] + queries["medium"] + queries["easy"]
    repair_summary = build_repair_cases(
        env, planner, repair_queries, max_cases=40, out_dir=ROOT / "datasets" / "shorttrip_repair"
    )
    (RESULTS / "e3_repair.json").write_text(
        json.dumps(repair_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("E4 infeasible dataset ...", flush=True)
    infeasible_summary = build_infeasible_cases(
        env,
        planner,
        repair_queries,
        per_kind=6,
        out_dir=ROOT / "datasets" / "shorttrip_infeasible",
    )
    (RESULTS / "e4_infeasible.json").write_text(
        json.dumps(infeasible_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    markdown = render_markdown(baseline, mutation_rows, repair_summary, infeasible_summary)
    (RESULTS / "experiment_tables.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


def render_markdown(baseline: dict, mutations: list[dict], repair: dict, infeasible: dict) -> str:
    lines = ["# ShortTrip-on-ChinaTravel 实验结果", ""]
    lines += ["## E2 确定性构造 + 有界修复（官方 checker 判分）", ""]
    lines += [
        "| split | n | 构造成功 | Commonsense 通过 | 修复前全通过 | 修复后全通过 | hard 通过(前/后/总) | 秒 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for split, info in baseline["splits"].items():
        lines.append(
            f"| {split} | {info['n']} | {info['constructed']} | {info['commonsense_ok']} | "
            f"{info['all_ok_before']} | {info['all_ok_after']} | "
            f"{info['hard_pass_before']}/{info['hard_pass_after']}/{info['hard_total']} | {info['seconds']} |"
        )
    lines += [
        "",
        "## E1 Checker 变异检测",
        "",
        "| 变异 | 是否检出 | 触发的 commonsense 列 | DSL 回归 |",
        "| --- | --- | --- | --- |",
    ]
    for row in mutations:
        cols = ", ".join(row["commonsense_violations"]) or "-"
        detected = "是" if row["detected"] else "否"
        lines.append(f"| {row['mutation']} | {detected} | {cols} | {row['hard_regressions']} |")
    lines += ["", "## E3 动态修复数据集 (shorttrip_repair)", ""]
    lines += [
        f"- 用例数：{repair['cases']}（来自 {repair['seeds_valid']} 个有效基础方案）",
        f"- 修复成功率：{repair['repair_success']}/{repair['cases']} = {repair['repair_success_rate']}",
        f"- 锁定项保持：{repair['lock_preserved']}",
        f"- 平均改动代价：{repair['mean_change_cost']}",
        "",
        "| 扰动类型 | 用例 | 修复成功 |",
        "| --- | --- | --- |",
    ]
    for kind, info in repair["by_disruption"].items():
        lines.append(f"| {kind} | {info['cases']} | {info['success']} |")
    lines += ["", "## E4 无解解释数据集 (shorttrip_infeasible)", ""]
    lines += [
        f"- 用例数：{infeasible['cases']}",
        f"- 分类准确率：{infeasible['classification_accuracy']}",
        f"- 把“可行但超预算”误判为“确认冲突”的次数：{infeasible['false_infeasible_claims']}",
        "",
        "| 真实类别 | 预测类别 | 求解器是否解出 |",
        "| --- | --- | --- |",
    ]
    for row in infeasible["confusion"]:
        lines.append(f"| {row['kind']} | {row['pred']} | {row['solved']} |")
    return "\n".join(lines) + "\n"
