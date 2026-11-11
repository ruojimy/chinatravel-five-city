"""P3 step 1: generate a diverse candidate pool (>=8 feasible plans per query).

Why this is the precondition for an honest human benchmark: with only 3 variants the
model's "regret = 0" is a small-pool artefact. A pairwise human evaluation needs plans
that a person would actually consider different — different attractions, different
order, different cost — while every one of them still passes the official checker.

Operators (none of them touches feasibility logic):
  * attractions per day: 2 / 3
  * departure window: early / mid / late
  * candidate ordering: distance / price / duration
  * intra-city mode preference: metro / taxi

Deduplication is by itinerary signature (ordered list of positions), so the pool size
reported here is the number of *distinct* plans, not the number of configurations
attempted.

Outputs
  results/p7_human_evaluation/pools.json
  results/p7_human_evaluation/pools.md
"""
from __future__ import annotations

import glob
import json
import sys
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.checker import check_plan  # noqa: E402
from shorttrip.env import get_env  # noqa: E402
from shorttrip.planner import PlannerOptions, SkeletonPlanner  # noqa: E402

OUT = ROOT / "results" / "p7_human_evaluation"
REPO = ROOT / "ChinaTravel"

WINDOWS = {"early": (7 * 60, 11 * 60), "mid": (8 * 60, 13 * 60), "late": (9 * 60, 14 * 60)}
COMBOS = list(product((2, 3), ("early", "mid", "late"), ("distance", "price", "duration"),
                      ("metro", "taxi")))


def load_queries(split: str, limit: int) -> list[dict]:
    paths = sorted(glob.glob(str(REPO / "chinatravel" / "data" / split / "*.json")))
    return [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths[:limit]]


def signature(plan: dict) -> str:
    return "|".join(
        f'{activity.get("position") or activity.get("start")}@{activity.get("start_time")}'
        for day in plan.get("itinerary", []) for activity in day.get("activities", []))


def plan_stats(plan: dict) -> dict:
    attractions = []
    total_cost = 0.0
    transit_minutes = 0.0
    for day in plan.get("itinerary", []):
        for activity in day.get("activities", []):
            total_cost += float(activity.get("cost") or 0)
            for leg in activity.get("transports") or []:
                total_cost += float(leg.get("cost") or 0)
                try:
                    start = str(leg.get("start_time")).split(":")
                    end = str(leg.get("end_time")).split(":")
                    transit_minutes += (int(end[0]) * 60 + int(end[1])) - (int(start[0]) * 60 + int(start[1]))
                except (IndexError, ValueError):
                    pass
            if activity.get("type") == "attraction":
                attractions.append(activity.get("position"))
    return {"attractions": attractions, "n_attractions": len(attractions),
            "cost": round(total_cost, 1), "transit_minutes": round(transit_minutes, 1)}


def main() -> int:
    split = sys.argv[1] if len(sys.argv) > 1 else "easy_short"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    target = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    env = get_env("zh")
    queries = load_queries(split, limit)
    print(f"queries={len(queries)} combos={len(COMBOS)} target_pool={target}")

    pools = []
    for query in queries:
        seen: dict[str, dict] = {}
        attempted = 0
        rejected = 0
        for count, window, order, mode in COMBOS:
            attempted += 1
            options = PlannerOptions(max_attractions_per_day=count,
                                     go_window=WINDOWS[window],
                                     order_by=order, prefer_mode=mode)
            planner = SkeletonPlanner(env, options)
            built = planner.build(query, deep_check=False)
            if built.plan is None:
                continue
            report = check_plan(query, built.plan)
            if not report.all_ok:
                rejected += 1
                continue
            sig = signature(built.plan)
            if sig in seen:
                continue
            stats = plan_stats(built.plan)
            seen[sig] = {
                "signature": sig,
                "config": {"attractions_per_day": count, "window": window,
                           "order_by": order, "mode": mode},
                "stats": stats,
                "plan": built.plan,
            }
        pool = list(seen.values())
        # diversity: how many distinct attractions appear across the pool
        universe = {name for item in pool for name in item["stats"]["attractions"]}
        pools.append({
            "uid": query.get("uid"),
            "city": query.get("target_city"),
            "days": query.get("days"),
            "people": query.get("people_number"),
            "nature_language": query.get("nature_language"),
            "attempted": attempted,
            "rejected_by_checker": rejected,
            "pool_size": len(pool),
            "meets_target": len(pool) >= target,
            "distinct_attractions_in_pool": len(universe),
            "candidates": pool,
        })
        print(f"  {query.get('uid')} {query.get('target_city')}: pool={len(pool)} "
              f"(rejected={rejected}, distinct_attractions={len(universe)})")

    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": "2026-10-22",
        "split": split,
        "target_pool_size": target,
        "pools": pools,
        "summary": {
            "queries": len(pools),
            "meeting_target": sum(1 for pool in pools if pool["meets_target"]),
            "pool_sizes": [pool["pool_size"] for pool in pools],
            "all_candidates_pass_checker": True,
        },
    }
    (OUT / "pools.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# P3 候选池生成（每条查询 ≥8 个实质不同的可行方案）", "",
             "| 查询 | 城市 | 天数 | 候选人方案 | 达标 | 池内不同景点数 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for pool in pools:
        lines.append(f'| `{pool["uid"]}` | {pool["city"]} | {pool["days"]} | '
                     f'{pool["pool_size"]} | {"✅" if pool["meets_target"] else "❌"} | '
                     f'{pool["distinct_attractions_in_pool"]} |')
    lines += ["", "所有候选均通过官方 checker（schema + commonsense + hard DSL）；"
                  "去重按 itinerary 签名，池大小是不同方案数，不是尝试次数。"]
    (OUT / "pools.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    print("wrote", OUT / "pools.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
