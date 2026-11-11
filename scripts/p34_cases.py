"""Collect concrete P34 cases (fixed / one-constraint failure / meal-time violation)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CT = ROOT / "ChinaTravel"


def load_rows(split: str) -> list[dict]:
    return json.loads((ROOT / f"results/p34_v2_planner/{split}_ShortTripV2_{split}.json")
                      .read_text(encoding="utf-8"))["rows"]


def query_row(split: str, uid: str) -> dict:
    return json.loads((CT / f"chinatravel/data/{split}/{uid}.json").read_text(encoding="utf-8"))


def plan_of(split: str, uid: str) -> dict | None:
    path = CT / f"results/ShortTripV2_{split}/{uid}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def csv_row(split: str, file: str, uid: str) -> dict | None:
    path = CT / f"eval_res/splits_{split}_p33/ShortTripV2_{split}/{file}.csv"
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    return next((r for r in rows if r["data_id"] == uid), None)


CASES = {
    "A_fixed": ("human", "h20241029143458760702"),
    "B_one_left": ("medium", "e20241028160851829629"),
    "C_meal": ("easy", "m20241028164657140437"),
}


def main() -> int:
    out = {}
    for name, (split, uid) in CASES.items():
        query = query_row(split, uid)
        plan = plan_of(split, uid)
        logical = csv_row(split, "logical_py", uid) or {}
        common = csv_row(split, "commonsense", uid) or {}
        failed_cols = [k for k, v in logical.items() if k != "data_id" and str(v) == "0"]
        violated = [k for k, v in common.items() if k != "data_id" and str(v) not in ("0", "0.0", "")]
        row = next(r for r in load_rows(split) if r["uid"] == uid)
        items = []
        if plan:
            for day_index, day in enumerate(plan["itinerary"]):
                for activity in day["activities"]:
                    items.append({
                        "day": day_index + 1,
                        "type": activity["type"],
                        "position": activity.get("position") or activity.get("start"),
                        "start": activity.get("start_time"),
                        "end": activity.get("end_time"),
                        "price": activity.get("price"),
                        "id": activity.get("TrainID") or activity.get("FlightID"),
                    })
        out[name] = {
            "split": split, "uid": uid,
            "natural_language": query["nature_language"],
            "days": query["days"], "people": query["people_number"],
            "from_city": query["start_city"], "to_city": query["target_city"],
            "constraints": query["hard_logic_py"],
            "failed_logic_cols": failed_cols,
            "commonsense_violations": violated,
            "plan_items": items,
            "metrics": {k: row.get(k) for k in ("built", "schema_ok", "commonsense_ok", "hard_pass",
                                               "hard_total", "hard_ok", "all_ok", "moves", "evaluations")},
        }
    path = ROOT / "results/p34_v2_planner/cases_detail.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, case in out.items():
        metrics = case["metrics"]
        print(f"{name}: {case['split']} {case['uid']} hard={metrics['hard_pass']}/{metrics['hard_total']} "
              f"all_ok={metrics['all_ok']} failed_cols={case['failed_logic_cols']} "
              f"cs={case['commonsense_violations']} moves={len(metrics['moves'] or [])} items={len(case['plan_items'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
