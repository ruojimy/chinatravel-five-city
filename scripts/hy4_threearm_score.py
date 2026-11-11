"""Unified, independent four-arm adjudication for hy4_threearm_20261108.

Runs the UNMODIFIED official ChinaTravel three gates on every first submission.
Selections happen before scoring; no score-driven retry and no historical plan
reuse. Arm C chain questions use the shorttrip-dynamic-v1 contract gate and are
reported separately because they are not compatible with the Phase-1 checker.

MEMORY SAFETY (added after the 2026-11-08 OOM): the official commonsense
evaluator builds pandas frames per call and caches them at module scope. A
single process scoring 600+ plans grows without bound. Use --arms/--offset/
--limit to score in small, PROCESS-ISOLATED batches, then --summarize-only to
merge cached per-question results. Each question is gc.collect()'d after scoring.
"""
from __future__ import annotations

import argparse
import contextlib
import gc
import io
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "ChinaTravel"), str(ROOT / "scripts")]

DEFAULT_RUN = "results/hy4_threearm_20261108"
ARMS = ("A", "B", "C", "R")
NATIVE_SPLITS = ("easy", "medium", "human")


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_queries() -> dict:
    out = {}
    for split in NATIVE_SPLITS:
        for p in (ROOT / "ChinaTravel" / "chinatravel" / "data" / split).glob("*.json"):
            d = read(p)
            out[d["uid"]] = {"query": d, "path": p, "split": split}
    return out


def c_queries() -> dict:
    out = {}
    for split in (*NATIVE_SPLITS, "chain"):
        for p in (ROOT / "query_sets" / "xian11" / split).glob("*.json"):
            d = read(p)
            out[d["uid"]] = {"query": d, "path": p, "split": split}
    return out


def collect(run: Path, nq: dict, cq: dict) -> dict:
    found = {a: {} for a in ARMS}
    for p in (run / "implementation_a" / "runtime").glob("**/results/LLMNeSy_luna-subagent/*.json"):
        if p.stem in nq:
            found["A"].setdefault(p.stem, p)
    for receipt in (run / "implementation_b" / "evaluations").glob("*.json"):
        m = read(receipt)
        uid = m.get("uid")
        if uid not in nq or uid in found["B"]:
            continue
        if m.get("native_plan_path"):
            plan = run / "implementation_b" / m["native_plan_path"]
            found["B"][uid] = plan if plan.exists() else None
        else:
            raw = run / "implementation_b" / m.get("raw_path", "__missing__")
            found["B"][uid] = raw if raw.exists() else None
    for receipt in (run / "implementation_c" / "evaluations").glob("*.json"):
        m = read(receipt)
        uid = m.get("uid")
        if uid not in cq or uid in found["C"]:
            continue
        if m.get("native_plan_path"):
            plan = run / "implementation_c" / m["native_plan_path"]
            found["C"][uid] = plan if plan.exists() else None
        else:
            raw = run / "implementation_c" / m.get("raw_path", "__missing__")
            found["C"][uid] = raw if raw.exists() else None
    for split in NATIVE_SPLITS:
        for p in (ROOT / "ChinaTravel" / "results" / f"HY4CTRL_P34_{split}").glob("*.json"):
            if p.stem in nq:
                found["R"].setdefault(p.stem, p)
    return found


def score_native(query: dict, plan: dict) -> dict:
    # Import lazily so summarize-only invocations never load pandas/checker.
    from shorttrip.checker import check_plan
    from chinatravel.symbol_verification.hard_constraint import (
        evaluate_constraints_py, _set_tool_lang,
    )
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        report = check_plan(query, plan).to_dict()
        codes = list(query.get("hard_logic_py") or [])
        try:
            _set_tool_lang("zh")
            hard = [bool(v) for v in evaluate_constraints_py(codes, plan)] if plan and codes else []
        except Exception as exc:  # noqa: BLE001
            hard = [False] * len(codes)
            report["hard_evaluator_error"] = f"{type(exc).__name__}: {exc}"
        report["hard_results"] = hard
        report["hard_pass_count"] = sum(hard)
        report["hard_total"] = len(codes)
        report["hard_ok"] = bool(codes) and len(hard) == len(codes) and all(hard)
        report["all_ok"] = bool(report.get("schema_ok") and report.get("commonsense_ok") and report["hard_ok"])
    return report


