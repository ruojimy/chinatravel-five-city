"""Build the ShortTrip dataset variants (V1 repair, V2 no-solution) and record metrics.

Run from `reproduction/ChinaTravel` with `PYTHONPATH=../src`:

    python ../scripts/build_shorttrip_datasets.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
LIMIT = 12

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.dataset import build_repair_cases
from shorttrip.env import get_env
from shorttrip.experiments import load_queries
from shorttrip.infeasibility import build_infeasible_cases
from shorttrip.planner import SkeletonPlanner


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    env = get_env("zh")
    planner = SkeletonPlanner(env)
    queries = (
        load_queries("human", LIMIT)
        + load_queries("medium", LIMIT)
        + load_queries("easy", LIMIT)
        + load_queries("preference_base50", LIMIT)
    )

    started = time.time()
    repair = build_repair_cases(
        env, planner, queries, max_cases=40, out_dir=ROOT / "datasets" / "shorttrip_repair"
    )
    repair["seconds"] = round(time.time() - started, 1)
    (RESULTS / "e3_repair.json").write_text(
        json.dumps(repair, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    started = time.time()
    infeasible = build_infeasible_cases(
        env, planner, queries, per_kind=6, out_dir=ROOT / "datasets" / "shorttrip_infeasible"
    )
    infeasible["seconds"] = round(time.time() - started, 1)
    (RESULTS / "e4_infeasible.json").write_text(
        json.dumps(infeasible, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(repair, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in infeasible.items() if k != "confusion"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
