"""P33: run the deterministic ShortTrip planner on the original ChinaTravel splits.

The planner is LLM-free: SkeletonPlanner builds a sandbox-grounded itinerary and
RepairEngine fixes it against the official DSL.  Plans are written to
`ChinaTravel/results/<method>/<uid>.json` so the unmodified `eval_exp.py` can score them.

Usage (from anywhere):
  python scripts/p33_run_native_planner.py --split easy --method ShortTrip_easy
  python scripts/p33_run_native_planner.py --split medium --method ShortTrip_medium
  python scripts/p33_run_native_planner.py --split human --method ShortTrip_human
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.env import get_env  # noqa: E402
from shorttrip.planner import SkeletonPlanner  # noqa: E402
from shorttrip.repair import RepairEngine  # noqa: E402

OUT = ROOT / "results/p33_native_planner"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", required=True)
    ap.add_argument("--method", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--max-evaluations", type=int, default=25)
    ap.add_argument("--room-type-fix", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--lang", default="zh")
    a = ap.parse_args()

    data_dir = ROOT / "ChinaTravel" / "chinatravel" / "data" / a.split
    paths = sorted(data_dir.glob("*.json"))
    if a.offset:
        paths = paths[a.offset:]
    if a.limit:
        paths = paths[: a.limit]
    out_dir = ROOT / "ChinaTravel" / "results" / a.method
    if not a.no_write:
        out_dir.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    env = get_env(a.lang)
    planner = SkeletonPlanner(env)
    engine = RepairEngine(env, max_evaluations=a.max_evaluations,
                          room_type_fix=a.room_type_fix)

    rows = []
    started = time.time()
    for i, p in enumerate(paths, 1):
        query = json.loads(p.read_text(encoding="utf-8"))
        uid = query["uid"]
        t0 = time.time()
        row = {"uid": uid, "tag": query.get("tag"), "days": query.get("days"),
               "start_city": query.get("start_city"), "target_city": query.get("target_city"),
               "built": False, "written": False, "error": None}
        plan = None
        try:
            build = planner.build(query)
            row["built"] = build.plan is not None
            row["combos_tried"] = build.combos_tried
            if build.plan is not None:
                repaired = engine.repair(query, build.plan, build.report)
                plan = repaired.plan
                rep = repaired.report
                row.update({
                    "schema_ok": bool(rep.schema_ok),
                    "commonsense_ok": bool(rep.commonsense_ok),
                    "commonsense_violations": rep.commonsense_violations,
                    "hard_pass": rep.hard_pass_count,
                    "hard_total": len(rep.hard_results),
                    "hard_ok": bool(rep.hard_ok),
                    "all_ok": bool(rep.all_ok),
                    "edits": repaired.edits,
                })
                if plan is not None and not a.no_write:
                    slim = {k: v for k, v in plan.items()
                            if k in ("people_number", "start_city", "target_city", "itinerary")}
                    (out_dir / f"{uid}.json").write_text(
                        json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
                    row["written"] = True
            else:
                row["reason"] = planner.last_reason
        except Exception as exc:  # noqa: BLE001
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["trace"] = traceback.format_exc()[-800:]
        row["seconds"] = round(time.time() - t0, 3)
        rows.append(row)
        if i % 20 == 0 or i == len(paths):
            print(json.dumps({"done": i, "total": len(paths),
                              "elapsed_s": round(time.time() - started, 1),
                              "all_ok": sum(1 for x in rows if x.get("all_ok"))},
                             ensure_ascii=False), flush=True)

    summary = {
        "split": a.split, "method": a.method, "queries": len(rows),
        "written": sum(1 for r in rows if r["written"]),
        "built": sum(1 for r in rows if r["built"]),
        "errors": sum(1 for r in rows if r["error"]),
        "all_ok": sum(1 for r in rows if r.get("all_ok")),
        "schema_ok": sum(1 for r in rows if r.get("schema_ok")),
        "commonsense_ok": sum(1 for r in rows if r.get("commonsense_ok")),
        "hard_ok": sum(1 for r in rows if r.get("hard_ok")),
        "by_tag": dict(Counter(r.get("tag") for r in rows)),
        "by_days": dict(Counter(r.get("days") for r in rows)),
        "by_target_city": dict(Counter(r.get("target_city") for r in rows)),
        "elapsed_s": round(time.time() - started, 1),
        "rows": rows,
    }
    (OUT / f"{a.split}_{a.method}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