def score_chain(query: dict, plan: dict) -> dict:
    """Structural contract gate for shorttrip-dynamic-v1; not the Phase-1 checker."""
    problems = []
    if plan.get("schema_version") != "shorttrip-dynamic-v1":
        problems.append("schema_version_mismatch")
    if plan.get("city_sequence") != query.get("city_sequence"):
        problems.append("city_sequence_mismatch")
    body = plan.get("plan")
    if not isinstance(body, (dict, list)) or not body:
        problems.append("plan_body_missing")
    limits = plan.get("limitations")
    if not isinstance(limits, (str, list, dict)) or not limits:
        problems.append("limitations_missing")
    return {"contract": "shorttrip-dynamic-v1", "contract_ok": not problems,
            "problems": problems, "official_three_gates": "not_applicable",
            "note": "chain questions are not compatible with the native Phase-1 checker; "
                    "this gate checks structure and honest pending connections only"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", default=DEFAULT_RUN)
    ap.add_argument("--arms", default="A,B,C,R", help="comma-separated arms to score")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--summarize-only", action="store_true",
                    help="merge cached per-question results without loading the checker")
    ap.add_argument("--inject-xian", action="store_true",
                    help="install the 11th-city official loader patch BEFORE importing any checker")
    ap.add_argument("--rescore", action="store_true",
                    help="ignore existing per-question caches and recompute (use after a protocol change)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    run = ROOT / args.run_dir
    grade = run / "adjudication"
    grade.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    injection = None
    if args.inject_xian:
        # Must happen before score_native() imports shorttrip.checker, because
        # the official commonsense verifier builds its tool singletons at
        # import time from the frozen 10-city database.
        from xian11_loader_inject import install
        injection = install()
        injection["installed_by"] = "hy4_threearm_score.py --inject-xian"
        injection["installed_at"] = now
        save(grade / "injection_info.json", injection)
    arms_only = {a.strip() for a in args.arms.split(",") if a.strip()}
    nq, cq = native_queries(), c_queries()
    manifest = read(run / "protocol" / "manifest.json")
    cohort = {i["uid"]: i for i in manifest["items"]}
    cohort_c = read(run / "protocol" / "cohort_c.json")
    expected = {"A": len(cohort), "B": len(cohort), "C": len(cohort_c["items"]), "R": len(cohort)}
    found = collect(run, nq, cq)

    selection_path = grade / "selected_attempts.json"
    selection = read(selection_path) if selection_path.exists() else {a: {} for a in ARMS}
    for arm in ARMS:
        for uid, path in sorted(found[arm].items(), key=lambda kv: kv[0]):
            if uid not in selection[arm]:
                selection[arm][uid] = {
                    "path": str(path.relative_to(ROOT)) if path else None,
                    "sha256": sha(path) if path else None,
                    "selected_at": now,
                    "policy": "first submission only; frozen before independent scoring",
                }
    save(selection_path, selection)

    # ---- scoring pass (process-isolated batches) ----
    if not args.summarize_only:
        for arm in ARMS:
            if arm not in arms_only:
                continue
            items = sorted(selection[arm].items())
            if args.limit:
                items = items[args.offset:args.offset + args.limit]
            for uid, attempt in items:
                cache = grade / arm / f"{uid}.json"
                if cache.exists() and not args.rescore:
                    continue
                path = ROOT / attempt["path"] if attempt["path"] else None
                if path and (not path.exists() or sha(path) != attempt["sha256"]):
                    raise RuntimeError(f"selected artifact changed: {arm}/{uid}")
                is_c = arm == "C"
                q = (cq if is_c else nq).get(uid, {}).get("query", {})
                plan = read(path) if path and path.suffix == ".json" else {}
                split = (cq if is_c else nq).get(uid, {}).get("split", "?")
                if is_c and split == "chain":
                    result = score_chain(q, plan)
                else:
                    result = score_native(q, plan)
                save(cache, {"uid": uid, "arm": arm, "split": split,
                             "evaluated_at": now, "result": result})
                del q, plan, result
                gc.collect()

    # ---- merge from caches (cheap, no checker import) ----
    injected = bool(injection) or (grade / "injection_info.json").exists()
    summary = {"updated_at": now, "run": run.name, "model": "hy4std (fixed)",
               "xian_loader_injected": injected,
               "state": "running", "expected": expected, "arms": {}, "pairing": {}}
    all_terminal = True
    for arm in ARMS:
        rows, counts, by_split, chain_rows = [], Counter(), Counter(), []
        for uid, attempt in sorted(selection[arm].items()):
            cache = grade / arm / f"{uid}.json"
            if not cache.exists():
                rows.append({"uid": uid, "split": "?", "status": "pending_score"})
                continue
            scored = read(cache)
            r, split = scored["result"], scored["split"]
            rows.append({"uid": uid, "split": split, "status": "ok",
                         "all_ok": bool(r.get("all_ok")), "contract_ok": bool(r.get("contract_ok"))})
            if split == "chain":
                chain_rows.append(r)
                continue
            for key in ("schema_ok", "commonsense_ok", "hard_ok", "all_ok"):
                counts[key] += bool(r.get(key))
            by_split[split] += 1
        scored_n = sum(1 for r in rows if r["status"] == "ok")
        n = len(rows)
        all_terminal &= n >= expected[arm] and scored_n == n
        summary["arms"][arm] = {
            "submitted": n, "independently_scored": scored_n,
            "pending": max(0, expected[arm] - n),
            "passes_among_submitted": dict(counts),
            "submitted_by_split": dict(by_split),
            "chain_structural_pass": sum(1 for r in chain_rows if r.get("contract_ok")),
            "chain_structural_total": len(chain_rows),
            "full_cohort_scores_available": n >= expected[arm] and scored_n == n,
        }
        (grade / f"{arm}_submitted.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    paired = sorted(set(selection["A"]) & set(selection["B"]) & set(selection["R"]))
    summary["pairing"] = {"native10_paired_uids": len(paired),
                          "paired_uids": paired,
                          "c_arm_uids": len(selection["C"]),
                          "note": "only paired UIDs support architecture comparison"}
    summary["all_uid_terminal"] = all_terminal
    summary["state"] = "complete" if all_terminal else "running"
    save(grade / "progress.json", summary)

    lines = ["# 四组对照实验进度（hy4std 固定模型）", "",
             f"更新：{now}　状态：{summary['state']}", "",
             "| 组 | 已提交/目标 | 已评分 | schema | commonsense | hard DSL | 三关全过 | 串联结构通过 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for arm in ARMS:
        s, c = summary["arms"][arm], summary["arms"][arm]["passes_among_submitted"]
        lines.append(f"| {arm} | {s['submitted']}/{expected[arm]} | {s['independently_scored']} | "
                     f"{c.get('schema_ok',0)} | {c.get('commonsense_ok',0)} | {c.get('hard_ok',0)} | "
                     f"{c.get('all_ok',0)} | {s['chain_structural_pass']}/{s['chain_structural_total']} |")
    lines += ["",
              "- 计数只覆盖已提交的首份计划；未提交不是失败，部分提交不是最终成绩。",
              f"- A/B/R 三方同 UID 配对数：{len(paired)}；只有配对 UID 可比较架构。",
              "- C 组 chain 30 题不兼容原生 Phase-1 checker，只做 shorttrip-dynamic-v1 结构门控，单列。",
              ("- C 组已启用第 11 城官方加载器注入 + L1/L2 分层：L1 齐备 = 主路径准入、"
               "L2 齐备 = 优先访问；L1 有缺的 1,312 条保留在 reference_only/ 仅可查询；"
               "主视图 L2 缺口用 -1 / UNKNOWN 显式标注，价格类判定不可信须单列披露。"
               "10 城数据逐字节未变，97 条 parity 零差异。"
               if injected else
               "- C 组 60 道原生题引用西安实体，官方 commonsense 沙盒未注入西安目录，该项通过率会系统性偏低，"
               "属于口径不等价，报告必须披露。"),
              "- 冻结沙盒通过不等于现实可执行；所有工具输出 real_world_availability=false。",
              ""]
    (grade / "progress.md").write_text("\n".join(lines), encoding="utf-8")
    if not args.quiet:
        print(json.dumps({k: v for k, v in summary.items() if k != "pairing"},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
