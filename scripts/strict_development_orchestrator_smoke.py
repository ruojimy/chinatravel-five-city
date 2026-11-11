"""Read-only v6 development smoke against the frozen local v4 catalog.

This script never builds or guesses a real itinerary. Missing planning context
is reported as a blocker, and field-evidence callbacks are deliberately absent.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shorttrip.strict_development_orchestrator import diagnose_development_plan
from shorttrip.strict_v4_reader import V4Reader


DEFAULT_COHORT = ROOT / "results/p43_timeonly_1030/cohort_v6_syntax_compiled.json"
DEFAULT_CATALOG = ROOT / "data/five_city_reference_v4_20261026/catalog.sqlite3"
DEFAULT_OUT = ROOT / "results/manual_20261031"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _task_expected_kind(task: dict, entity_id: str):
    selected = task.get("generation", {}).get("selected_entities_by_kind", {})
    matches = [kind for kind, item in selected.items()
               if isinstance(item, dict) and item.get("id") == entity_id]
    return matches[0] if len(matches) == 1 else None


def run(cohort_path: Path, catalog_path: Path) -> dict:
    cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
    tasks = cohort.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("cohort tasks must be a list")
    development = [task for task in tasks if isinstance(task, dict)
                   and task.get("split") == "development"
                   and task.get("purpose") == "development"]
    if not development:
        raise ValueError("no development tasks in cohort")

    reader = V4Reader(catalog_path)
    task_reports = []
    city_counts = collections.defaultdict(lambda: {"tasks": 0, "candidate_references": 0,
                                                    "id_kind_city_matches": 0,
                                                    "mapping_errors": 0})
    unique_ids = set()
    reference_count = loaded_count = matching_count = mapping_errors = 0
    try:
        for task in development:
            uid = task.get("uid", "unknown")
            city = task.get("target_city", "unknown")
            selection = task.get("candidate_selection")
            ids = selection.get("required_entity_ids") if isinstance(selection, dict) else None
            ids = ids if isinstance(ids, list) else []
            per_task = {"uid": uid, "city": city,
                        "candidate_reference_count": len(ids), "loaded_count": 0,
                        "id_kind_city_matches": 0, "mapping_errors": [],
                        "independent_identity_verified": False,
                        "plan_present": False,
                        "start_location_id_present": False,
                        "field_scope_bindings_present": False,
                        "field_evidence_verifier_configured": False,
                        "formal_or_feasibility_check_performed": False,
                        "blockers": ["plan_missing", "start_location_missing",
                                     "per_entity_field_scope_missing",
                                     "independent_identity_verifier_missing",
                                     "field_evidence_verifier_missing",
                                     "planner_not_integrated"]}
            city_counts[city]["tasks"] += 1
            city_counts[city]["candidate_references"] += len(ids)
            reference_count += len(ids)

            for entity_id in ids:
                if not isinstance(entity_id, str) or not entity_id:
                    per_task["mapping_errors"].append("candidate_id_malformed")
                    mapping_errors += 1
                    continue
                unique_ids.add(entity_id)
                expected_kind = _task_expected_kind(task, entity_id)
                if expected_kind is None:
                    per_task["mapping_errors"].append("candidate_kind_mapping_missing_or_ambiguous")
                    mapping_errors += 1
                    continue
                try:
                    record = reader.get(entity_id)
                except KeyError:
                    per_task["mapping_errors"].append("candidate_id_not_found")
                    mapping_errors += 1
                    continue
                except Exception as exc:
                    per_task["mapping_errors"].append("v4_reader_error:" + type(exc).__name__)
                    mapping_errors += 1
                    continue
                loaded_count += 1
                per_task["loaded_count"] += 1
                if (record.get("id") == entity_id and record.get("kind") == expected_kind
                        and record.get("city") == city):
                    matching_count += 1
                    per_task["id_kind_city_matches"] += 1
                    city_counts[city]["id_kind_city_matches"] += 1
                else:
                    details = {}
                    for key, wanted in (("id", entity_id), ("kind", expected_kind), ("city", city)):
                        if record.get(key) != wanted:
                            details[key] = {"expected": wanted, "actual": record.get(key)}
                    per_task["mapping_errors"].append({"reason": "record_mapping_mismatch",
                                                        "fields": details})
                    mapping_errors += 1
                # The record's name, claims, and tags are retained in memory only
                # for reader integrity. No name or evidence is trusted here.
            city_counts[city]["mapping_errors"] += len(per_task["mapping_errors"])

            # Exercise the current orchestrator's fail-closed missing-plan path.
            # Do not synthesize plan/context/bindings merely to force the bridge.
            blocked = diagnose_development_plan(
                task, None, plan_context=None, record_bindings=[],
                now="2026-10-31T00:00:00Z", registry={},
            )
            per_task["orchestrator_missing_plan_reason"] = (
                blocked.get("axes", {}).get("pipeline", [{}])[0].get("reason"))
            task_reports.append(per_task)
    finally:
        reader.close()

    city_summary = {city: values for city, values in sorted(city_counts.items())}
    return {
        "artifact": "strict-development-orchestrator-read-only-smoke-v1",
        "mode": "read_only_real_v4_candidate_catalog_no_plan_constructed",
        "cohort_path": str(cohort_path.resolve()),
        "cohort_sha256": sha256_file(cohort_path),
        "catalog_path": str(catalog_path.resolve()),
        "catalog_sha256": sha256_file(catalog_path),
        "development_task_count": len(development),
        "candidate_reference_count": reference_count,
        "unique_development_candidate_ids": len(unique_ids),
        "candidate_rows_loaded": loaded_count,
        "id_kind_city_matches": matching_count,
        "mapping_error_count": mapping_errors,
        "identity_verifier_configured": False,
        "field_evidence_verifier_configured": False,
        "formal_evaluation_performed": False,
        "freeze_approved": False,
        "real_itinerary_built": False,
        "synthetic_control_used": False,
        "city_summary": city_summary,
        "tasks": task_reports,
    }


def write_markdown(report: dict, target: Path) -> None:
    lines = [
        "# v6 development 编排只读工程冒烟（2026-10-31）", "",
        "## 范围", "",
        "只筛选 `split=development` 且 `purpose=development` 的 v6 任务，按候选 ID 只读加载本地 V4 记录，核对存储 ID/kind/city。没有读取留出任务逐题结果，没有联网或写入 catalog。没有构造真实或合成行程，也没有调用字段证据验证器。", "",
        "## 汇总", "",
        f"- 开发任务：{report['development_task_count']}；候选引用：{report['candidate_reference_count']}；唯一候选 ID：{report['unique_development_candidate_ids']}。",
        f"- V4 行读取：{report['candidate_rows_loaded']}；ID/kind/city 匹配：{report['id_kind_city_matches']}；映射错误：{report['mapping_error_count']}。",
        "- 独立身份验证器与字段证据验证器均未配置；因此目录映射不升级为实体身份或字段事实通过。",
        "- 未构造计划，未执行正式评估；`freeze_approved=false`。", "",
        "## 城市分布", "",
        "| 城市 | 开发任务 | 候选引用 | ID/kind/city 匹配 | 映射错误 |", "|---|---:|---:|---:|---:|",
    ]
    for city, values in report["city_summary"].items():
        lines.append(f"| {city} | {values['tasks']} | {values['candidate_references']} | {values['id_kind_city_matches']} | {values['mapping_errors']} |")
    lines += [
        "", "## 逐题阻塞状态", "",
        "每个开发任务都明确标记：计划缺失、起点位置 ID 缺失、候选到字段的逐日 scope 绑定缺失、独立身份验证器缺失、字段证据验证器缺失、planner 未集成。编排器对 `plan=None` 的直接调用返回缺计划 pipeline gap；本报告同时将规划输入的缺失解释为 context/adapter 阻塞，不据此推断任务不可行。", "",
        "## 可复现命令", "",
        "```powershell",
        "$env:PYTHONPATH='src'",
        "python scripts/strict_development_orchestrator_smoke.py --out-dir results/manual_20261031/smoke_run_YYYYMMDD_HHMMSS",
        "```", "",
        "默认读取 `results/p43_timeonly_1030/cohort_v6_syntax_compiled.json` 与 `data/five_city_reference_v4_20261026/catalog.sqlite3`。每次运行须选择一个新的、不含同名输出文件的 `--out-dir`；若目标 JSON 或 Markdown 已存在，脚本会拒绝运行，不覆盖旧工件。", "",
        "## 限制", "",
        "此冒烟只证明本地 catalog 的候选 ID/kind/city 映射可读；未独立核验真实实体身份。没有计划、起点、时间窗、房间配置、交通段、逐字段 scope 或证据验证器，所以没有调用 P31 计划评价去冒充完整行程检查。记录中的价格、开放时间、坐标、标签与名称都未作为已验证事实。",
    ]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    json_path = args.out_dir / "strict_development_orchestrator_smoke.json"
    markdown_path = args.out_dir / "strict_development_orchestrator_smoke.md"
    existing = [str(path) for path in (json_path, markdown_path) if path.exists()]
    if existing:
        parser.error("refusing to overwrite existing artifact(s): " + ", ".join(existing)
                     + "; choose a new --out-dir")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report = run(args.cohort, args.catalog)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    write_markdown(report, markdown_path)
    print(json.dumps({"json": str(json_path.resolve()), "markdown": str(markdown_path.resolve()),
                      "development_tasks": report["development_task_count"],
                      "candidate_rows_loaded": report["candidate_rows_loaded"],
                      "id_kind_city_matches": report["id_kind_city_matches"],
                      "mapping_errors": report["mapping_error_count"],
                      "freeze_approved": report["freeze_approved"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
