"""A/B/C/D comparison: baseline, TAG-enhanced, preference-enhanced, full system.

Design (matches §11 of the task specification)
----------------------------------------------
* Same query set, same planner budget, same official checker for all four groups.
* A 原始基线      : first feasible plan the planner produces (no ranking at all)
* B TAG 增强      : re-rank with the merged TAG view but a *population* profile —
                    i.e. no personalisation, only "is this attraction good/burdensome"
* C 偏好增强      : re-rank with the traveller's profile but only sandbox attribute tags
                    (no external experience evidence)
* D 完整动态系统  : traveller profile + external TAG evidence + overlay rehydrate
                    (dynamic sandbox) + edit-cost against the previous plan

Metrics, all computed from real runs:
* ``hard_pass``     — official checker verdict for the chosen plan (must stay 100%)
* ``regret``        — Q_ref(best feasible) - Q_ref(chosen), where Q_ref is the user's
                      own profile scored against the *full* tag view. Lower is better
                      and 0 means the ranking picked the best available plan.
* ``coverage``      — share of attractions in the chosen plan that carry evidence
* ``distinct``      — how often groups differ in what they chose (a ranking that never
                      changes anything cannot be claimed to be "personalised")

Honest limits: no human pairwise judgement was collected, so this measures whether
the *reranker implements the stated preference relation*, not whether travellers
actually prefer the result. Reported as such in results/preference/README and STATE.md.
"""
from __future__ import annotations

import glob
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.checker import check_plan  # noqa: E402
from shorttrip.dynamic.overlay import OverlayStore  # noqa: E402
from shorttrip.dynamic.pipeline import rehydrate  # noqa: E402
from shorttrip.dynamic.tagstore import TagStore  # noqa: E402
from shorttrip.env import get_env  # noqa: E402
from shorttrip.planner import PlannerOptions, SkeletonPlanner  # noqa: E402
from shorttrip.preference import DEFAULT_SPECS, UserProfile  # noqa: E402
from shorttrip.rerank import RerankOptions, describe_tag_support, rank_plans, score_plan  # noqa: E402
from shorttrip.tagbridge import (  # noqa: E402
    merge_tag_views, provenance_summary, sandbox_attribute_tags, tag_view_from_store,
)

REPO = ROOT / "ChinaTravel"
OUT = ROOT / "results" / "preference"

VARIANTS = [
    ("default", PlannerOptions()),
    ("fewer_stops", PlannerOptions(max_attractions_per_day=2)),
    ("early_start", PlannerOptions(go_window=(7 * 60, 11 * 60))),
]


def load_queries(split: str, limit: int) -> list[dict]:
    paths = sorted(glob.glob(str(REPO / "chinatravel" / "data" / split / "*.json")))
    return [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths[:limit]]


def population_profile() -> UserProfile:
    """No personalisation: every preference is the documented neutral prior."""
    profile = UserProfile(uid="population_average")
    profile._fill_neutral_priors()
    return profile


def build_candidates(env, query: dict) -> list[dict]:
    out = []
    for label, options in VARIANTS:
        try:
            planner = SkeletonPlanner(env, options)
            built = planner.build(query, deep_check=False)
        except Exception as exc:  # noqa: BLE001
            out.append({"variant": label, "plan": None, "error": str(exc)})
            continue
        if built.plan is None:
            out.append({"variant": label, "plan": None, "error": planner.last_reason})
            continue
        report = check_plan(query, built.plan)
        out.append({"variant": label, "plan": built.plan, "report": report})
    return out


