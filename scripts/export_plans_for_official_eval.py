"""Export ShortTrip planner outputs into the official `results/<method>/` layout
so that the unmodified `eval_exp.py` can score them.

Run from `reproduction/ChinaTravel`:

    python ../scripts/export_plans_for_official_eval.py easy_short ShortTrip
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.checker import check_plan  # noqa: E402
from shorttrip.env import get_env  # noqa: E402
from shorttrip.planner import SkeletonPlanner  # noqa: E402
from shorttrip.repair import RepairEngine  # noqa: E402


def main() -> int:
    split = sys.argv[1] if len(sys.argv) > 1 else "easy_short"
    method = sys.argv[2] if len(sys.argv) > 2 else "ShortTrip"
    data_dir = ROOT / "ChinaTravel" / "chinatravel" / "data" / split
    out_dir = ROOT / "ChinaTravel" / "results" / method
    out_dir.mkdir(parents=True, exist_ok=True)

    env = get_env("zh")
    planner = SkeletonPlanner(env)
    engine = RepairEngine(env, max_evaluations=25)
    summary = []
    for path in sorted(data_dir.glob("*.json")):
        query = json.loads(path.read_text(encoding="utf-8"))
        build = planner.build(query)
        if build.plan is None:
            continue
        repaired = engine.repair(query, build.plan, build.report)
        plan = repaired.plan
        # strip helper keys the official evaluator does not expect
        plan = {k: v for k, v in plan.items() if k in ("people_number", "start_city", "target_city", "itinerary")}
        (out_dir / f"{query['uid']}.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        summary.append(
            {
                "uid": query["uid"],
                "written": True,
                "all_ok": repaired.report.all_ok,
                "hard_pass": repaired.report.hard_pass_count,
                "hard_total": len(repaired.report.hard_results),
            }
        )
    print(json.dumps({"split": split, "method": method, "plans": len(summary)}, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
