"""P34: run the V2 rule planner (constraint-directed) on the original Chinatravel splits.

Same plumbing as p33_run_native_planner.py, but the planner is
`shorttrip.planner_v2.ConstraintPlannerV2`: it seeds with SkeletonPlanner and then
proposes constraint-directed content edits, keeping only the ones the official
checker scores as an improvement.

Usage (from anywhere):
  python scripts/p34_run_v2.py --split easy --method ShortTripV2_easy
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
from shorttrip.planner_v2 import ConstraintPlannerV2  # noqa: E402

OUT = ROOT / "results/p34_v2_planner"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", required=True)
    ap.add_argument("--method", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--max-evaluations", type=int, default=60)
    ap.add_argument("--room-type-fix", action="store_true", help="ignored; kept for parity")
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
    planner = ConstraintPlannerV2(env, max_evaluations=a.max_evaluations)

    rows = []
    started = time.time()
    for index, path in enumerate(paths, 1):
        query = json.loads(path.read_text(encoding="utf-8"))
        uid = query["uid"]
        t0 = time.time()
        row = {"uid": uid, "tag": query.get("tag"), "days": query.get("days"),
               "start_city": query.get("start_city"), "target_city": query.get("target_city"),
               "built": False, "written": False, "error": None}
        try:
            result = planner.plan(query)
            row["built"] = result.plan is not None
            row["evaluations"] = result.evaluations
            row["moves"] = result.moves
            report = result.report
            if result.plan is not None and report is not None:
                row.update({
                    "schema_ok": bool(report.schema_ok),
                    "commonsense_ok": bool(report.commonsense_ok),
                    "commonsense_violations": report.commonsense_violations,
                    "hard_pass": report.hard_pass_count,
                    "hard_total": len(report.hard_results),
                    "hard_ok": bool(report.hard_ok),
                    "all_ok": bool(report.all_ok),
                })
                if not a.no_write:
                    slim = {k: v for k, v in result.plan.items()
                            if k in ("people_number", "start_city", "target_city", "itinerary")}
                    (out_dir / f"{uid}.json").write_text(
                        json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
                    row["written"] = True
            else:
                row["reason"] = result.reason
        except Exception as exc:  # noqa: BLE001
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["trace"] = traceback.format_exc()[-800:]
        row["seconds"] = round(time.time() - t0, 3)
        rows.append(row)
        if index % 20 == 0 or index == len(paths):
            print(json.dumps({"done": index, "total": len(paths),
                              "elapsed_s": round(time.time() - started, 1),
                              "all_ok": sum(1 for r in rows if r.get("all_ok")),
                              "hard_ok": sum(1 for r in rows if r.get("hard_ok"))},
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
        "mean_evaluations": round(sum(r.get("evaluations", 0) for r in rows) / max(1, len(rows)), 2),
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
