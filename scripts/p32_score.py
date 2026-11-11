"""P32: score the LLM's 96 tasks with the same rule gate as P31, and compare.

Reads:
  results/p31_five_city_96/{tasks,static,final,retrieval}   (rule baseline + frozen evidence)
  results/p32_llm_96/{packs,baseline.json,out/*.json}       (LLM inputs + outputs)

Writes:
  results/p32_llm_96/evaluation_llm_96.csv
  results/p32_llm_96/summary_llm_96.json
  results/p32_llm_96/comparison.json
  results/p32_llm_96/scored/<uid>.json
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from p31_common import (OUT as P31, entity_coord, haversine_km, hhmm_to_min, known,
                        min_to_hhmm, read_json, write_json)
from p31_finalize import build_final, load_details, load_responses
from p31_static import (LUNCH_MIN, LUNCH_WINDOW, TRAVEL_KMH, TRANSFER_BUFFER, _run_sequence,
                        coord_of_cand, fields_required, missing_fields, visit_minutes, window_of)

ROOT = Path(__file__).resolve().parents[1]
P32 = ROOT / "results/p32_llm_96"


def _load_p32_reqs():
    p = P32 / "retrieval/planned_requests.json"
    out = {}
    if p.exists():
        for r in read_json(p):
            out.setdefault(r["uid"], []).append(r)
    return out


P32_REQS = _load_p32_reqs()

CAT = {"price": "price", "opentime": "hours", "endtime": "hours",
       "lat": "coord", "lon": "coord",
       "From": "intercity", "To": "intercity", "BeginTime": "intercity",
       "EndTime": "intercity", "Duration": "intercity", "Cost": "intercity"}
OPTIONAL_FIELDS = {"recommendmintime", "recommendmaxtime", "hotelname_en", "numbed",
                   "recommendedfood", "featurehoteltype", "cuisine"}


def attraction_names(task):
    return [c["name"] for c in task["candidates"] if c["kind"] == "attraction"]


def restaurant_of(task):
    return next((c for c in task["candidates"] if c["kind"] == "restaurant"), None)


def norm_name(s):
    return str(s or "").strip()


def order_check(task, order, lunch_after):
    atts = attraction_names(task)
    rest = restaurant_of(task)
    ok_order = isinstance(order, list) and len(order) == len(atts) and set(order) == set(atts)
    if rest:
        ok_lunch = isinstance(lunch_after, int) and 0 <= lunch_after <= len(order)
    else:
        ok_lunch = lunch_after is None
    return ok_order, ok_lunch


def split_order(task, order):
    """Chains sometimes append the old-city attraction; keep only day-1 candidates."""
    atts = attraction_names(task)
    pool = set(atts)
    order = order if isinstance(order, list) else []
    kept = [n for n in order if n in pool]
    extras = [n for n in order if n not in pool]
    ok = len(kept) == len(atts) and set(kept) == pool
    return kept, extras, ok


def synth_plan(task, order, lunch_after):
    timeline = []
    rest = restaurant_of(task)
    lunch = lunch_after if rest and isinstance(lunch_after, int) else None
    for i, name in enumerate(order):
        timeline.append({"type": "visit", "entity": name})
        if lunch is not None and i + 1 == lunch:
            timeline.append({"type": "meal", "entity": rest["name"]})
    days = [{"date": task["dates"][0], "city": task["city_sequence"][0], "timeline": timeline}]
    if task.get("intercity"):
        days.append({"date": task["dates"][1], "city": task["city_sequence"][1]})
    return {"days": days, "static": {}}


def canonical_static(task, order, lunch_after):
    """Static-stage checks mirroring p31_static.build_plan, on a fixed order."""
    people = task["people_number"]
    cons = task["constraints"]
    start_min = hhmm_to_min(cons.get("start_time") or "09:00")
    deadline = hhmm_to_min(cons["window"][1])
    start = task["start"]
    start_coord = {"lat": start["position_wgs84"][0], "lon": start["position_wgs84"][1],
                   "system": "WGS84"}
    by_name = {c["name"]: c for c in task["candidates"]}
    rest = restaurant_of(task)
    lunch = lunch_after if rest and isinstance(lunch_after, int) else None
    before = [by_name[n] for n in order[:lunch]] if lunch is not None else [by_name[n] for n in order]
    after = [by_name[n] for n in order[lunch:]] if lunch is not None else []
    r = _run_sequence(before, rest if lunch is not None else None, after,
                      start_coord, start_min, deadline)
    required = fields_required(task)
    present = 0
    for eid, f in required:
        c = next((x for x in task["candidates"] if x["entity_id"] == eid), None)
        if c is None and task.get("old_city") and task["old_city"]["attraction"]["entity_id"] == eid:
            c = task["old_city"]["attraction"]
        if c is not None and known((c.get("data") or {}).get(f)):
            present += 1
    closure = present / len(required) if required else 1.0

    unknown, cost = [], 0.0
    for c in task["candidates"]:
        d = c["data"]
        if c["kind"] == "attraction":
            if known(d.get("price")):
                cost += float(d["price"]) * people
            else:
                unknown.append(c["name"] + ":price")
        elif c["kind"] == "restaurant" and lunch is not None:
            if known(d.get("price")):
                cost += float(d["price"]) * people
            else:
                unknown.append(c["name"] + ":price")
        elif c["kind"] == "accommodation":
            if known(d.get("price")):
                cost += float(d["price"])
            else:
                unknown.append(c["name"] + ":price")
        elif c["kind"] in ("train", "flight"):
            if known(d.get("Cost")):
                cost += float(d["Cost"]) * people
            else:
                unknown.append(c["name"] + ":Cost")
    legs = len(order) + 1 + (1 if lunch is not None else 0)
    transit = 5 * people * legs
    budget_limit = task["static_estimate"]["budget_limit"]
    budget_ok = (not unknown) and (cost + transit <= budget_limit + 1e-6)
    if unknown or closure < 0.999:
        verdict = "blocked"
    elif not r["feasible"] or r["end"] > deadline:
        verdict = "infeasible"
    else:
        verdict = "ok"
    return {
        "closure": round(closure, 4),
        "end": min_to_hhmm(r["end"]),
        "end_min": r["end"],
        "schedule_ok": bool(r["feasible"]) and r["end"] <= deadline,
        "reasons": r["reasons"], "warnings": r["warnings"],
        "known_cost": round(cost, 1), "transit_estimate": transit,
        "budget_ok": budget_ok, "budget_limit": budget_limit,
        "unknown": unknown, "verdict": verdict,
    }


def gap_sets(task):
    req = set()
    for g in missing_fields(task):
        cat = CAT.get(g["field"])
        if cat:
            req.add((g["entity"], cat))
    return req


def norm_gap(g):
    entity = norm_name(g.get("entity"))
    field = str(g.get("field") or "")
    low = field.lower()
    if any(k in low for k in ("price", "ticket", "cost", "票价", "门票", "价")):
        cat = "price"
    elif any(k in low for k in ("open", "hour", "time", "营业", "开放", "时段", "关门")):
        cat = "hours"
    elif any(k in low for k in ("lat", "lon", "coord", "坐标")):
        cat = "coord"
    elif any(k in low for k in ("from", "to", "begin", "end", "duration", "车次", "航班", "时刻", "班次")):
        cat = "intercity"
    else:
        cat = None
    return entity, field, cat


def score_gaps(task, gaps):
    req = gap_sets(task)
    reported, optional_noise, unknown_fields = set(), [], []
    for g in gaps or []:
        entity, field, cat = norm_gap(g)
        if field in OPTIONAL_FIELDS:
            optional_noise.append({"entity": entity, "field": field})
            continue
        if cat is None:
            unknown_fields.append({"entity": entity, "field": field})
            continue
        reported.add((entity, cat))
    hit = req & reported
    return {
        "required": sorted(f"{e}::{c}" for e, c in req),
        "reported": sorted(f"{e}::{c}" for e, c in reported),
        "hit": sorted(f"{e}::{c}" for e, c in hit),
        "miss": sorted(f"{e}::{c}" for e, c in (req - reported)),
        "extra": sorted(f"{e}::{c}" for e, c in (reported - req)),
        "optional_noise": optional_noise,
        "unknown_field_names": unknown_fields,
        "recall": round(len(hit) / len(req), 3) if req else 1.0,
        "precision": round(len(hit) / len(reported), 3) if reported else (1.0 if not req else 0.0),
    }


def price_hallucinations(task, items):
    price_of = {}
    for c in task["candidates"]:
        if c["kind"] in ("attraction", "restaurant", "accommodation"):
            price_of[c["name"]] = c["data"].get("price")
    bad = []
    for it in items or []:
        ent, amt = norm_name(it.get("entity")), it.get("amount")
        if ent in price_of and price_of[ent] is None and amt not in (None, 0, 0.0):
            bad.append({"entity": ent, "amount": amt})
    return bad


def load_out(uid, stage):
    p = P32 / "out" / f"{uid}_{stage}.json"
    if not p.exists():
        return None, "missing"
    try:
        d = read_json(p)
    except Exception as e:
        return None, f"invalid_json:{e.__class__.__name__}"
    if d.get("uid") != uid:
        return d, "uid_mismatch"
    return d, "ok"


def main():
    tasks = read_json(P31 / "tasks/all_96.json")
    baseline = {b["uid"]: b for b in read_json(P32 / "baseline.json")}
    responses = load_responses()
    for f in (P32 / "retrieval/responses").rglob("*.json"):
        d = read_json(f)
        responses[(d["uid"], d["req_id"])] = d
    details = load_details()
    (P32 / "scored").mkdir(exist_ok=True)

    rows, per_task = [], {}
    for t in tasks:
        uid = t["uid"]
        s, s_err = load_out(uid, "static")
        f, f_err = load_out(uid, "final")
        s = s or {}
        f = f or {}
        order_s, extras_s, sok = split_order(t, s.get("order"))
        lunch_s = s.get("lunch_after")
        order_f, extras_f, fok = split_order(t, f.get("order") or s.get("order"))
        lunch_f = f.get("lunch_after", lunch_s)
        _, slok = order_check(t, order_s, lunch_s)
        _, flok = order_check(t, order_f, lunch_f)

        # static scoring
        st = canonical_static(t, order_s, lunch_s) if sok else None
        gaps = score_gaps(t, s.get("gaps"))
        halluc = price_hallucinations(t, s.get("budget_items"))
        known_cost = s.get("known_cost")
        cost_delta = None
        cost_basis = None
        if st and isinstance(known_cost, (int, float)):
            d1 = abs(known_cost - st["known_cost"])
            d2 = abs(known_cost - (st["known_cost"] + st["transit_estimate"]))
            cost_delta = round(min(d1, d2), 1)
            cost_basis = "with_transit" if d2 < d1 else "prices_only"

        # final scoring: same deterministic gate as P31
        gate = build_final(t, synth_plan(t, order_f, lunch_f), responses, details) if fok else None
        self_status = f.get("status")
        overclaim = bool(gate and self_status == "complete" and gate["status"] != "complete")
        underclaim = bool(gate and self_status != "complete" and gate["status"] == "complete")
        evidence_used = f.get("evidence_used") or []
        route_reqs = {r["req_id"] for r in baseline[uid]["requests"] if r["type"] == "route"}
        weather_reqs = {r["req_id"] for r in baseline[uid]["requests"] if r["type"] == "weather"}
        other_reqs = {r["req_id"] for r in baseline[uid]["requests"] if r["type"] not in ("route", "weather")}
        p32_reqs = {r["req_id"] for r in P32_REQS.get(uid, [])}
        known_evidence = route_reqs | weather_reqs | other_reqs | p32_reqs
        evidence_valid = sum(1 for e in evidence_used if e in known_evidence)
        evidence_unknown = [e for e in evidence_used if e not in known_evidence]
        cost_delta_final = None
        if gate and isinstance(f.get("total_cost"), (int, float)):
            cost_delta_final = round(f["total_cost"] - gate["cost"]["total"], 1)

        rec = {
            "uid": uid, "level": t["level"], "scope": baseline[uid]["scope"],
            "cities": "+".join(t["city_sequence"]),
            "rule_status": baseline[uid]["status"],
            "rule_order": baseline[uid]["order"],
            "rule_lunch_after": baseline[uid]["lunch_after"],
            "static_file": s_err, "final_file": f_err,
            "order_ok": sok, "lunch_ok": slok,
            "order_extras_static": extras_s, "order_extras_final": extras_f,
            "order_changed": bool(sok and fok and order_s != order_f),
            "lunch_changed": bool(sok and fok and lunch_s != lunch_f),
            "static": None if not st else {
                "closure": st["closure"], "schedule_ok": st["schedule_ok"],
                "budget_ok": st["budget_ok"], "end": st["end"],
                "verdict_canonical": st["verdict"], "verdict_llm": s.get("verdict"),
                "verdict_match": s.get("verdict") == st["verdict"],
                "known_cost_canonical": st["known_cost"], "known_cost_llm": known_cost,
                "cost_delta": cost_delta, "cost_basis": cost_basis,
            },
            "gaps": gaps,
            "hallucinated_prices": halluc,
            "soft_handling": s.get("soft_handling") or [],
            "clarifications": s.get("clarifications") or [],
            "final": None if not gate else {
                "gate_status": gate["status"], "self_status": self_status,
                "status_match": self_status == gate["status"], "overclaim": overclaim,
                "underclaim": underclaim,
                "gate_end": gate["end"], "self_end": f.get("end_time"),
                "gate_cost": gate["cost"]["total"], "self_cost": f.get("total_cost"),
                "cost_delta": cost_delta_final,
                "checks": gate["checks"], "reasons": gate["reasons"],
                "self_checks": f.get("checks"),
                "unknown": gate["cost"]["unknown"],
                "unsolved": f.get("unsolved") or [],
                "changes": f.get("changes") or [],
                "evidence_used": evidence_used, "evidence_valid": evidence_valid,
                "evidence_unknown": evidence_unknown,
                "opening_conflict": gate["checks"]["opening_conflict"],
            },
            "answer_static": s.get("answer"), "answer_final": f.get("answer"),
        }
        per_task[uid] = rec
        write_json(P32 / "scored" / f"{uid}.json", rec)

        rows.append({
            "uid": uid, "level": t["level"], "scope": rec["scope"], "cities": rec["cities"],
            "rule_status": rec["rule_status"],
            "static_ok": bool(sok and st and st["verdict"] == "ok"),
            "static_verdict_llm": s.get("verdict"),
            "static_verdict_canonical": st["verdict"] if st else "",
            "gap_recall": gaps["recall"], "gap_precision": gaps["precision"],
            "gap_miss": ";".join(gaps["miss"]), "gap_extra": ";".join(gaps["extra"]),
            "hallucinated_price_count": len(halluc),
            "gate_status": gate["status"] if gate else "",
            "self_status": self_status or "",
            "status_match": (self_status == gate["status"]) if gate else False,
            "overclaim": overclaim, "underclaim": underclaim,
            "order_ok": sok, "lunch_ok": slok,
            "order_changed": rec["order_changed"],
            "evidence_used": len(evidence_used), "evidence_valid": evidence_valid,
            "soft_items": len(rec["soft_handling"]),
            "clarifications": len(rec["clarifications"]),
        })

    fields = list(rows[0].keys())
    with (P32 / "evaluation_llm_96.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    summary = summarize(tasks, baseline, per_task)
    write_json(P32 / "summary_llm_96.json", summary)
    print(json.dumps(summary["headline"], ensure_ascii=False, indent=1))


def summarize(tasks, baseline, per_task):
    ok = [r for r in per_task.values() if r["final"]]
    gate_counts = Counter(r["final"]["gate_status"] for r in ok)
    self_counts = Counter(r["final"]["self_status"] for r in ok)
    rule_counts = Counter(baseline[u]["status"] for u in per_task)

    def rate(num, den):
        return round(num / den, 3) if den else None

    by_level = {}
    for lv in ("easy", "hard", "human"):
        sub = [r for r in ok if r["level"] == lv]
        by_level[lv] = {
            "n": len(sub),
            "rule_complete": sum(1 for r in sub if r["rule_status"] == "complete"),
            "gate_complete": sum(1 for r in sub if r["final"]["gate_status"] == "complete"),
            "self_complete": sum(1 for r in sub if r["final"]["self_status"] == "complete"),
            "gate_match_rule": sum(1 for r in sub if r["final"]["gate_status"] == r["rule_status"]),
            "overclaim": sum(1 for r in sub if r["final"]["overclaim"]),
            "underclaim": sum(1 for r in sub if r["final"]["underclaim"]),
            "gap_recall": round(statistics.mean(r["gaps"]["recall"] for r in sub), 3) if sub else None,
            "gap_precision": round(statistics.mean(r["gaps"]["precision"] for r in sub), 3) if sub else None,
            "static_ok": sum(1 for r in sub if r["static"] and r["static"]["verdict_canonical"] == "ok"),
        }
    by_scope = {}
    for sc in ("single_city", "chain"):
        sub = [r for r in ok if r["scope"] == sc]
        by_scope[sc] = {"n": len(sub),
                        "rule_complete": sum(1 for r in sub if r["rule_status"] == "complete"),
                        "gate_complete": sum(1 for r in sub if r["final"]["gate_status"] == "complete"),
                        "overclaim": sum(1 for r in sub if r["final"]["overclaim"])}
    by_city = {}
    for city in ("西安", "厦门", "宁波", "长沙", "青岛"):
        sub = [r for r in ok if city in r["cities"]]
        by_city[city] = {"n": len(sub),
                         "rule_complete": sum(1 for r in sub if r["rule_status"] == "complete"),
                         "gate_complete": sum(1 for r in sub if r["final"]["gate_status"] == "complete")}
    changed = sum(1 for r in ok if r["order_changed"])
    return {
        "headline": {
            "tasks": len(tasks),
            "with_final_output": len(ok),
            "rule": dict(rule_counts),
            "llm_gate": dict(gate_counts),
            "llm_self": dict(self_counts),
            "gate_same_as_rule": sum(1 for r in ok if r["final"]["gate_status"] == r["rule_status"]),
            "overclaim": sum(1 for r in ok if r["final"]["overclaim"]),
            "underclaim": sum(1 for r in ok if r["final"]["underclaim"]),
            "status_exact_match": sum(1 for r in ok if r["final"]["status_match"]),
            "order_changed": changed,
            "gap_recall_avg": round(statistics.mean(r["gaps"]["recall"] for r in ok), 3) if ok else None,
            "gap_precision_avg": round(statistics.mean(r["gaps"]["precision"] for r in ok), 3) if ok else None,
            "hallucinated_price_tasks": sum(1 for r in ok if r["hallucinated_prices"]),
            "static_order_ok": sum(1 for r in ok if r["order_ok"]),
            "static_lunch_ok": sum(1 for r in ok if r["lunch_ok"]),
        },
        "by_level": by_level, "by_scope": by_scope, "by_city": by_city,
        "gate_confusion": {a: {b: sum(1 for r in ok if r["rule_status"] == a and r["final"]["gate_status"] == b)
                               for b in ("complete", "blocked", "infeasible", "partial")}
                           for a in ("complete", "blocked", "infeasible")},
        "self_confusion": {a: {b: sum(1 for r in ok if r["final"]["gate_status"] == a and r["final"]["self_status"] == b)
                               for b in ("complete", "blocked", "infeasible", "partial")}
                           for a in ("complete", "blocked", "infeasible")},
    }


if __name__ == "__main__":
    main()
