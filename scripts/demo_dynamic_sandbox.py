"""Demo: gap-triggered dynamic sandbox update.

Three cases:
  A. 南越王博物院 (Guangzhou)   -- real POI missing from the 2026.08 sandbox
  B. 上海博物馆东馆 (Shanghai)   -- recently opened, missing
  C. 一个不存在的场馆             -- gate must reject (no authoritative evidence)

For each case we measure, before and after the update:
  * sandbox table visibility
  * goto resolvability (can a route be computed to it?)
  * Is_attractions_correct on a plan activity referencing it
  * whether the same query can now be planned
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.checker import check_plan  # noqa: E402
from shorttrip.dynamic.overlay import OverlayStore  # noqa: E402
from shorttrip.dynamic.pipeline import UpdatePipeline, rehydrate  # noqa: E402
from shorttrip.dynamic.records import DataRequest  # noqa: E402
from shorttrip.env import get_env  # noqa: E402
from shorttrip.planner import SkeletonPlanner  # noqa: E402
from shorttrip.repair import RepairEngine  # noqa: E402

from chinatravel.symbol_verification.commonsense_constraint import (  # noqa: E402
    Is_attractions_correct,
    _set_tool_lang,
)

RESULTS = ROOT / "results" / "dynamic_update"


def table_has(env, city: str, name: str) -> bool:
    table = env.attraction_table(city)
    return name in set(table["name"].astype(str))


def goto_ok(env, city: str, name: str) -> tuple[bool, str]:
    mode = env.best_mode(city, "广州塔" if city == "广州" else "人民广场", name)
    return mode is not None, str(mode)


def checker_accepts(city: str, name: str, record: dict | None) -> tuple[bool, list[str]]:
    """Run the real Is_attractions_correct on a one-activity day."""
    record = record or {}
    open_t = record.get("opentime") or "09:00"
    close_t = record.get("endtime") or "17:00"
    price = float(record.get("price") or 0)
    activity = {
        "position": name,
        "type": "attraction",
        "price": price,
        "cost": price,
        "tickets": 1,
        "start_time": open_t,
        "end_time": close_t,
        "transports": [],
    }
    plan = {
        "people_number": 1,
        "start_city": "上海",
        "target_city": city,
        "itinerary": [{"day": 1, "activities": [activity]}],
    }
    _set_tool_lang("zh")
    table, info = Is_attractions_correct({"target_city": city}, plan)
    return bool(table.loc[0].sum() == 0), list(info)


def probe(env, city: str, name: str, record: dict | None = None) -> dict:
    visible = table_has(env, city, name)
    routable, mode = goto_ok(env, city, name)
    accepted, info = checker_accepts(city, name, record)
    return {
        "table_visible": visible,
        "goto_routable": routable,
        "goto_mode": mode,
        "checker_accepts": accepted,
        "checker_info": [str(item)[:160] for item in info],
    }


def build_query(city: str, name: str) -> dict:
    return {
        "uid": f"dyn_{city}_{abs(hash(name)) % 100000}",
        "start_city": "上海" if city != "上海" else "南京",
        "target_city": city,
        "days": 1,
        "people_number": 1,
        "hard_logic_py": [
            "result=(day_count(plan)==1)",
            "result=(people_count(plan)==1)",
            (
                "attraction_name_set=set()\n"
                "for activity in allactivities(plan):\n"
                "  if activity_type(activity)=='attraction': attraction_name_set.add(activity_position(activity))\n"
                f'result=({{"{name}"}}<=attraction_name_set)'
            ),
        ],
        "nature_language": f"我想到{city}看{name}，帮我安排一天。",
    }


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    fresh = "--fresh" in sys.argv
    db_path = ROOT / "data" / "sandbox_overlay.sqlite"
    if fresh and db_path.exists():
        db_path.unlink()
        print("cleared overlay (cold start)")
    env = get_env("zh")
    store = OverlayStore(db_path)
    pipeline = UpdatePipeline(env, store, use_llm=True)
    rehydrated = rehydrate(store, env)
    print(f"rehydrated {rehydrated} tool instances from overlay")
    planner = SkeletonPlanner(env)
    engine = RepairEngine(env, max_evaluations=10)

    cases = [
        ("广州", "南越王博物院"),
        ("上海", "上海博物馆东馆"),
        ("广州", "广东省博物馆"),
        ("广州", "ShortTrip 不存在的博物馆"),
    ]
    ANCHORS = {"广州": "广州南站", "上海": "上海虹桥站"}
    report = {"cases": []}
    for city, name in cases:
        entry = {"city": city, "name": name}
        entry["before"] = probe(env, city, name)

        query = build_query(city, name)
        built = planner.build(query)
        entry["plan_before"] = {
            "constructed": built.plan is not None,
            "all_ok": bool(built.report and built.report.all_ok),
            "hard_pass": built.report.hard_pass_count if built.report else None,
            "hard_total": len(built.report.hard_results) if built.report else None,
        }

        request = DataRequest(
            city=city,
            kind="attraction",
            name=name,
            fields=("name", "type", "lat", "lon", "opentime", "endtime", "price"),
            reason=f"query 要求必去 {name}，但沙箱 3 张表 + POI 表都没有该记录",
            source_query=query["uid"],
            required_by=[query["hard_logic_py"][-1]],
        )
        result = pipeline.run(request, anchor=ANCHORS.get(city))
        entry["update"] = result.to_dict()

        if result.accepted:
            record = result.candidate.plain()
            entry["after"] = probe(env, city, name, record)
            built2 = planner.build(query)
            repaired = engine.repair(query, built2.plan, built2.report) if built2.plan else None
            entry["plan_after"] = {
                "constructed": built2.plan is not None,
                "all_ok": bool(repaired.report.all_ok) if repaired else False,
                "hard_pass": repaired.report.hard_pass_count if repaired else None,
                "hard_total": len(repaired.report.hard_results) if repaired else None,
            }
        else:
            entry["after"] = probe(env, city, name)
            entry["plan_after"] = None
        report["cases"].append(entry)
        print(f"[{city}] {name}: decision={entry['update']['decision']} "
              f"version={entry['update']['version']} patched={entry['update']['patched_instances']}")

    report["store"] = store.summary()
    (RESULTS / "dynamic_update_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["store"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
