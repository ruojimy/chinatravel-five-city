"""P32: cross-analysis of rule planner vs LLM, including gate variants.

Writes results/p32_llm_96/comparison.json and prints a compact table.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from p31_common import read_json, write_json
from p31_static import fields_required, missing_fields

ROOT = Path(__file__).resolve().parents[1]
P31 = ROOT / "results/p31_five_city_96"
P32 = ROOT / "results/p32_llm_96"

TAG24 = "open_24_hours"


def tags_of(c):
    return {t.get("tag"): t.get("value") for t in (c.get("tags") or [])}


def main():
    tasks = {t["uid"]: t for t in read_json(P31 / "tasks/all_96.json")}
    rule = {f["uid"]: f for f in read_json(P31 / "final/plans_all_96.json")}
    scored = {p.stem: read_json(p) for p in (P32 / "scored").glob("*.json")}
    variants = {"base": {}, "strict": {}, "tag_aware": {}}
    rows = []
    for uid, t in tasks.items():
        r, s = rule[uid], scored[uid]
        gate = s["final"]["gate_status"] if s["final"] else None
        conflict = bool(s["final"] and s["final"]["opening_conflict"])
        rule_conflict = bool(r["checks"].get("opening_conflict"))
        # tag-aware: accept source-stated 24h for hours-only blocked tasks
        def tag_resolvable(fin, task):
            if fin["status"] != "blocked" or fin["cost"]["unknown"]:
                return False
            unknown = fin["checks"]["opening_unknown"]
            if not unknown:
                return False
            for name in unknown:
                c = next((x for x in task["candidates"] if x["name"] == name), None)
                if not c or tags_of(c).get(TAG24) is not True:
                    return False
            return True
        variants["base"][uid] = {"rule": r["status"], "llm": gate}
        strict_rule = "infeasible" if (r["status"] == "complete" and rule_conflict) else r["status"]
        strict_llm = ("infeasible" if (gate == "complete" and conflict) else gate) if gate else None
        variants["strict"][uid] = {
            "rule": strict_rule,
            "rule_conflict": rule_conflict,
            "llm": strict_llm,
            "llm_conflict": conflict,
        }
        tag_rule = "complete" if tag_resolvable(r, t) else r["status"]
        tag_llm = ("complete" if (gate == "blocked" and s["final"] and not s["final"]["unknown"]
                                 and s["final"]["checks"]["opening_unknown"]
                                 and all(tags_of(next((x for x in t["candidates"] if x["name"] == n), {})).get(TAG24) is True
                                         for n in s["final"]["checks"]["opening_unknown"]))
                   else gate) if gate else None
        both_rule = "infeasible" if (tag_rule == "complete" and rule_conflict) else tag_rule
        both_llm = ("infeasible" if (tag_llm == "complete" and conflict) else tag_llm) if tag_llm else None
        variants.setdefault("both", {})[uid] = {"rule": both_rule, "llm": both_llm}
        variants["tag_aware"][uid] = {
            "rule": "complete" if tag_resolvable(r, t) else r["status"],
            "llm": ("complete" if (gate == "blocked" and s["final"] and not s["final"]["unknown"]
                                  and all(tags_of(next((x for x in t["candidates"] if x["name"] == n), {})).get(TAG24) is True
                                          for n in s["final"]["checks"]["opening_unknown"]))
                    else gate) if gate else None,
            "rule_tagged": tag_resolvable(r, t),
            "llm_tagged": bool(gate == "blocked" and s["final"] and not s["final"]["unknown"]
                               and s["final"]["checks"]["opening_unknown"]
                               and all(tags_of(next((x for x in t["candidates"] if x["name"] == n), {})).get(TAG24) is True
                                       for n in s["final"]["checks"]["opening_unknown"])),
        }
        rows.append({"uid": uid, "level": t["level"], "scope": s["scope"], "cities": s["cities"]})

    # strict: only when a closing conflict exists does complete become infeasible
    for k in ("rule", "llm"):
        pass

    def counts(key):
        return {lv: dict(Counter(variants[key][u][lv] for u in tasks if tasks[u]["level"] == lv))
                for lv in ("easy", "hard", "human")}

    def totals(key):
        return dict(Counter(variants[key][u]["llm"] for u in tasks)), dict(Counter(variants[key][u]["rule"] for u in tasks))

    # static stage
    static_ok_rule = 0
    static_ok_llm = 0
    static_match = 0
    static_ok_by_level = defaultdict(lambda: {"rule": 0, "llm": 0})
    for uid, t in tasks.items():
        r = rule[uid]
        rule_ok = (r["static"]["closure"] == 1.0 and r["static"]["schedule_ok"]
                   and r["static"]["budget_ok_static"])
        s = scored[uid]["static"]
        llm_ok = bool(s and s["verdict_canonical"] == "ok")
        static_ok_rule += rule_ok
        static_ok_llm += llm_ok
        static_ok_by_level[t["level"]]["rule"] += int(rule_ok)
        static_ok_by_level[t["level"]]["llm"] += int(llm_ok)
        if s and s["verdict_match"]:
            static_match += 1

    # gaps
    gap_req = gap_hit = gap_miss = gap_extra = 0
    gap_tasks_miss = []
    for uid, t in tasks.items():
        g = scored[uid]["gaps"]
        gap_req += len(g["required"])
        gap_hit += len(g["hit"])
        gap_miss += len(g["miss"])
        gap_extra += len(g["extra"])
        if g["miss"]:
            gap_tasks_miss.append((uid, g["miss"]))

    # calibration / arithmetic / evidence / text
    over = [(u, scored[u]["final"]["self_status"], scored[u]["final"]["gate_status"])
            for u in tasks if scored[u]["final"] and scored[u]["final"]["overclaim"]]
    under = [(u,) for u in tasks if scored[u]["final"] and scored[u]["final"]["underclaim"]]
    cost_deltas = [abs(scored[u]["final"]["cost_delta"]) for u in tasks
                   if scored[u]["final"] and scored[u]["final"]["cost_delta"] is not None]
    end_deltas = [abs((int(scored[u]["final"]["self_end"][:2]) * 60 + int(scored[u]["final"]["self_end"][3:]))
                      - (int(scored[u]["final"]["gate_end"][:2]) * 60 + int(scored[u]["final"]["gate_end"][3:])))
                  for u in tasks if scored[u]["final"] and scored[u]["final"].get("self_end")
                  and scored[u]["final"].get("gate_end")]
    ev_valid = sum(scored[u]["final"]["evidence_valid"] for u in tasks if scored[u]["final"])
    ev_used = sum(len(scored[u]["final"]["evidence_used"]) for u in tasks if scored[u]["final"])
    ev_unknown = [e for u in tasks if scored[u]["final"] for e in scored[u]["final"].get("evidence_unknown") or []]
    soft_tasks = [u for u, t in tasks.items() if t["constraints"].get("soft")]
    soft_any = [u for u in soft_tasks if scored[u]["soft_handling"]]
    clar = [len(scored[u]["clarifications"]) for u in tasks]
    ans_len = [len(scored[u]["answer_final"] or "") for u in tasks]
    ans_len_s = [len(scored[u]["answer_static"] or "") for u in tasks]

    out = {
        "tasks": len(tasks),
        "gate_variants": {
            "base": {"rule": dict(Counter(variants["base"][u]["rule"] for u in tasks)),
                     "llm": dict(Counter(variants["base"][u]["llm"] for u in tasks))},
            "strict": {
                "rule": dict(Counter(variants["strict"][u]["rule"] for u in tasks)),
                "llm": dict(Counter(variants["strict"][u]["llm"] for u in tasks)),
                "rule_conflict_tasks": [u for u in tasks if rule[u]["checks"].get("opening_conflict")],
                "llm_conflict_tasks": [u for u in tasks if variants["strict"][u]["llm_conflict"]],
            },
            "tag_aware": {
                "rule": dict(Counter(variants["tag_aware"][u]["rule"] for u in tasks)),
                "llm": dict(Counter(variants["tag_aware"][u]["llm"] for u in tasks)),
                "rule_tagged": [u for u in tasks if variants["tag_aware"][u]["rule_tagged"]],
                "llm_tagged": [u for u in tasks if variants["tag_aware"][u]["llm_tagged"]],
            },
            "both": {
                "rule": dict(Counter(variants["both"][u]["rule"] for u in tasks)),
                "llm": dict(Counter(variants["both"][u]["llm"] for u in tasks)),
            },
        },
        "static": {
            "rule_ok": static_ok_rule, "llm_ok": static_ok_llm,
            "llm_verdict_matches_canonical": static_match,
            "by_level": {k: dict(v) for k, v in static_ok_by_level.items()},
        },
        "gaps": {"required": gap_req, "hit": gap_hit, "miss": gap_miss, "extra": gap_extra,
                 "tasks_with_miss": gap_tasks_miss},
        "calibration": {"overclaim": over, "underclaim": under,
                        "cost_delta_median_cny": statistics.median(cost_deltas) if cost_deltas else None,
                        "cost_delta_max_cny": max(cost_deltas) if cost_deltas else None,
                        "cost_within_1cny": sum(1 for d in cost_deltas if d <= 1.0),
                        "end_delta_median_min": statistics.median(end_deltas) if end_deltas else None,
                        "end_delta_max_min": max(end_deltas) if end_deltas else None,
                        "end_within_5min": sum(1 for d in end_deltas if d <= 5)},
        "evidence": {"used_total": ev_used, "valid_total": ev_valid,
                     "unknown_ids": ev_unknown[:20], "avg_used": round(ev_used / len(tasks), 2)},
        "soft": {"tasks_with_soft": len(soft_tasks), "with_handling": len(soft_any),
                 "coverage": round(len(soft_any) / len(soft_tasks), 3) if soft_tasks else None},
        "text": {"clarifications_avg": round(statistics.mean(clar), 2),
                 "answer_static_avg_chars": round(statistics.mean(ans_len_s)),
                 "answer_final_avg_chars": round(statistics.mean(ans_len))},
        "levels": {lv: {"n": sum(1 for t in tasks.values() if t["level"] == lv),
                        "rule_complete": sum(1 for u, t in tasks.items() if t["level"] == lv and rule[u]["status"] == "complete"),
                        "llm_gate_complete": sum(1 for u, t in tasks.items() if t["level"] == lv and scored[u]["final"] and scored[u]["final"]["gate_status"] == "complete"),
                        "llm_self_complete": sum(1 for u, t in tasks.items() if t["level"] == lv and scored[u]["final"] and scored[u]["final"]["self_status"] == "complete")}
                  for lv in ("easy", "hard", "human")},
    }
    write_json(P32 / "comparison.json", out)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