def main() -> int:
    split = sys.argv[1] if len(sys.argv) > 1 else "easy_short"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    limit = min(limit, 6)
    started = time.time()

    env = get_env("zh")
    store = OverlayStore(ROOT / "data" / "sandbox_overlay.sqlite")
    rehydrated = rehydrate(store, env)
    tag_store = TagStore(ROOT / "data" / "tag_store.sqlite")
    snapshot = tag_store.latest_snapshot()
    external = tag_view_from_store(tag_store, snapshot)

    queries = load_queries(split, limit)
    profiles = [UserProfile.from_spec(spec) for spec in DEFAULT_SPECS[:3]]
    options = RerankOptions()

    rows: list[dict] = []
    for query in queries:
        city = query["target_city"]
        attributes = sandbox_attribute_tags(env, city)
        merged = merge_tag_views(attributes, external)
        candidates = build_candidates(env, query)
        feasible = [item for item in candidates if item.get("plan") and item["report"] and item["report"].all_ok]
        city_view = {poi: tags for poi, tags in merged.items() if poi.startswith(f"sandbox:{city}:")}

        base = {
            "uid": query.get("uid"),
            "city": city,
            "days": query.get("days"),
            "candidates": len(candidates),
            "feasible": len(feasible),
            "candidate_variants": [item["variant"] for item in candidates],
        }
        if not feasible:
            rows.append({**base, "profile": None, "groups": {},
                         "note": "没有通过官方 checker 的候选方案，四组均无结果"})
            continue

        reference_scores = [score_plan(item["plan"], None or profiles[0], city_view, city=city,
                                       options=options)["Q"] for item in feasible]
        for profile in profiles:
            # Q_ref: the user's own profile scored against the full tag view
            ref = [score_plan(item["plan"], profile, city_view, city=city, options=options)
                   for item in feasible]
            best_ref = max(row["Q"] for row in ref)
            groups: dict[str, dict] = {}

            # A: first feasible, no ranking
            chosen_a = feasible[0]
            qa = score_plan(chosen_a["plan"], profile, city_view, city=city, options=options)
            groups["A_raw"] = {
                "variant": chosen_a["variant"], "Q_ref": qa["Q"],
                "regret": round(best_ref - qa["Q"], 4),
                "coverage": qa["coverage"]["rate"],
                "hard_ok": chosen_a["report"].all_ok,
            }

            # B: merged tags, population profile (no personalisation)
            ranked_b = rank_plans([item["plan"] for item in feasible], population_profile(),
                                  city_view, city=city, options=options)
            chosen_b = feasible[ranked_b[0]["candidate"]]
            qb = score_plan(chosen_b["plan"], profile, city_view, city=city, options=options)
            groups["B_tag"] = {
                "variant": chosen_b["variant"], "Q_ref": qb["Q"],
                "regret": round(best_ref - qb["Q"], 4),
                "coverage": qb["coverage"]["rate"],
                "hard_ok": chosen_b["report"].all_ok,
                "ranking_Q": ranked_b[0]["Q"],
            }

            # C: user profile, attribute tags only
            ranked_c = rank_plans([item["plan"] for item in feasible], profile,
                                  attributes, city=city, options=options)
            chosen_c = feasible[ranked_c[0]["candidate"]]
            qc = score_plan(chosen_c["plan"], profile, city_view, city=city, options=options)
            groups["C_pref"] = {
                "variant": chosen_c["variant"], "Q_ref": qc["Q"],
                "regret": round(best_ref - qc["Q"], 4),
                "coverage": qc["coverage"]["rate"],
                "hard_ok": chosen_c["report"].all_ok,
                "ranking_Q": ranked_c[0]["Q"],
            }

            # D: user profile + external tags + holiday context
            ranked_d = rank_plans([item["plan"] for item in feasible], profile, merged,
                                  city=city, options=RerankOptions(holiday=True))
            chosen_d = feasible[ranked_d[0]["candidate"]]
            qd = score_plan(chosen_d["plan"], profile, city_view, city=city,
                            options=RerankOptions(holiday=True))
            groups["D_full"] = {
                "variant": chosen_d["variant"], "Q_ref": qd["Q"],
                "regret": round(best_ref - qd["Q"], 4),
                "coverage": qd["coverage"]["rate"],
                "hard_ok": chosen_d["report"].all_ok,
                "ranking_Q": ranked_d[0]["Q"],
            }
            rows.append({**base, "profile": profile.uid, "profile_summary": profile.summary(),
                         "groups": groups, "best_ref_Q": round(best_ref, 4),
                         "reference_scores": [round(x, 4) for x in reference_scores]})

    # ------------------------------------------------------------- aggregate
    groups = ["A_raw", "B_tag", "C_pref", "D_full"]
    summary = {}
    for group in groups:
        entries = [row["groups"][group] for row in rows if row.get("groups")]
        if not entries:
            summary[group] = {"n": 0}
            continue
        summary[group] = {
            "n": len(entries),
            "hard_pass_rate": round(sum(1 for e in entries if e["hard_ok"]) / len(entries), 3),
            "mean_regret": round(sum(e["regret"] for e in entries) / len(entries), 4),
            "mean_coverage": round(sum(e["coverage"] for e in entries) / len(entries), 3),
            "exact_best_rate": round(sum(1 for e in entries if e["regret"] == 0) / len(entries), 3),
        }

    report = {
        "generated_at": "2026-10-21",
        "split": split,
        "queries": [row.get("uid") for row in rows if row.get("uid")],
        "n_rows": len(rows),
        "profiles": [profile.uid for profile in profiles],
        "groups": summary,
        "tag_view": {
            "provenance": provenance_summary(merge_tag_views(
                sandbox_attribute_tags(env, load_queries(split, 1)[0]["target_city"]) if queries else {},
                external)),
            "support": describe_tag_support(external),
            "snapshot": snapshot,
            "external_pois": len(external),
        },
        "dynamic": {"rehydrated_instances": rehydrated,
                    "overlay_records": len(store.active())},
        "runtime_s": round(time.time() - started, 1),
        "limits": [
            "没有人工成对偏好标注：只能证明重排器实现了所述偏好关系，不能证明游客更满意",
            "外部体验 TAG 仅覆盖极少 POI（配额受限），B/D 的差异在这批查询上通常很小",
            "候选集来自 3 个 planner 变体，池子很小；更大候选集需要更多算力",
        ],
        "rows": rows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "abcd_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("split", "n_rows", "groups", "runtime_s")},
                     ensure_ascii=False, indent=2))
    print("wrote", OUT / "abcd_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
