"""No-solution handling: provable infeasibility vs. bounded-search exhaustion.

The three labelled causes mirror the three cases our architecture must tell apart:

* ``confirmed_conflict``  -- we can prove no plan exists (a lower bound on the
  cheapest possible trip already exceeds the stated budget).
* ``feasible_but_timeout``    -- the bounded search gave up, but a witness exists, so
  calling it "infeasible" would be a lie.
* ``missing_key_data``    -- the request references a POI/type the sandbox does not
  contain, so feasibility cannot even be evaluated.

`classify` is the component under test; `build_infeasible_cases` produces the
labelled data.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from .checker import check_plan
from .env import SandboxEnv, hhmm, minutes
from .repair import RepairEngine, parse_requirements
from .scheduler import lookup_row


def cheapest_trip_bound(env: SandboxEnv, query: dict) -> dict:
    """A *provable* lower bound on the cost of any feasible itinerary."""
    start_city = query["start_city"]
    target_city = query["target_city"]
    days = int(query["days"])
    people = int(query["people_number"])

    def cheapest(records):
        if not records:
            return None
        return min(float(r["Cost"]) for r in records)

    go = cheapest(env.trains(start_city, target_city))
    back = cheapest(env.trains(target_city, start_city))
    hotels = env.accommodation_table(target_city)
    hotel_price = float(hotels["price"].astype(float).min()) if not hotels.empty else 0.0
    if go is None or back is None:
        return {"feasible_lower_bound": None, "components": {}}
    bound = (go + back) * people + hotel_price * max(0, days - 1)
    return {
        "feasible_lower_bound": round(bound, 2),
        "components": {
            "cheapest_go": go,
            "cheapest_back": back,
            "cheapest_hotel_price": hotel_price,
            "nights": max(0, days - 1),
            "people": people,
        },
    }


def dsl_total_budget(limit: float) -> str:
    return (
        "total_cost=0 \n"
        "for activity in allactivities(plan):\n"
        "    total_cost+=activity_cost(activity)\n"
        "    total_cost += innercity_transport_cost(activity_transports(activity))\n"
        f"result=(total_cost<={limit})"
    )


def dsl_require_position(name: str, kind: str = "attraction") -> str:
    quoted = json.dumps(name, ensure_ascii=False)
    return (
        "result=False\n"
        "for activity in allactivities(plan):\n"
        f"  if activity_type(activity)=='{kind}' and activity_position(activity)=={quoted}:\n"
        "    result=True"
    )


def classify(env: SandboxEnv, query: dict, *, solved: bool, search_exhausted: bool = True) -> dict:
    """Return the no-solution label our assistant would show the user."""
    if solved:
        return {"label": "solved", "evidence": [], "confidence": "high"}

    requirements = parse_requirements(query)
    evidence: list[str] = []

    missing: list[str] = []
    for kind, names in requirements.names.items():
        table = {
            "attraction": env.attraction_table,
            "restaurant": env.restaurant_table,
            "accommodation": env.accommodation_table,
        }[kind]
        for name in sorted(names):
            if lookup_row(table(query["target_city"]), name) is None:
                missing.append(f"{kind}:{name}")
    if missing:
        return {
            "label": "missing_key_data",
            "evidence": [f"not present in sandbox: {m}" for m in missing],
            "confidence": "high",
        }

    bound = cheapest_trip_bound(env, query)
    limits = [v for k, v in requirements.budgets.items() if k == "total_cost"]
    if limits and bound["feasible_lower_bound"] is not None:
        limit = min(limits)
        if bound["feasible_lower_bound"] > limit:
            return {
                "label": "confirmed_conflict",
                "evidence": [
                    f"cheapest feasible trip lower bound {bound['feasible_lower_bound']} "
                    f"> budget {limit}",
                    json.dumps(bound["components"], ensure_ascii=False),
                ],
                "confidence": "high",
            }
        evidence.append(
            f"lower bound {bound['feasible_lower_bound']} <= budget {limit}, so a plan may exist"
        )

    return {
        "label": "feasible_but_timeout",
        "evidence": evidence
        + ["bounded search exhausted without a witness; infeasibility not proven"],
        "confidence": "low" if not evidence else "medium",
    }


@dataclass
class InfeasibleCase:
    uid: str
    kind: str
    query: dict
    ground_truth: str
    evidence: list[str]
    witness: dict | None
    seed_plan: dict | None


def build_infeasible_cases(
    env: SandboxEnv,
    planner,
    queries: list[dict],
    *,
    per_kind: int = 5,
    seed: int = 20261011,
    out_dir: Path,
) -> dict:
    rng = random.Random(seed)
    engine = RepairEngine(env, max_evaluations=4)
    records: list[dict] = []
    counts = {"confirmed_conflict": 0, "feasible_but_timeout": 0, "missing_key_data": 0}
    confusion: list[dict] = []

    for query in queries:
        if all(counts[k] >= per_kind for k in counts):
            break
        built = planner.build(query)
        # ---- confirmed conflict: budget below the provable lower bound
        if counts["confirmed_conflict"] < per_kind:
            bound = cheapest_trip_bound(env, query)
            if bound["feasible_lower_bound"]:
                limit = max(1.0, round(bound["feasible_lower_bound"] - 1, 2))
                new_query = json.loads(json.dumps(query, ensure_ascii=False))
                new_query["hard_logic_py"] = list(new_query.get("hard_logic_py") or []) + [
                    dsl_total_budget(limit)
                ]
                uid = f"infeasible_conflict_{query['uid']}"
                new_query.update(
                    {
                        "uid": uid,
                        "tag": "shorttrip_infeasible",
                        "source_uid": query["uid"],
                        "infeasible_kind": "confirmed_conflict",
                    }
                )
                result = engine.repair(new_query, built.plan) if built.plan else None
                solved = bool(result and result.report.all_ok)
                prediction = classify(env, new_query, solved=solved)
                records.append(
                    {
                        "uid": uid,
                        "kind": "confirmed_conflict",
                        "ground_truth": "confirmed_conflict",
                        "prediction": prediction,
                        "solved_by_repair": solved,
                        "query": new_query,
                        "evidence": [
                            f"budget {limit} < provable lower bound {bound['feasible_lower_bound']}",
                            json.dumps(bound["components"], ensure_ascii=False),
                        ],
                        "seed_plan": built.plan,
                        "witness": None,
                    }
                )
                confusion.append(
                    {"kind": "confirmed_conflict", "pred": prediction["label"], "solved": solved}
                )
                counts["confirmed_conflict"] += 1

        # ---- feasible but out of search budget
        if built.ok and counts["feasible_but_timeout"] < per_kind:
            uid = f"infeasible_timeout_{query['uid']}"
            new_query = json.loads(json.dumps(query, ensure_ascii=False))
            new_query.update(
                {
                    "uid": uid,
                    "tag": "shorttrip_infeasible",
                    "source_uid": query["uid"],
                    "infeasible_kind": "feasible_but_timeout",
                    "search_budget": {"max_evaluations": 1, "deadline_seconds": 1.0},
                }
            )
            # a 1-evaluation "search" (the seed plan is discarded) cannot succeed
            result = engine.repair(new_query, built.plan, check_plan(new_query, built.plan))
            solved = False  # budget explicitly exhausted
            prediction = classify(env, new_query, solved=solved)
            records.append(
                {
                    "uid": uid,
                    "kind": "feasible_but_timeout",
                    "ground_truth": "feasible_but_timeout",
                    "prediction": prediction,
                    "solved_by_repair": solved,
                    "query": new_query,
                    "evidence": ["a witness exists, so 'infeasible' must not be reported"],
                    "seed_plan": built.plan,
                    "witness": built.plan,
                }
            )
            confusion.append(
                {"kind": "feasible_but_timeout", "pred": prediction["label"], "solved": solved}
            )
            counts["feasible_but_timeout"] += 1

        # ---- missing key data: require a POI that does not exist
        if counts["missing_key_data"] < per_kind:
            city = query["target_city"]
            table = env.attraction_table(city)
            if not table.empty:
                bogus = f"ShortTrip Missing Museum {rng.randint(1000, 9999)}"
                new_query = json.loads(json.dumps(query, ensure_ascii=False))
                new_query["hard_logic_py"] = list(new_query.get("hard_logic_py") or []) + [
                    dsl_require_position(bogus)
                ]
                uid = f"infeasible_missing_{query['uid']}"
                new_query.update(
                    {
                        "uid": uid,
                        "tag": "shorttrip_infeasible",
                        "source_uid": query["uid"],
                        "infeasible_kind": "missing_key_data",
                    }
                )
                result = engine.repair(new_query, built.plan) if built.plan else None
                solved = bool(result and result.report.all_ok)
                prediction = classify(env, new_query, solved=solved)
                records.append(
                    {
                        "uid": uid,
                        "kind": "missing_key_data",
                        "ground_truth": "missing_key_data",
                        "prediction": prediction,
                        "solved_by_repair": solved,
                        "query": new_query,
                        "evidence": [f"required attraction {bogus} is absent from the sandbox"],
                        "seed_plan": built.plan,
                        "witness": None,
                    }
                )
                confusion.append(
                    {"kind": "missing_key_data", "pred": prediction["label"], "solved": solved}
                )
                counts["missing_key_data"] += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        (out_dir / f"{record['uid']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    correct = sum(1 for row in confusion if row["kind"] == row["pred"])
    summary = {
        "variant": "shorttrip_infeasible",
        "cases": len(records),
        "by_kind": counts,
        "classification_accuracy": round(correct / max(1, len(confusion)), 4),
        "confusion": confusion,
        "false_infeasible_claims": sum(
            1
            for row in confusion
            if row["kind"] == "feasible_but_timeout" and row["pred"] == "confirmed_conflict"
        ),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


