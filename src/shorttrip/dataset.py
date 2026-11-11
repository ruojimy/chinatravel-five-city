"""Dataset variants for the ShortTrip architecture, built on ChinaTravel data.

Three variants, each addressing a capability the ChinaTravel release does not
cover:

* V1 ``shorttrip_repair``      -- post-confirmation repair under a disruption,
                                 with locked arrangements and a change-cost metric.
* V2 ``shorttrip_infeasible``  -- labelled "no solution" cases with a *provable*
                                 cause (confirmed conflict / feasible-but-out-of-
                                 budget / missing key data).
* V3 ``shorttrip_preference``  -- questionnaire-style preference profiles attached
                                 to the preference splits.

Disruptions are expressed as extra DSL constraints appended to the original
query, so the official evaluator stays the single source of truth and the
"damaged" plan is genuinely invalid while the original plan stays valid for the
original query.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from .checker import check_plan
from .env import SandboxEnv, hhmm, minutes
from .repair import RepairEngine
from .scheduler import extract_content, lookup_row


# --------------------------------------------------------------------- helpers
def dsl_return_departure(op: str, clock: str) -> str:
    return (
        "return_start_time = 0\n"
        "for activity in allactivities(plan):\n"
        "  if activity_type(activity) in ['train','airplane'] and "
        "intercity_transport_origin(activity) == target_city(plan): "
        "return_start_time = activity_start_time(activity)\n"
        f"result=(return_start_time{op}'{clock}')"
    )


def dsl_go_departure(op: str, clock: str) -> str:
    return (
        "go_start_time = 0\n"
        "for activity in allactivities(plan):\n"
        "  if activity_type(activity) in ['train','airplane'] and "
        "intercity_transport_origin(activity) == start_city(plan): "
        "go_start_time = activity_start_time(activity)\n"
        f"result=(go_start_time{op}'{clock}')"
    )


def dsl_forbid_name(kind: str, name: str) -> str:
    if kind == "attraction":
        condition = "activity_type(activity)=='attraction'"
        variable = "attraction_name_set"
    elif kind == "restaurant":
        condition = "activity_type(activity) in ['breakfast', 'lunch', 'dinner']"
        variable = "restaurant_name_set"
    else:
        condition = "activity_type(activity)=='accommodation'"
        variable = "accommodation_name_set"
    return (
        f"{variable}=set()\n"
        "for activity in allactivities(plan):\n"
        f"  if {condition}: {variable}.add(activity_position(activity))\n"
        f"result=not({{{json.dumps(name, ensure_ascii=False)}}}&{variable})"
    )


def locked_activity(plan: dict) -> dict | None:
    """Pick the arrangement the user refuses to change (a fixed dinner slot)."""
    for day in plan["itinerary"]:
        for activity in day["activities"]:
            if activity.get("type") == "dinner":
                return {
                    "kind": "dinner",
                    "position": activity["position"],
                    "start_time": activity["start_time"],
                    "end_time": activity["end_time"],
                }
    for day in plan["itinerary"]:
        for activity in day["activities"]:
            if activity.get("type") == "attraction":
                return {
                    "kind": "attraction",
                    "position": activity["position"],
                    "start_time": activity["start_time"],
                    "end_time": activity["end_time"],
                }
    return None


def lock_holds(plan: dict, lock: dict) -> bool:
    for day in plan.get("itinerary", []):
        for activity in day["activities"]:
            if activity.get("position") == lock["position"]:
                return activity.get("start_time") == lock["start_time"]
    return False


def change_cost(original: dict, repaired: dict, *, shift_tolerance: int = 15) -> dict:
    """Minimal-edit distance between two itineraries (our '修改代价')."""

    def key(activity: dict) -> str:
        return f"{activity.get('type')}|{activity.get('position', activity.get('start'))}"

    before = {
        key(a): a
        for day in original.get("itinerary", [])
        for a in day["activities"]
    }
    after = {
        key(a): a
        for day in repaired.get("itinerary", [])
        for a in day["activities"]
    }
    removed = [k for k in before if k not in after]
    added = [k for k in after if k not in before]
    shifted = [
        k
        for k in before
        if k in after and before[k].get("start_time") != after[k].get("start_time")
    ]
    big_shift = [
        k
        for k in shifted
        if abs(minutes(before[k]["start_time"]) - minutes(after[k]["start_time"])) > shift_tolerance
    ]
    return {
        "removed": len(removed),
        "added": len(added),
        "moved": len(big_shift),
        "retimed": len(shifted) - len(big_shift),
        "total": len(removed) + len(added) + len(big_shift),
        "details": {"removed": removed, "added": added, "moved": big_shift},
    }


# ------------------------------------------------------------------ V1 builder
@dataclass
class RepairCase:
    uid: str
    source_uid: str
    disruption: str
    query: dict
    seed_plan: dict
    locked: dict | None
    feasible: bool
    witness: dict | None
    witness_report: dict | None
    witness_cost: dict | None
    seed_violations: list[str] = field(default_factory=list)

    def to_record(self) -> dict:
        return {
            "uid": self.uid,
            "source_uid": self.source_uid,
            "disruption": self.disruption,
            "query": self.query,
            "seed_plan": self.seed_plan,
            "locked": self.locked,
            "feasible": self.feasible,
            "witness": self.witness,
            "witness_report": self.witness_report,
            "witness_cost": self.witness_cost,
            "seed_violations": self.seed_violations,
        }


def _with_extra_constraints(query: dict, extra: list[dict]) -> dict:
    new_query = json.loads(json.dumps(query, ensure_ascii=False))
    codes = list(new_query.get("hard_logic_py") or [])
    for item in extra:
        codes.append(item["code"])
    new_query["hard_logic_py"] = codes
    new_query["disruption"] = extra
    return new_query


def inject_disruptions(
    env: SandboxEnv, query: dict, plan: dict, rng: random.Random
) -> list[dict]:
    """Return disruption descriptors; each is also an extra DSL constraint.

    A `delay` is only emitted when a later train actually exists, so every case
    in the released variant is repairable *by construction* unless the case is
    explicitly tagged otherwise.
    """
    out: list[dict] = []
    attractions = [
        (day["day"], activity)
        for day in plan["itinerary"]
        for activity in day["activities"]
        if activity.get("type") == "attraction"
    ]
    restaurants = [
        (day["day"], activity)
        for day in plan["itinerary"]
        for activity in day["activities"]
        if activity.get("type") in ("lunch", "dinner")
    ]
    if attractions:
        _, target = rng.choice(attractions)
        out.append(
            {
                "kind": "closure",
                "name": target["position"],
                "code": dsl_forbid_name("attraction", target["position"]),
                "note": f"attraction {target['position']} is closed all day",
            }
        )
    if restaurants:
        _, target = rng.choice(restaurants)
        out.append(
            {
                "kind": "closure",
                "name": target["position"],
                "code": dsl_forbid_name("restaurant", target["position"]),
                "note": f"restaurant {target['position']} is closed all day",
            }
        )
    first = plan["itinerary"][0]["activities"][0]
    if first.get("type") in ("train", "airplane"):
        target_clock = minutes(first["start_time"]) + 60
        later = [
            record
            for record in env.trains(query["start_city"], query["target_city"])
            if minutes(record["BeginTime"]) >= target_clock
            and minutes(record["EndTime"]) <= 21 * 60
        ]
        if later:
            new_clock = min(minutes(r["BeginTime"]) for r in later)
            out.append(
                {
                    "kind": "go_delay",
                    "code": dsl_go_departure(">=", hhmm(new_clock)),
                    "note": (
                        f"outbound train delayed: earliest acceptable departure {hhmm(new_clock)} "
                        f"(original {first['start_time']})"
                    ),
                    "later_options": len(later),
                }
            )
    last = plan["itinerary"][-1]["activities"][-1]
    if last.get("type") in ("train", "airplane"):
        target_clock = minutes(last["start_time"]) + 45
        later = [
            record
            for record in env.trains(query["target_city"], query["start_city"])
            if minutes(record["BeginTime"]) >= target_clock
        ]
        if later:
            new_clock = min(minutes(r["BeginTime"]) for r in later)
            out.append(
                {
                    "kind": "delay",
                    "code": dsl_return_departure(">=", hhmm(new_clock)),
                    "note": (
                        f"return train delayed: earliest acceptable departure "
                        f"{hhmm(new_clock)} (after {last['start_time']})"
                    ),
                    "later_options": len(later),
                }
            )
    out.append(
        {
            "kind": "early_departure",
            "code": dsl_return_departure("<=", "15:30"),
            "note": "traveller must be at the station by 15:30",
        }
    )
    return out


def build_repair_cases(
    env: SandboxEnv,
    planner,
    queries: list[dict],
    *,
    max_cases: int = 20,
    seed: int = 20261010,
    out_dir: Path,
) -> dict:
    rng = random.Random(seed)
    engine = RepairEngine(env, max_evaluations=30)
    records: list[dict] = []
    stats = {
        "queries_considered": 0,
        "seeds_valid": 0,
        "cases": 0,
        "repair_success": 0,
        "lock_preserved": 0,
        "by_disruption": {},
        "change_cost": [],
    }
    for query in queries:
        if len(records) >= max_cases:
            break
        stats["queries_considered"] += 1
        built = planner.build(query)
        if built.plan is None:
            continue
        plan = built.plan
        seed_report = built.report or check_plan(query, plan)
        if not seed_report.all_ok:
            seed_repair = engine.repair(query, plan, seed_report)
            if not seed_repair.report.all_ok:
                continue
            plan = seed_repair.plan
        stats["seeds_valid"] += 1
        disruptions = inject_disruptions(env, query, plan, rng)
        if not disruptions:
            continue
        for disruption in disruptions:
            if len(records) >= max_cases:
                break
            new_query = _with_extra_constraints(query, [disruption])
            seed_report = check_plan(new_query, plan)
            if seed_report.hard_ok:
                continue
            locked = locked_activity(plan)
            repaired = engine.repair(new_query, plan, seed_report)
            feasible = bool(repaired.report.all_ok and (locked is None or lock_holds(repaired.plan, locked)))
            cost = change_cost(plan, repaired.plan) if repaired.plan else None
            label = disruption["kind"]
            if disruption.get("name"):
                label = f"{label}_{abs(hash(disruption['name'])) % 100000:05d}"
            uid = f"repair_{query['uid']}_{label}"
            new_query = dict(new_query)
            new_query["uid"] = uid
            new_query["tag"] = "shorttrip_repair"
            new_query["source_uid"] = query["uid"]
            new_query["disruption_kind"] = disruption["kind"]
            record = RepairCase(
                uid=uid,
                source_uid=query["uid"],
                disruption=disruption["kind"],
                query=new_query,
                seed_plan=plan,
                locked=locked,
                feasible=feasible,
                witness=repaired.plan if feasible else None,
                witness_report=repaired.report.to_dict(),
                witness_cost=cost if feasible else None,
                seed_violations=seed_report.commonsense_violations
                + [f"failed DSL {i}" for i, ok in enumerate(seed_report.hard_results) if not ok],
            ).to_record()
            records.append(record)
            stats["cases"] += 1
            stats["repair_success"] += int(feasible)
            stats["lock_preserved"] += int(
                feasible and locked is not None and lock_holds(repaired.plan, locked)
            )
            bucket = stats["by_disruption"].setdefault(
                disruption["kind"], {"cases": 0, "success": 0}
            )
            bucket["cases"] += 1
            bucket["success"] += int(feasible)
            if cost:
                stats["change_cost"].append(cost["total"])

    out_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        (out_dir / f"{record['uid']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    summary = {
        "variant": "shorttrip_repair",
        "cases": len(records),
        "repair_success": stats["repair_success"],
        "repair_success_rate": round(stats["repair_success"] / max(1, len(records)), 4),
        "lock_preserved": stats["lock_preserved"],
        "by_disruption": stats["by_disruption"],
        "mean_change_cost": round(
            sum(stats["change_cost"]) / max(1, len(stats["change_cost"])), 3
        ),
        "seeds_valid": stats["seeds_valid"],
        "queries_considered": stats["queries_considered"],
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
