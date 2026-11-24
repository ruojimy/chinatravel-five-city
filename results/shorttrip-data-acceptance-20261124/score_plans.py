"""Score the recommended rule-only itineraries against the original frozen benchmark requirements."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from run_rule_planning import CORPUS, SNAPSHOT, read


def scorer_configuration(release):
    planner = release / "combined version_personalized"
    engine = release / "ShortTrip/artifacts/trial-engine"
    data = release / "ShortTrip/artifacts/data"
    sys.path.insert(0, str(planner))
    from chinatravel.environment.sandbox.__main__ import configuration
    lookup = {**os.environ, **configuration(data / "6de12f4"),
              "CT_XIAMEN_HISTORICAL_FARES": "1", "CT_SANDBOX_ENGINE_ROOT": str(engine),
              "SHORTTRIP_REFERENCE_PREVIEW": str(data / SNAPSHOT / "reference-preview.json"),
              "PYTHONPATH": os.pathsep.join((str(engine), str(planner)))}
    return engine, lookup, Path(lookup["CT_SANDBOX_RUNTIME_DIR"]) / "evaluator/score_tristate.py"


def score(row, engine, env, scorer, directory):
    uid = row["id"]
    if "recommended_itinerary" not in row:
        return {"id": uid, "overall": "no_plan"}
    query = CORPUS / "private" / f"{uid}.json"
    audit_file = query.with_suffix(".audit.json")
    plan, outcome = directory / f"{uid}.plan.json", directory / f"{uid}.score.json"
    plan.write_text(json.dumps(row["recommended_itinerary"], ensure_ascii=False) + "\n", encoding="utf-8")
    command = [sys.executable, "-B", "-X", "utf8", str(scorer), "--target-root", str(engine),
               "--query", str(query), "--audit", str(audit_file), "--plan", str(plan), "--output", str(outcome)]
    try:
        proc = subprocess.run(command, cwd=engine, env=env, capture_output=True, timeout=75)
    except subprocess.TimeoutExpired:
        return {"id": uid, "overall": "scoring_timeout"}
    if proc.returncode:
        return {"id": uid, "overall": "scoring_error", "exit_code": proc.returncode}
    result = read(outcome)
    audit = read(audit_file)
    names = {x["repaired_index"]: x["key"] for x in audit["clauses"] if x.get("repaired_index") is not None}
    return {"id": uid, "overall": result["overall"], "plan_sha256": result["plan_sha256"],
            "query_sha256": result["query_sha256"], "schema": result["schema"]["state"],
            "commonsense": result["commonsense"]["state"], "hard": result["hard"]["state"],
            "requested_places": result["requested_places"]["state"],
            "commonsense_checks": {row["name"]: row["state"] for row in result["groups"]},
            "hard_checks": [{"key": names[clause["index"]], "state": clause["state"],
                             **({"reason": clause["reason"]} if "reason" in clause else {})}
                            for clause in result["hard"]["clauses"]],
            "unresolved_original_requirements": audit.get("unresolved_requirements", []),
            "evaluator_hashes": result["evaluator_hashes"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = read(args.plans)
    assert report["snapshot"] == SNAPSHOT and len(report["cases"]) == 36
    engine, env, scorer = scorer_configuration(args.release.resolve())
    with TemporaryDirectory(prefix="shorttrip-scores-") as tmp, ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(score, row, engine, env, scorer, Path(tmp)) for row in report["cases"]]
        results = [job.result() for job in jobs]
    with args.output.open("x", encoding="utf-8", newline="\n") as target:
        json.dump({"snapshot": SNAPSHOT, "scorer_sha256": hashlib.sha256(scorer.read_bytes()).hexdigest(),
                   "cases": results}, target, ensure_ascii=False, indent=2, allow_nan=False)
        target.write("\n")


if __name__ == "__main__":
    main()
