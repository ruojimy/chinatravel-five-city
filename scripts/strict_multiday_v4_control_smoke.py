"""Five-city, read-only reconstructed control through candidate/search/diagnostic.

The itinerary-shaped inputs are synthetic controls for interface exercise only.
They are not user intent, travel facts, route claims, or feasibility results.
No identity, evidence, schedule, route, cost, or other fact verifier is enabled.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import types
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shorttrip.strict_multiday_candidates import generate_multiday_candidate_proposals
from shorttrip.strict_search_orchestrator import search_development_assignments
from shorttrip.strict_v4_reader import V4Reader


DEFAULT_COHORT = ROOT / "results/p43_timeonly_1030/cohort_v6_syntax_compiled.json"
DEFAULT_CATALOG = ROOT / "data/five_city_reference_v4_20261026/catalog.sqlite3"
DEFAULT_OUT = ROOT / "results/manual_20261031"
EXPECTED_CITIES = {"西安", "厦门", "宁波", "长沙", "青岛"}
SYNTHETIC_TIMEZONE = "+08:00"
SYNTHETIC_NOW = "2026-10-31T00:00:00Z"
START_KIND_ORDER = ("poi", "metro_station", "train", "flight")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_code_manifest() -> dict[str, Any]:
    """Hash this script and loaded project-local shorttrip Python sources.

    This records an engineering run snapshot, not a formal frozen build.
    Modules are discovered from the live import table after the smoke ran, so
    lazily imported local shorttrip dependencies are included as well.
    """
    entries = [{"module": "__main__", "path": "scripts/strict_multiday_v4_control_smoke.py",
                "sha256": sha256_file(Path(__file__).resolve())}]
    source_root = (ROOT / "src/shorttrip").resolve()
    for module_name, module in sorted(sys.modules.items()):
        if not module_name.startswith("shorttrip") or not isinstance(module, types.ModuleType):
            continue
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        path = Path(module_file).resolve()
        if path.suffix != ".py" or not path.is_relative_to(source_root):
            continue
        entries.append({"module": module_name,
                        "path": path.relative_to(ROOT).as_posix(),
                        "sha256": sha256_file(path)})
    # Keep the imported manifest deterministic, including modules which alias
    # one source file under only one import name.
    entries = sorted(entries, key=lambda item: (item["module"], item["path"]))
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False)
    return {"classification": "engineering_code_snapshot_not_formal_freeze",
            "capture_method": "loaded_shorttrip_modules_from_sys_modules_after_run",
            "module_count_including_script": len(entries),
            "manifest_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "modules": entries}


def _selected_by_id(task: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    selected = task.get("generation", {}).get("selected_entities_by_kind", {})
    result: dict[str, tuple[str, dict[str, Any]]] = {}
    if not isinstance(selected, dict):
        return result
    for kind, entity in selected.items():
        if isinstance(kind, str) and isinstance(entity, dict) and isinstance(entity.get("id"), str):
            entity_id = entity["id"]
            if entity_id not in result:
                result[entity_id] = (kind, entity)
            else:
                result.pop(entity_id, None)  # Ambiguous ID-kind mapping remains unusable.
    return result


def _choose_task_by_city(cohort: dict[str, Any]) -> tuple[dict[str, dict], list[dict]]:
    tasks = cohort.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("cohort tasks must be a list")
    # Only development task fields are used below. Holdout rows are not emitted,
    # summarized, or passed to any adapter.
    selected: dict[str, dict] = {}
    development_count = 0
    for task in tasks:
        if (not isinstance(task, dict) or task.get("split") != "development" or
                task.get("purpose") != "development"):
            continue
        development_count += 1
        city = task.get("target_city")
        if isinstance(city, str) and city in EXPECTED_CITIES and city not in selected:
            selected[city] = task
    missing = EXPECTED_CITIES - set(selected)
    if missing:
        raise ValueError("development tasks missing expected cities: " + ", ".join(sorted(missing)))
    return selected, [{"development_task_count": development_count}]


def _dates_for(task: dict[str, Any]) -> list[str] | None:
    if task.get("days") != 3 or not isinstance(task.get("start_date"), str):
        return None
    try:
        start = date.fromisoformat(task["start_date"])
    except ValueError:
        return None
    return [(start + timedelta(days=index)).isoformat() for index in range(3)]


def _synthetic_slots(attraction_id: str, dates: list[str]) -> list[dict]:
    # Artificial 10:00-11:00 intervals solely to exercise the generator.
    return [{"date": day, "slots": [{
        "slot_id": f"reconstructed-control-visit-day-{index + 1}",
        "candidates": [{"entity_id": attraction_id, "kind": "attraction", "date": day,
                        "start": f"{day}T10:00:00{SYNTHETIC_TIMEZONE}",
                        "end": f"{day}T11:00:00{SYNTHETIC_TIMEZONE}"}],
    }]} for index, day in enumerate(dates)]


def _build_control_plan(task: dict, proposal: dict, start_id: str,
                        selected_by_id: dict[str, tuple[str, dict]]) -> dict:
    start_name = selected_by_id[start_id][1].get("stored_name_unverified")
    days = []
    for occurrence in proposal["occurrences"]:
        entity_id, day = occurrence["entity_id"], occurrence["date"]
        label = selected_by_id[entity_id][1].get("stored_name_unverified")
        days.append({"date": day, "city": task["target_city"], "timeline": [
            {"type": "travel", "origin_id": start_id, "destination_id": entity_id,
             "from": start_name, "to": label,
             "start": "09:00", "end": "09:30",
             "control_note": "reconstructed_synthetic_control"},
            {"type": "visit", "entity_id": entity_id, "entity": label,
             "start": "10:00", "end": "11:00",
             "control_note": "reconstructed_synthetic_control"},
        ]})
    return {"uid": task.get("uid"), "level": task.get("level"), "days": days,
            "control_note": "reconstructed_synthetic_control"}


def _record_bindings(task: dict, plan: dict, start_id: str,
                     reader: V4Reader) -> tuple[list[dict], list[dict], list[dict]]:
    selected = _selected_by_id(task)
    # Occurrence keys follow strict_development_orchestrator's exact plan indices.
    occurrence_map: dict[str, list[dict]] = {}
    for day_index, day in enumerate(plan["days"]):
        travel_day = day["date"]
        occurrence_map.setdefault(start_id, []).append({
            "day_index": day_index, "item_index": 0, "role": "travel_origin",
            "requirements": [{"native_field": "lat", "policy_field": "coordinates",
                              "scope": {"travel_date": travel_day}}],
        })
        attraction_id = day["timeline"][0]["destination_id"]
        occurrence_map.setdefault(attraction_id, []).extend([
            {"day_index": day_index, "item_index": 0, "role": "travel_destination",
             "requirements": [{"native_field": "lat", "policy_field": "coordinates",
                               "scope": {"travel_date": travel_day}}]},
            {"day_index": day_index, "item_index": 1, "role": "activity",
             "requirements": [{"native_field": "opentime", "policy_field": "opening_hours",
                               "scope": {"travel_date": travel_day}}]},
        ])

    bindings, mapping_checks, load_errors = [], [], []
    for entity_id, occurrences in sorted(occurrence_map.items()):
        expected = selected.get(entity_id)
        if expected is None:
            load_errors.append({"entity_id": entity_id, "reason": "task_id_kind_mapping_missing_or_ambiguous"})
            continue
        expected_kind = expected[0]
        try:
            record = reader.get(entity_id)
        except Exception as exc:
            load_errors.append({"entity_id": entity_id, "reason": "v4_record_load_failed",
                                "error_type": type(exc).__name__})
            continue
        matched = (record.get("id") == entity_id and record.get("kind") == expected_kind
                   and record.get("city") == task.get("target_city"))
        mapping_checks.append({"entity_id": entity_id, "expected_kind": expected_kind,
                               "id_kind_city_match": matched,
                               "independent_identity_verified": False})
        # Preserve the V4 record unchanged. If the task label or row metadata is
        # inconsistent, downstream strict validation rejects it conservatively.
        bindings.append({"entity_id": entity_id, "kind": expected_kind,
                         "record": record, "occurrences": occurrences})
    return bindings, mapping_checks, load_errors


def _run_one(city: str, task: dict, reader: V4Reader) -> dict:
    dates = _dates_for(task)
    selected = _selected_by_id(task)
    ids = task.get("candidate_selection", {}).get("required_entity_ids", [])
    attraction_ids = [entity_id for entity_id in ids if entity_id in selected
                      and selected[entity_id][0] == "attraction"]
    start_ids = []
    for kind in START_KIND_ORDER:
        start_ids.extend(entity_id for entity_id in ids if entity_id in selected
                         and selected[entity_id][0] == kind)
    if dates is None or len(attraction_ids) != 1 or not start_ids:
        return {"city": city, "task_uid": task.get("uid"),
                "label": "engineering_only", "status": "solver_incomplete",
                "context_gap": {"dates_valid_three_day": dates is not None,
                                "unique_attraction_id": len(attraction_ids) == 1,
                                "synthetic_start_entity_available": bool(start_ids)},
                "real_world_feasibility_certified": False,
                "truth_certified": False, "frozen": False}

    attraction_id, start_id = attraction_ids[0], start_ids[0]
    generator = generate_multiday_candidate_proposals(
        _synthetic_slots(attraction_id, dates), expected_dates=dates, max_combinations=8)
    if generator.get("status") != "candidate_proposal_unverified" or len(generator.get("proposals", [])) != 1:
        return {"city": city, "task_uid": task.get("uid"),
                "label": "engineering_only", "status": "solver_incomplete",
                "candidate_generator": generator,
                "real_world_feasibility_certified": False,
                "truth_certified": False, "frozen": False}

    proposal = generator["proposals"][0]
    plan = _build_control_plan(task, proposal, start_id, selected)
    context = {"start_city": task.get("start_city"), "target_city": task.get("target_city"),
               "start_date": task.get("start_date"), "days": task.get("days"),
               "people_number": task.get("people_number"),
               "start_location_id": start_id,
               "control_note": "reconstructed_synthetic_control"}
    bindings, mapping_checks, load_errors = _record_bindings(task, plan, start_id, reader)

    def resolver(_task_copy, assignment):
        assigned = assignment.get("proposal")
        if not isinstance(assigned, dict) or assigned.get("proposal_id") != proposal.get("proposal_id"):
            raise ValueError("proposal_assignment_unexpected")
        resolved_plan = _build_control_plan(task, assigned, start_id, selected)
        return {"plan": resolved_plan, "plan_context": copy.deepcopy(context),
                "record_bindings": copy.deepcopy(bindings), "now": SYNTHETIC_NOW,
                "registry": {}, "diagnostic_callbacks": {}}

    # Deliberately no independent verifier. In particular, no identity, field
    # evidence, route, opening-hours, cost, schedule, or interval verifier runs.
    search = search_development_assignments(
        task, {"proposal": [proposal]}, resolver=resolver, decision_verifier=None,
        max_assignments=8)
    diagnostic = (search.get("diagnostics") or [{}])[0].get("diagnostic", {})
    axes = diagnostic.get("axes", {}) if isinstance(diagnostic, dict) else {}
    axis_gaps = {name: [gap.get("reason") for gap in gaps if isinstance(gap, dict)]
                 for name, gaps in axes.items() if isinstance(gaps, list)}
    return {
        "city": city, "task_uid": task.get("uid"),
        "input_label": "reconstructed_synthetic_control",
        "start_location_id": start_id, "start_is_user_intent": False,
        "plan_times_are_synthetic": True,
        "candidate_proposal_status": generator.get("status"),
        "candidate_entity_ids": sorted({item["entity_id"] for item in proposal["occurrences"]}),
        "bound_entity_ids": sorted(item["entity_id"] for item in bindings),
        "record_mapping_checks": mapping_checks, "record_load_errors": load_errors,
        "independent_identity_verifier_configured": False,
        "field_evidence_verifier_configured": False,
        "all_fact_verifiers_disabled": True,
        "candidate_proposal_count": len(generator.get("proposals", [])),
        "search_status": search.get("status"),
        "search_decision_counts": search.get("decision_counts"),
        "search_candidate_count": search.get("candidate_count"),
        "search_solver_incomplete": search.get("status") == "solver_incomplete",
        "diagnostic_axes": axis_gaps,
        "planner_integrated": False,
        "complete_planner_integrated": False,
        "engineering_only": True,
        "formal_score": None, "frozen": False,
        "truth_certified": False,
        "real_world_feasibility_certified": False,
        "execution_confirmed": False,
    }


def run(cohort_path: Path, catalog_path: Path) -> dict:
    cohort_before = sha256_file(cohort_path)
    catalog_before = sha256_file(catalog_path)
    cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
    tasks_by_city, counts = _choose_task_by_city(cohort)
    reader = V4Reader(catalog_path)
    try:
        cities = [_run_one(city, tasks_by_city[city], reader) for city in sorted(EXPECTED_CITIES)]
    finally:
        reader.close()
    cohort_after = sha256_file(cohort_path)
    catalog_after = sha256_file(catalog_path)
    return {
        "artifact": "strict-multiday-v4-reconstructed-control-smoke-v1",
        "label": "engineering_only",
        "mode": "read_only_v6_development_and_v4_record_bindings_with_synthetic_control",
        "control_definition": {
            "marker": "reconstructed_synthetic_control",
            "human_times_are_not_user_intent": True,
            "synthetic_start_is_not_user_intent": True,
            "synthetic_plan_is_not_a_travel_fact_or_route_claim": True,
            "v4_records_are_loaded_by_real_ids_but_identity_is_not_verified": True,
        },
        "source_inputs": {
            "cohort": str(cohort_path.resolve()), "cohort_sha256_before": cohort_before,
            "cohort_sha256_after": cohort_after,
            "catalog": str(catalog_path.resolve()), "catalog_sha256_before": catalog_before,
            "catalog_sha256_after": catalog_after,
            "inputs_unchanged": cohort_before == cohort_after and catalog_before == catalog_after,
        },
        "runtime_code_snapshot": runtime_code_manifest(),
        "development_task_count": counts[0]["development_task_count"],
        "city_task_count": len(cities), "cities": cities,
        "all_fact_verifiers_disabled": True,
        "bounded_candidate_count": 0,
        "formal_evaluation_performed": False,
        "freeze_approved": False,
        "global_unsat_claimed": False,
        "holdout_task_payload_used": False,
    }


def write_markdown(report: dict, target: Path) -> None:
    lines = [
        "# 五城三日 v4 合成控制冒烟（2026-10-31）", "",
        "此工件只验证本地接口连通性。每城挑选一条 v6 development task；候选实体和记录按真实 ID 读取/绑定，但起点与时段由脚本重建，标记为 `reconstructed_synthetic_control`。它们不是用户意图、旅行事实或路线主张。未配置身份、字段证据、路线、开放时间、费用、时刻表或其他事实验证器。", "",
        "## 输入完整性", "",
        f"- 开发任务数：{report['development_task_count']}；五城控制任务数：{report['city_task_count']}。",
        f"- cohort SHA-256：`{report['source_inputs']['cohort_sha256_before']}`（前后相同：{report['source_inputs']['cohort_sha256_before'] == report['source_inputs']['cohort_sha256_after']}）。",
        f"- v4 catalog SHA-256：`{report['source_inputs']['catalog_sha256_before']}`（前后相同：{report['source_inputs']['catalog_sha256_before'] == report['source_inputs']['catalog_sha256_after']}）。",
        f"- 运行代码快照：{report['runtime_code_snapshot']['module_count_including_script']} 个脚本/已加载 shorttrip Python 模块；manifest SHA-256：`{report['runtime_code_snapshot']['manifest_sha256']}`。完整路径与各文件 SHA-256 见 JSON。此快照用于工程复现，不是正式冻结版本。",
        "- catalog 通过只读 SQLite URI 打开；没有网络请求或数据库写入。筛选开发行时只检查 cohort 条目的 split/purpose 字段；未使用或汇报任何留出题内容、结果或逐题信息。", "",
        "## 五城结果", "",
        "| 城市 | task uid | 候选 proposals | search 状态 | pass | unknown | v4 ID/kind/city 映射 | verifier | 冻结/认证 |",
        "|---|---|---:|---|---:|---:|---|---|---|",
    ]
    for item in report["cities"]:
        counts = item.get("search_decision_counts") or {}
        matches = all(row.get("id_kind_city_match") is True
                      for row in item.get("record_mapping_checks", []))
        lines.append(f"| {item['city']} | {item.get('task_uid')} | {item.get('candidate_proposal_count', 0)} | {item.get('search_status', item.get('status'))} | {counts.get('pass', 0)} | {counts.get('unknown', 0)} | {'structural match' if matches else 'gap'} | 全部关闭 | false |")
    lines += ["", "## 解释与边界", "",
        "候选生成器只枚举传入的三日 attraction occurrence。plan 中每天的 09:00–09:30 travel 与 10:00–11:00 visit，以及作为起点的 task-selected ID，均是演示输入；即使引用 v4 真实 ID，也没有验证地点间路线、身份、时段、价格或开放状态。严格诊断收到实际 v4 记录与逐 occurrence 日期 scope，但 verifier 均关闭，因此这些记录不能成为事实通过。", "",
        "所有结果保留为 `engineering_only`；预期为 `unknown/solver_incomplete`，不是失败的真实行程，也不证明全局无解。P31 planner/coverage gap 保留；没有 bounded candidate、正式评分或冻结认证。", "",
        "## 复现", "",
        "```powershell", "$env:PYTHONPATH='src'",
        "python scripts/strict_multiday_v4_control_smoke.py --out-dir results/manual_20261031/<new-run-directory>", "```", "",
        "脚本在创建目录或写文件前检查 JSON 与 Markdown 两个目标；若已存在则拒绝覆盖。默认输出名为 `strict_multiday_v4_control_smoke.json` 与 `.md`。"]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    json_path = args.out_dir / "strict_multiday_v4_control_smoke.json"
    markdown_path = args.out_dir / "strict_multiday_v4_control_smoke.md"
    existing = [str(path) for path in (json_path, markdown_path) if path.exists()]
    if existing:
        parser.error("refusing to overwrite existing artifact(s): " + ", ".join(existing)
                     + "; choose a new --out-dir")
    report = run(args.cohort, args.catalog)
    if not report["source_inputs"]["inputs_unchanged"]:
        raise RuntimeError("source input changed during read-only smoke")
    if any((city.get("search_decision_counts") or {}).get("pass", 0) != 0
           for city in report["cities"]):
        raise RuntimeError("unexpected pass in verifier-disabled engineering control; refusing artifact")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    write_markdown(report, markdown_path)
    print(json.dumps({"json": str(json_path.resolve()),
                      "markdown": str(markdown_path.resolve()),
                      "city_count": report["city_task_count"],
                      "freeze_approved": report["freeze_approved"],
                      "inputs_unchanged": report["source_inputs"]["inputs_unchanged"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
