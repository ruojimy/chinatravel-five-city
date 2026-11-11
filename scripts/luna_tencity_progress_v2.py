"""Select submitted attempts before grading; report live coverage, never final early."""
from __future__ import annotations

import contextlib
import argparse
import datetime as dt
import hashlib
import io
import json
import subprocess
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_DIR = "results/luna_tencity_20261106"
OUT = ROOT / DEFAULT_RUN_DIR
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "ChinaTravel")]


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    from shorttrip.checker import check_plan
    from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py, _set_tool_lang

    parser = argparse.ArgumentParser()
    parser.add_argument("--include-pilots", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--run-dir", default=DEFAULT_RUN_DIR,
                        help="Experiment run directory relative to repo root; defaults to the historical Luna run")
    args = parser.parse_args()
    global OUT
    OUT = ROOT / args.run_dir
    grade_dir = OUT / ("adjudication" if args.include_pilots else "adjudication_formal")

    cohort = read(OUT / "protocol/manifest.json")["items"]
    known = {r["uid"]: r for r in cohort}
    selection_path = grade_dir / "selected_attempts.json"
    selected = read(selection_path) if selection_path.exists() else {"A": {}, "B": {}}
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    # New runs do not inherit the historical engineering exclusion. Every
    # exclusion must be declared here with a reason and evidence path.
    exclusion_file = grade_dir / "exclusions.json"
    excluded = read(exclusion_file) if exclusion_file.exists() else {}
    candidates = {"A": [], "B": []}
    for f in (OUT / "implementation_a/runtime").glob("**/results/LLMNeSy_luna-subagent/*.json"):
        if f.stem in known:
            candidates["A"].append((f.stem, f, None, "ok"))
    for receipt in (OUT / "implementation_b/evaluations").glob("*.json"):
        if receipt.name in excluded:
            continue
        meta = read(receipt)
        if not args.include_pilots and meta.get("request_protocol") != "luna-extended-b-native-v3":
            continue
        if meta.get("uid") not in known or not meta.get("raw_path"):
            continue
        raw = OUT / "implementation_b" / meta["raw_path"]
        if not meta.get("native_plan_path"):
            if raw.exists() and meta.get("status") in {"malformed", "blocked", "error", "timeout"}:
                candidates["B"].append((meta["uid"], raw, receipt, meta["status"]))
            continue
        plan = OUT / "implementation_b" / meta["native_plan_path"]
        if plan.exists() and raw.exists():
            candidates["B"].append((meta["uid"], plan, receipt, "ok"))
    for arm, rows in candidates.items():
        for uid, plan, receipt, status in sorted(rows, key=lambda row: row[1].stat().st_mtime_ns):
            if uid not in selected[arm]:
                selected[arm][uid] = {"path": plan.relative_to(ROOT).as_posix(),
                                      "sha256": digest(plan), "selected_at": now,
                                      "status": status,
                                      "receipt": receipt.relative_to(ROOT).as_posix() if receipt else None,
                                      "policy": "first submitted tool-valid attempt; chosen before independent score"}
    # Commit selection first. No choosing the highest score among versions.
    save(selection_path, selected)
    summary = {"updated_at": now, "state": "running", "expected_per_arm": len(cohort),
               "expected_total": 2 * len(cohort), "all_uid_terminal": False,
               "B_required_protocol": "pilot-inclusive" if args.include_pilots else "luna-extended-b-native-v3",
               "engineering_exclusions": excluded, "arms": {}}
    all_terminal = True
    for arm in ("A", "B"):
        rows = []
        counts = Counter()
        split_counts = Counter()
        cities = Counter()
        for uid, attempt in selected[arm].items():
            f = ROOT / attempt["path"]
            if digest(f) != attempt["sha256"]:
                raise RuntimeError(f"Selected raw plan changed: {arm}/{uid}")
            result_path = grade_dir / arm / f"{uid}.json"
            if not result_path.exists():
                source = ROOT / known[uid]["source"]
                if digest(source) != known[uid]["source_sha256"]:
                    raise RuntimeError(f"Frozen query changed: {uid}")
                query = read(source)
                plan = read(f) if attempt.get("status", "ok") == "ok" else {}
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    result = check_plan(query, plan).to_dict()
                    codes = query.get("hard_logic_py") or []
                    try:
                        _set_tool_lang("zh")
                        hard = [bool(v) for v in evaluate_constraints_py(codes, plan)] if plan else [False] * len(codes)
                    except Exception:
                        hard = [False] * len(codes)
                    result.update(hard_results=hard, hard_pass_count=sum(hard), hard_total=len(codes),
                                  hard_ok=bool(codes) and len(hard) == len(codes) and all(hard))
                    result["all_ok"] = result["schema_ok"] and result["commonsense_ok"] and result["hard_ok"]
                save(result_path, {"uid": uid, "arm": arm, "attempt": attempt,
                                   "evaluated_at": now, "official_check": result})
            result = read(result_path)["official_check"]
            for key in ("schema_ok", "commonsense_ok", "hard_ok", "all_ok"):
                counts[key] += bool(result[key])
            split_counts[known[uid]["split"]] += 1
            cities[known[uid]["target_city"]] += 1
            status = attempt.get("status", "ok")
            rows.append({"uid": uid, "arm": arm, "status": status,
                         "plan": read(f) if status == "ok" else None})
        response_path = grade_dir / f"{arm}_submitted.jsonl"
        response_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        n = len(rows)
        all_terminal &= n == len(cohort)
        summary["arms"][arm] = {"submitted": n, "pending": len(cohort) - n,
                                 "independently_scored": n, "passes_among_submitted": dict(counts),
                                 "submitted_by_split": dict(split_counts),
                                 "submitted_by_target_city": dict(cities),
                                 "final_604_scores_available": n == len(cohort)}
    summary["all_uid_terminal"] = all_terminal
    summary["state"] = "complete" if all_terminal else "running"
    queue = OUT / "implementation_a/queue"
    summary["A_internal_calls"] = {"requested": len(list((queue / "requests").glob("*.json"))),
                                   "responded": len(list((queue / "responses").glob("*.json")))}
    save(grade_dir / "progress.json", summary)
    experiment = read(OUT / "experiment.json") if (OUT / "experiment.json").exists() else {}
    model_name = (experiment.get("model") or {}).get("name", "unknown model")
    run_label = experiment.get("experiment", OUT.name)
    lines = [f"# Ten-city experiment {run_label}", "", f"State: {summary['state']}; updated {now}", "",
             "| Arm | Submitted / 604 | Schema pass | Commonsense pass | Hard pass | All three pass |", "|---|---:|---:|---:|---:|---:|"]
    for arm, row in summary["arms"].items():
        c = row["passes_among_submitted"]
        lines.append(f"| {arm} | {row['submitted']} / 604 | {c.get('schema_ok', 0)} | {c.get('commonsense_ok', 0)} | {c.get('hard_ok', 0)} | {c.get('all_ok', 0)} |")
    lines += ["", "Counts above describe submitted attempts only. Pending questions are not terminal failures, and this is not a full-cohort performance report.",
              "The submitted subsets can differ by UID and difficulty between arms. Do not rank architectures from these partial counts; the final paired denominator is 604 per arm.",
              "", f"A: original local LLMNeSy, with actual {model_name} internal LLM responses. B: actual {model_name} constructs complete native plans using expanded read-only retrieval. No historical plan reuse or score-driven repair.",
              "", "Frozen sandbox scores do not establish current real-world availability. Source time and live qualification are reported separately."]
    (grade_dir / "progress.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if all_terminal and not args.include_pilots:
        for arm in ("A", "B"):
            target = grade_dir / f"{arm}_final"
            if not target.with_suffix(".json").exists():
                with (grade_dir / f"{arm}_final_evaluator_log.txt").open("w", encoding="utf-8") as log:
                    subprocess.run([sys.executable, str(ROOT / "scripts/luna_tencity_evaluate.py"),
                                    "evaluate", "--responses", str(grade_dir / f"{arm}_submitted.jsonl"),
                                    "--out", str(target), "--arm", arm], cwd=ROOT,
                                   stdout=log, stderr=subprocess.STDOUT, check=True)
    if not args.quiet:
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
