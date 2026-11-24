"""Run the fixed 36-case cohort through the installed ShortTrip rule-only planner."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import json
import os
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "results/v19-20261118/luna_v19_standard_36"
SNAPSHOT = "trial-5e2d7c000735607f6ada8c42"


def read(path):
    return json.loads(path.read_bytes())


def init(release, out):
    global env, facts, destination
    destination = out
    sys.path.insert(0, str(release / "combined version_personalized"))
    data = release / "ShortTrip/artifacts/data"
    os.environ["SHORTTRIP_REFERENCE_PREVIEW"] = str(data / SNAPSHOT / "reference-preview.json")
    os.environ["SHORTTRIP_REFERENCE_ENGINE"] = str(release / "ShortTrip/artifacts/trial-engine")
    os.environ["CT_XIAMEN_HISTORICAL_FARES"] = "1"
    from chinatravel.environment.sandbox.__main__ import configuration
    os.environ.update(configuration(data / "6de12f4"))
    from chinatravel.environment.world_env import WorldEnv
    from chinatravel.personalization import cli
    from chinatravel.personalization.world_facts import WorldFacts
    cli.ROOT = out
    env = WorldEnv(lang="zh")
    facts = WorldFacts.configured(data / "6de12f4")
    if facts.version["reference_preview"] != SNAPSHOT:
        raise RuntimeError("Wrong planning snapshot")


def case_form(case, query):
    form = {k: query[k] for k in ("start_city", "target_city", "days", "people_number")}
    form["start_date"] = "2026-11-20"
    if case["budget"] is not None:
        form["budget"] = case["budget"]
    if len(case["allowed_modes"]) == 1:
        mode_labels = {"airplane": "飞机", "train": "火车"}
        form["intercity_modes"] = [mode_labels[mode] for mode in case["allowed_modes"]]
    if query.get("limit_rooms"):
        clauses = "\n".join(query["hard_logic_py"])
        counts = set(re.findall(r"room_count\(activity\)\s*!=\s*(\d+)", clauses))
        if len(counts) != 1:
            raise ValueError("The frozen room count must have a unique literal")
        form["rooms"] = int(counts.pop())
    return form


def plan_case(case):
    from chinatravel.personalization.integrated_planning import run_trip_plan
    from chinatravel.personalization.tripspec import evaluate_draft, ModelReply

    uid = case["id"]
    query = read(CORPUS / "private" / f"{uid}.json")
    form = case_form(case, query)
    spec = evaluate_draft(query["nature_language"], form, facts.sandbox.cities,
                          ModelReply(draft={"items": [], "questions": []}))
    row = {"id": uid, "destination": query["target_city"], "difficulty": uid.split("-")[-1][0]}
    try:
        status = run_trip_plan(spec, destination / uid, env, facts, model=False, seconds=12,
                               candidates=2, improve_meals=False)
    except Exception as error:
        return {**row, "state": "execution_error", "error": type(error).__name__}
    return {**row, "state": status["state"], "stage": status["stage"],
            "reason_code": status.get("reason_code"), "message": status.get("message"),
            "candidate_count": status.get("candidate_count", 0),
            "issue_fields": [issue.get("field") for issue in status.get("issues", [])],
            "seconds": round(status.get("elapsed_seconds", 0), 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--prior", type=Path, help="Reuse cases whose frozen request forms are identical.")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cases = read(ROOT / "results/v20-20261119/transport_preflight_v19_v20.json")["cases"]
    assert set(cases) == set(read(CORPUS / "public/manifest.json")["cases"]) and len(cases) == 36
    reused = {}
    if args.prior:
        prior = read(args.prior / "run.json")
        assert prior["snapshot"] == SNAPSHOT
        for row in prior["cases"]:
            uid = row["id"]
            request = args.prior / uid / "request.json"
            if not request.exists() or row["state"] == "execution_error":
                continue
            query = read(CORPUS / "private" / f"{uid}.json")
            saved = read(request)
            if (saved["raw_text"] == query["nature_language"]
                    and json.dumps(saved["form"], sort_keys=True) == json.dumps(case_form(cases[uid], query), sort_keys=True)):
                reused[uid] = row
    with ProcessPoolExecutor(args.workers, initializer=init, initargs=(args.release.resolve(), output),
                             max_tasks_per_child=1) as pool:
        pending = {uid: pool.submit(plan_case, case) for uid, case in cases.items() if uid not in reused}
        rows = []
        for uid in cases:
            if uid in reused:
                row = reused[uid]
                case_dir = args.prior / uid
            else:
                try:
                    row = pending[uid].result()
                except Exception as error:
                    row = {"id": uid, "destination": cases[uid]["destination"], "state": "execution_error",
                           "error": type(error).__name__, "missing_module": getattr(error, "name", None)}
                case_dir = output / uid
            if row["state"] == "complete":
                selected = read(case_dir / "PLAN_VIEW.json")["recommended_id"]
                choices = read(case_dir / "CANDIDATE_ARCHIVE.json")["archive"]
                row["recommended_itinerary"] = next(x["itinerary"] for x in choices if x["id"] == selected)
            row["reused_unchanged_run"] = uid in reused
            rows.append(row)
            print(uid, row["state"], "reused" if uid in reused else "run", flush=True)
    (output / "run.json").write_text(json.dumps({"snapshot": SNAPSHOT, "cases": rows}, ensure_ascii=False, indent=2)
                                      + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
