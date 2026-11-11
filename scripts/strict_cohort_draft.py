"""Generate a review-only, non-frozen cohort proposal from the local catalog."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

CITIES = ["西安", "厦门", "宁波", "长沙", "青岛"]
KINDS = ["attraction", "restaurant", "accommodation", "poi", "metro_station", "train", "flight"]
CHAIN_KINDS = ["attraction", "restaurant", "accommodation"]
AUX_KINDS = ["poi", "metro_station", "train", "flight"]
KIND_LABELS = {"attraction": "景点", "restaurant": "餐厅", "accommodation": "住宿",
               "poi": "地点", "metro_station": "地铁站", "train": "火车", "flight": "航班"}
LEVELS = ["easy", "medium", "human"]
SEED = 2026103003
BUDGET_CNY_TOTAL = 6000
PEOPLE = 2
INCLUDED_COSTS = ["intercity", "local_transport", "tickets", "meals", "rooms"]
START_DATE = "2026-11-15"

# id, expression, strength, wording variants. Operators stay unmapped.
EXTRAS = {
    "walkable": ({"op": "prefer_tag", "args": {"tag": "walkable"}}, "soft", "any",
                 ["至少一个所选景点优先考虑步行方便的选项", "所选景点中至少一处尽量选择步行方便的安排"]),
    "local_food": ({"op": "prefer_tag", "args": {"tag": "local_food"}}, "soft", "any",
                   ["所选餐厅中至少一家优先考虑本地风味", "至少一家所选餐厅尽量选择本地风味"]),
    "low_crowd": ({"op": "prefer_tag", "args": {"tag": "low_crowd"}}, "soft", "any",
                  ["至少一个所选景点优先考虑人少一些的选项", "所选景点中至少一处尽量避开拥挤地点"]),
    "rain_indoor": ({"op": "conditional_prefer_tag", "args": {
        "if": {"weather": "rain"}, "prefer": {"setting": "indoor"}}}, "soft", "any",
        ["若行程期间经核实会下雨，则至少一个所选景点优先选择室内选项", "如果确认遇雨，至少有一处所选景点尽量安排室内", "下雨条件成立时，至少一个所选景点优先考虑室内"]),
    "exclude_night": ({"op": "exclude_tag", "args": {"tag": "night_activity"}}, "hard", "all",
                       ["所选景点中的每一项都不得是夜间活动", "所有所选景点均排除夜间活动", "所选景点中任何一项都不安排夜间活动"]),
}
TAG_ITEM_KIND = {"walkable": "attraction", "local_food": "restaurant",
                 "low_crowd": "attraction", "rain_indoor": "attraction",
                 "exclude_night": "attraction"}
BUDGET_WORDINGS = [
    "两人全程总预算不超过人民币6000元，包含城际交通、市内交通、门票、餐饮和住宿",
    "请把两人总花费控制在6000元以内，城际与市内交通、门票、餐饮、住宿都计入",
    "全程两人预算上限为人民币6000元，需覆盖城际交通、市内交通、门票、餐饮及住宿",
]
INTRO_TEMPLATES = [
    "帮我安排{city}3天行程，两个人，{date}出发。",
    "想在{date}开始去{city}待3天，共2人，麻烦规划一下。",
    "请做一份{city}的3日双人安排，起始日期是{date}。",
    "我和同伴计划从{date}起在{city}游玩3天，请协助规划。",
]


def _rank(seed: int | str, city: str, kind: str, entity_id: str) -> str:
    return hashlib.sha256(f"{seed}\0{city}\0{kind}\0{entity_id}".encode()).hexdigest()


def _assignment_rank(city: str, split: str, kind: str, uid: str) -> str:
    return hashlib.sha256(f"{SEED}\0assign\0{city}\0{split}\0{kind}\0{uid}".encode()).hexdigest()


def _extra_ids(level: str, city: str, split: str, ordinal: int) -> list[str]:
    if level == "easy":
        return []
    if level == "human":
        return ["local_food", "rain_indoor", "exclude_night"]
    # Three additions plus the hard budget give four logical constraints.
    options = ["walkable", "local_food", "low_crowd", "rain_indoor", "exclude_night"]
    start = int(_rank(SEED, city, level, f"{split}:{ordinal}")[:8], 16) % len(options)
    return [options[(start + offset) % len(options)] for offset in range(3)]


def _phrases(extra_ids: list[str], task_index: int) -> list[str]:
    budget = BUDGET_WORDINGS[task_index % len(BUDGET_WORDINGS)]
    out = [budget]
    for ident in extra_ids:
        variants = EXTRAS[ident][3]
        out.append(variants[task_index % len(variants)])
    return out


def generate(database: Path) -> dict:
    con = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    records: dict[tuple[str, str], list[dict]] = {}
    for row in con.execute("SELECT id,city,kind,name FROM records"):
        records.setdefault((row["city"], row["kind"]), []).append(dict(row))
    con.close()

    tasks: list[dict] = []
    city_metadata = []
    for city in CITIES:
        coverage = {split: {kind: 0 for kind in KINDS} for split in ("development", "holdout")}
        task_ids_by_split: dict[str, set[str]] = {"development": set(), "holdout": set()}
        specs = []
        for level_index, level in enumerate(LEVELS):
            for split, count in (("development", 4), ("holdout", 2)):
                for ordinal in range(1, count + 1):
                    task_index = level_index * 6 + (0 if split == "development" else 4) + ordinal - 1
                    aux_order = sorted(AUX_KINDS, key=lambda k: _rank(f"{SEED}-aux", city, k, k))
                    aux = aux_order[task_index % len(aux_order)]
                    required = CHAIN_KINDS + [aux]
                    for kind in required:
                        coverage[split][kind] += 1
                    uid = f"draft-v6-{city}-{level}-{split}-{ordinal}"
                    specs.append({"level": level, "level_index": level_index, "split": split,
                                  "ordinal": ordinal, "task_index": task_index, "aux": aux,
                                  "required": required, "uid": uid})

        # Core kinds use fixed, disjoint pools with balanced reuse. Auxiliary
        # pools use one distinct candidate per actual occurrence in that split.
        pools: dict[str, dict[str, list[dict]]] = {"development": {}, "holdout": {}}
        assignments: dict[str, dict[str, dict[str, dict]]] = {
            split: {spec["uid"]: {} for spec in specs if spec["split"] == split}
            for split in ("development", "holdout")}
        for kind in KINDS:
            ordered = sorted(records.get((city, kind), []),
                             key=lambda r: (_rank(SEED, city, kind, r["id"]), r["id"]))
            dev_specs = [s for s in specs if s["split"] == "development" and kind in s["required"]]
            hold_specs = [s for s in specs if s["split"] == "holdout" and kind in s["required"]]
            dev_size = 4 if kind in CHAIN_KINDS else len(dev_specs)
            hold_size = 2 if kind in CHAIN_KINDS else len(hold_specs)
            needed = dev_size + hold_size
            if len(ordered) < needed:
                raise ValueError(f"insufficient disjoint candidates for {city}/{kind}: {len(ordered)} < {needed}")
            pools["development"][kind] = ordered[:dev_size]
            pools["holdout"][kind] = ordered[dev_size:needed]
            for split, occurrences in (("development", dev_specs), ("holdout", hold_specs)):
                pool = pools[split][kind]
                if not pool and occurrences:
                    raise ValueError(f"empty candidate pool for {city}/{split}/{kind}")
                ranked_specs = sorted(occurrences,
                    key=lambda s: (_assignment_rank(city, split, kind, s["uid"]), s["uid"]))
                for index, spec in enumerate(ranked_specs):
                    assignments[split][spec["uid"]][kind] = pool[index % len(pool)]

        for spec in specs:
            level, split, ordinal = spec["level"], spec["split"], spec["ordinal"]
            task_index, aux, required, uid = spec["task_index"], spec["aux"], spec["required"], spec["uid"]
            entities = assignments[split][uid]
            ids = [entities[k]["id"] for k in required]
            task_ids_by_split[split].update(ids)

            constraint_ids = _extra_ids(level, city, split, ordinal)
            constraints = [{
                "id": "total_budget", "strength": "hard",
                "scope": {"currency": "CNY", "people": PEOPLE, "unit": "total_trip_cost"},
                "expression": {"op": "total_cost_at_most", "args": {
                    "CNY": BUDGET_CNY_TOTAL, "people": PEOPLE, "includes": INCLUDED_COSTS}},
                "compiler_status": "unmapped",
            }]
            for ident in constraint_ids:
                expression, strength, quantifier, _ = EXTRAS[ident]
                constraints.append({"id": ident, "strength": strength,
                    "scope": {"domain": "trip", "quantifier": quantifier,
                              "item_kind": TAG_ITEM_KIND[ident]},
                    "expression": expression, "compiler_status": "unmapped"})

            chain = [{"kind": kind, "entity_id": entities[kind]["id"],
                      "stored_name_unverified": entities[kind]["name"]}
                     for kind in CHAIN_KINDS]
            phrase_list = _phrases(constraint_ids, task_index)
            labels = "→".join(
                f"{KIND_LABELS[k]}候选“{entities[k]['name']}”（{entities[k]['id']}）"
                for k in CHAIN_KINDS)
            aux_label = f"{KIND_LABELS[aux]}候选“{entities[aux]['name']}”（{entities[aux]['id']}）"
            intro = INTRO_TEMPLATES[task_index % len(INTRO_TEMPLATES)].format(
                city=city, date=START_DATE)
            language = (intro + f"请把业务链按{labels}的顺序组织，并查询辅助类别{aux_label}。" +
                        "这些目录名称只作未核实标签。" + "；".join(phrase_list))
            if aux in ("train", "flight"):
                language += "若涉及城际交通，原请求没有提供出发地和目的地；只保留候选资料待查，不预设方向、线路或已确定交通段。"
            else:
                language += "城际交通方向和线路未提供，相关可行性保持未知，不要补造。"
            language += "此请求为机器生成的合成风格样本，不代表人工撰写。"

            tasks.append({
                "uid": uid, "level": level,
                "task_origin": "synthetic_human_style" if level == "human" else "researcher_generated",
                "purpose": "development" if split == "development" else "holdout",
                "nature_language": language,
                "start_city": city, "target_city": city,
                "days": 3, "people_number": PEOPLE, "start_date": START_DATE,
                "additional_constraints": constraints,
                "required_kinds": required,
                "mode": "collection_static_reference",
                "evidence_policy_id": "strict-v4-engineering-v1-unapproved",
                "generation": {
                    "seed": SEED,
                    "budget_sampling": "fixed total CNY 6000 for two people; independent of actual prices",
                    "feasibility_claim": "not_checked",
                    "business_chain": chain,
                    "auxiliary_kind": aux,
                    "selected_entities_by_kind": {k: {"id": entities[k]["id"],
                        "stored_name_unverified": entities[k]["name"]} for k in required},
                    "logical_constraint_count": len(constraints),
                    "draft_only": True,
                    "constraint_phrases_for_audit": phrase_list,
                },
                "candidate_selection": {
                    "policy": "price-independent deterministic sha256 ranked disjoint pools per exact catalog city/kind; balanced within-split reuse for core kinds; auxiliary candidates assigned without reuse when demand permits; identities remain unverified",
                    "required_entity_ids": ids,
                },
                "split": split,
                **({"medium_variant": "paper_main_3_5"} if level == "medium" else {}),
            })

        city_metadata.append({
            "city": city,
            "development_candidate_ids": sorted(task_ids_by_split["development"]),
            "holdout_candidate_ids": sorted(task_ids_by_split["holdout"]),
            "candidate_ids_disjoint_across_splits": not bool(task_ids_by_split["development"] & task_ids_by_split["holdout"]),
            "unique_candidate_counts_by_split_and_kind": {
                split: {kind: len({s["id"] for s in pools[split][kind]}) for kind in KINDS}
                for split in ("development", "holdout")},
            "kind_coverage_by_split": coverage,
            "all_candidate_identities_verified": False,
        })

    task_count = len(tasks)
    return {
        "artifact_status": "DRAFT_ONLY_NOT_FORMALLY_FROZEN",
        "supersedes_artifact": "cohort_draft_v5.json",
        "supersedes_reason": "V6 preserves V5 task semantics and increases price-independent candidate diversity using deterministic disjoint pools with balanced reuse.",
        "executable": False,
        "formal_freeze": False,
        "evaluation_ready": False,
        "seed": SEED,
        "cities": CITIES,
        "levels": LEVELS,
        "kinds": KINDS,
        "split_design": {"development_total": 60, "holdout_total": 30,
            "development_per_city_level": 4, "holdout_per_city_level": 2,
            "development_holdout_candidate_ids_disjoint": True,
            "candidate_id_reuse_within_split_allowed": True,
            "candidate_pool_policy": {"ranking": "sha256(seed, city, kind, entity_id)",
                "assignment": "sha256(seed, city, split, kind, task_uid), then round-robin within ranked pool",
                "core_pool_sizes": {"development": 4, "holdout": 2},
                "auxiliary_pool_sizes": "one per actual occurrence in split; no reuse within split",
                "selection_uses_price": False},
            "all_seven_kinds_covered_in_each_city_and_split": True,
            "kind_coverage_by_city": city_metadata},
        "fixed_budget": {"amount": BUDGET_CNY_TOTAL, "currency": "CNY", "people": PEOPLE,
            "includes": INCLUDED_COSTS, "basis": "total trip cost for two people",
            "source": "predeclared generator constant; selection and generation do not read price fields"},
        "tag_operator_semantics": {
            "scope_shape": {"domain": "trip", "quantifier": "all|any", "item_kind": "optional selected item kind; requires independent complete inventory for that kind"},
            "prefer_tag": {"any": "softly prefer the tag on at least one selected item of item_kind",
                           "all": "softly prefer the tag on every selected item of item_kind"},
            "conditional_prefer_tag": {"any": "when the independently verified trip condition is true, softly prefer the tag on at least one selected item of item_kind",
                                        "all": "when the independently verified trip condition is true, softly prefer the tag on every selected item of item_kind"},
            "exclude_tag": {"all": "hard requirement that the excluded tag be absent from every selected item of item_kind",
                            "any": "hard requirement that the excluded tag be absent from at least one selected item of item_kind; this does not exclude it from the entire scoped kind"},
            "all_expressions_remain_unmapped": True,
        },
        "tasks": tasks,
        "task_count": task_count,
        "known_limitations": [
            "Catalog IDs and stored names are unverified handles and labels; no real-world identity or suitability is asserted.",
            "Every query has a three-kind attraction-to-restaurant-to-accommodation business chain and one auxiliary kind; this is a draft structure, not a feasible itinerary.",
            "Train and flight are requested as candidate data only; missing origin, destination, direction, route, and applicability stay unknown.",
            "Unknown prices, openings, ticket scope, routes, and date-specific facts are not inferred; the fixed budget is not checked against any prices.",
            "All expressions remain compiler_status=unmapped. The available solver does not interpret the added preference, conditional, or exclusion operators.",
            "TAG scopes now declare all/any and the selected item_kind; only a separate independent scope verifier can establish that scope_items are the complete selected-item-kind inventory.",
            "Human-level samples are synthetic_human_style, not human-authored; preference, conditional, and negation cases are generated examples without human labels.",
            "No semantic evaluator, feasibility witness, infeasibility proof, independent human labels, or formal split freeze exists; do not execute or score this draft.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = generate(args.database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
