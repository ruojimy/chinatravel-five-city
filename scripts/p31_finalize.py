"""P31 final stage: apply retrieved evidence, re-plan, and score 96 tasks.

No network. Reads static plans + saved Amap responses.

Output:
  results/p31_five_city_96/final/plans.json
  results/p31_five_city_96/evaluation.csv
  results/p31_five_city_96/summary.json
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from p31_common import (OUT, entity_coord, haversine_km, hhmm_to_min, known, load_tasks,
                        min_to_hhmm, parse_window, read_json, write_json)
from p31_static import (DEFAULT_VISIT_MIN, LUNCH_MIN, LUNCH_WINDOW, TRAVEL_KMH, TRANSFER_BUFFER,
                        coord_of_cand, travel_estimate, visit_minutes, window_of)

RAIN_WORDS = ("雨", "雪", "雷", "storm", "rain", "snow")


def load_responses():
    base = OUT / "retrieval/responses"
    out = {}
    if not base.exists():
        return out
    for f in base.rglob("*.json"):
        try:
            d = read_json(f)
        except Exception:
            continue
        out[(d["uid"], d["req_id"])] = d
    return out


def load_details():
    base = OUT / "retrieval/details"
    out = {}
    if not base.exists():
        return out
    for f in base.rglob("*.json"):
        try:
            d = read_json(f)
        except Exception:
            continue
        out[(d["uid"], d["entity_id"])] = d
    return out


def place_override(resp):
    p = resp.get("parsed") or {}
    if not p.get("ok"):
        return None
    return {"location_gcj02": p.get("location_gcj02"), "opentime_windows": p.get("opentime_windows"),
            "opentime_text": p.get("opentime_text"), "name": p.get("name")}


def route_lookup(responses, uid, frm, to):
    for (u, rid), d in responses.items():
        if u != uid or d["type"] != "route":
            continue
        r = d["request"]
        if r.get("from") == frm and r.get("to") == to:
            p = d["parsed"]
            if p.get("ok"):
                return {"duration": p.get("duration_min"), "fare": p.get("fare"), "modes": p.get("modes"),
                        "req_id": rid, "retrieved_at": d["retrieved_at"]}
            return {"duration": None, "fare": None, "modes": [], "req_id": rid, "reason": p.get("reason")}
    return None


def build_final(task, plan, responses, details):
    people = task["people_number"]
    cons = task["constraints"]
    start_min = hhmm_to_min(cons.get("start_time") or "09:00")
    deadline = hhmm_to_min(cons["window"][1])
    start = task["start"]
    start_coord = {"lat": start["position_wgs84"][0], "lon": start["position_wgs84"][1], "system": "WGS84"}
    cand_by_id = {c["entity_id"]: c for c in task["candidates"]}
    cand_by_name = {c["name"]: c for c in task["candidates"]}

    # place overrides keyed by entity id
    overrides = {}
    for (uid, rid), d in responses.items():
        if uid != task["uid"] or d["type"] != "place":
            continue
        o = place_override(d)
        if o:
            overrides[d["request"]["entity_id"]] = o

    # rebuild day1 in the static order
    order = [x["entity"] for x in plan["days"][0]["timeline"] if x["type"] in ("visit", "meal")]
    timeline = []
    cur_name, cur_coord, t = start["name"], start_coord, start_min
    travel_total = wait_total = 0
    legs = []
    reasons = []
    warnings = []

    def coord_for(name):
        c = cand_by_name.get(name)
        if not c:
            return None
        o = overrides.get(c["entity_id"])
        if o and o.get("location_gcj02"):
            lat, lon = o["location_gcj02"]
            return {"lat": lat, "lon": lon, "system": "GCJ02"}
        return coord_of_cand(c)

    def window_for(name):
        c = cand_by_name.get(name)
        o = overrides.get(c["entity_id"]) if c else None
        if o and o.get("opentime_windows"):
            return o["opentime_windows"]
        if c:
            det = details.get((task["uid"], c["entity_id"]))
            if det and det.get("hours_window"):
                return tuple(det["hours_window"])
        return window_of(c) if c else None

    def move(to_name, label):
        nonlocal cur_name, cur_coord, t, travel_total
        to_coord = coord_for(to_name)
        dyn = route_lookup(responses, task["uid"], cur_name, to_name)
        mins = None
        status = "estimate"
        fare = None
        if dyn and dyn.get("duration"):
            mins = dyn["duration"]
            fare = dyn.get("fare")
            status = "dynamic"
        if mins is None and dyn and dyn.get("reason") == "no_transit_route" and cur_coord and to_coord:
            km = haversine_km(cur_coord["lat"], cur_coord["lon"], to_coord["lat"], to_coord["lon"])
            if km <= 1.5:
                mins = km / 4.5 * 60
                fare = 0.0
                status = "walk"
        if mins is None:
            mins = travel_estimate(cur_coord, to_coord)
            if mins is None:
                reasons.append(f"missing_coord:{label}")
                mins = 30
        mins = int(round(mins))
        timeline.append({"type": "travel", "from": cur_name, "to": to_name, "start": min_to_hhmm(t),
                         "end": min_to_hhmm(t + mins), "minutes": mins, "status": status,
                         "fare": fare, "req_id": dyn.get("req_id") if dyn else None})
        legs.append({"from": cur_name, "to": to_name, "minutes": mins, "status": status,
                     "fare": fare, "req_id": dyn.get("req_id") if dyn else None})
        t += mins
        travel_total += mins
        cur_name, cur_coord = to_name, to_coord

    first = True
    for name in order:
        c = cand_by_name.get(name)
        if not c:
            continue
        move(name, name)
        win = window_for(name)
        if c["kind"] == "restaurant":
            if t < LUNCH_WINDOW[0]:
                timeline.append({"type": "wait", "at": name, "start": min_to_hhmm(t),
                                 "end": min_to_hhmm(LUNCH_WINDOW[0]), "minutes": LUNCH_WINDOW[0] - t})
                wait_total += LUNCH_WINDOW[0] - t
                t = LUNCH_WINDOW[0]
            if t > LUNCH_WINDOW[1]:
                warnings.append(f"late_lunch:{min_to_hhmm(t)}")
            timeline.append({"type": "meal", "entity": name, "start": min_to_hhmm(t),
                             "end": min_to_hhmm(t + LUNCH_MIN), "minutes": LUNCH_MIN,
                             "opening_status": "known" if win else "unknown"})
            t += LUNCH_MIN
        else:
            dur = visit_minutes(c)
            arrive = t
            if win:
                o, cl = win
                if arrive < o:
                    timeline.append({"type": "wait", "at": name, "start": min_to_hhmm(arrive),
                                     "end": min_to_hhmm(o), "minutes": o - arrive})
                    wait_total += o - arrive
                    t = o
                    arrive = o
                if arrive + dur > cl:
                    reasons.append(f"closing_conflict:{name}")
                    t = max(arrive, cl - dur)
            timeline.append({"type": "visit", "entity": name, "start": min_to_hhmm(t),
                             "end": min_to_hhmm(t + dur), "minutes": dur,
                             "opening_status": "known" if win else "unknown"})
            t += dur
    move(start["name"], start["name"])
    if t > deadline:
        reasons.append(f"late_return:{min_to_hhmm(t)}")
    end = t

    # costs
    ticket = meal = hotel = inter = 0.0
    unknown_price = []
    for c in task["candidates"]:
        d = c["data"]
        if c["kind"] == "attraction":
            if known(d.get("price")):
                ticket += float(d["price"]) * people
            else:
                unknown_price.append(c["name"] + ":price")
        elif c["kind"] == "restaurant" and c["name"] in order:
            if known(d.get("price")):
                meal += float(d["price"]) * people
            else:
                unknown_price.append(c["name"] + ":price")
        elif c["kind"] == "accommodation":
            if known(d.get("price")):
                hotel += float(d["price"])
            else:
                unknown_price.append(c["name"] + ":price")
        elif c["kind"] in ("train", "flight"):
            if known(d.get("Cost")):
                inter += float(d["Cost"]) * people
            else:
                unknown_price.append(c["name"] + ":Cost")
    fares = sum((lg.get("fare") or 0) * people for lg in legs if lg.get("fare") is not None)
    total = ticket + meal + hotel + inter + fares
    budget_limit = task["static_estimate"]["budget_limit"]
    budget_ok = (not unknown_price) and total <= budget_limit

    # opening check
    att_visits = [x for x in timeline if x["type"] == "visit"]
    opening_unknown = [x["entity"] for x in att_visits if x.get("opening_status") != "known"]
    opening_conflict = [r for r in reasons if r.startswith("closing_conflict")]

    # route coverage
    route_legs = [lg for lg in legs]
    route_cov = sum(1 for lg in route_legs if lg["status"] in ("dynamic", "walk")) / len(route_legs) if route_legs else 1.0

    # weather
    weather_days = []
    for d in plan["days"]:
        rid = f"{task['uid']}-W-{d['city']}"
        r = responses.get((task["uid"], rid))
        v = (r or {}).get("parsed", {}).get("value") if r else None
        weather_days.append({"city": d["city"], "date": d["date"], "value": v,
                             "ok": bool(v), "rid": rid})
    weather_ok = sum(1 for w in weather_days if w["ok"]) / len(weather_days) if weather_days else 1.0
    rain = any(any(w in str((x["value"] or {}).get("dayweather", "")) for w in RAIN_WORDS) for x in weather_days)

    # chain day2
    intercity_ok = None
    day2 = None
    if len(plan["days"]) > 1:
        d2 = plan["days"][1]
        leg = None
        for c in task["candidates"]:
            if c["kind"] in ("train", "flight"):
                leg = c
        fields_ok = all(known(leg["data"].get(f)) for f in ("From", "To", "BeginTime", "EndTime", "Duration", "Cost"))
        arrive = None
        if known(leg["data"].get("BeginTime")) and known(leg["data"].get("Duration")):
            arrive = hhmm_to_min(leg["data"]["BeginTime"]) + int(float(leg["data"]["Duration"]) * 60)
        old = task["old_city"]["attraction"]
        win = parse_window(old["data"].get("opentime"), old["data"].get("endtime"))
        visit_start = (arrive + 45) if arrive is not None else None
        old_ok = False
        if win and visit_start is not None:
            o, cl = win
            visit_start = max(visit_start, o)
            old_ok = visit_start + 60 <= cl
        intercity_ok = bool(fields_ok and arrive is not None and old_ok)
        day2 = {"departure": leg["data"].get("BeginTime"), "arrival": min_to_hhmm(arrive) if arrive else None,
                "old_attraction": old["name"], "old_open": [old["data"].get("opentime"), old["data"].get("endtime")],
                "old_visit_start": min_to_hhmm(visit_start) if visit_start else None,
                "feasible": intercity_ok}

    time_ok = not any(r.startswith("late_return") for r in reasons)
    if opening_unknown or unknown_price:
        status = "blocked"
    elif not time_ok or intercity_ok is False or not budget_ok:
        status = "infeasible"
    elif route_cov >= 1.0 and weather_ok >= 1.0:
        status = "complete"
    else:
        status = "partial"

    return {
        "uid": task["uid"], "level": task["level"], "people": people,
        "dates": task["dates"], "city_sequence": task["city_sequence"],
        "timeline": timeline, "end": min_to_hhmm(end), "deadline": min_to_hhmm(deadline),
        "legs": legs, "day2": day2,
        "cost": {"ticket": round(ticket, 1), "meal": round(meal, 1), "hotel": round(hotel, 1),
                 "intercity": round(inter, 1), "transit_fares": round(fares, 1), "total": round(total, 1),
                 "limit": budget_limit, "unknown": unknown_price, "budget_ok": budget_ok},
        "weather": weather_days, "rain": rain,
        "checks": {"opening_known": not opening_unknown, "opening_unknown": opening_unknown,
                   "opening_conflict": opening_conflict, "route_coverage": round(route_cov, 3),
                   "weather_coverage": round(weather_ok, 3), "budget_ok": budget_ok,
                   "time_ok": time_ok, "intercity_ok": intercity_ok},
        "reasons": reasons, "warnings": warnings,
        "status": status,
        "static": plan["static"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", choices=["easy", "hard", "human"])
    a = ap.parse_args()
    tasks = load_tasks(a.level)
    plans = read_json(OUT / "static" / (f"plans_{a.level}.json" if a.level else "plans_all_96.json"))
    plan_by = {p["uid"]: p for p in plans}
    responses = load_responses()
    details = load_details()
    finals = [build_final(t, plan_by[t["uid"]], responses, details) for t in tasks]
    OUT.joinpath("final").mkdir(parents=True, exist_ok=True)
    name = a.level or "all_96"
    write_json(OUT / "final" / f"plans_{name}.json", finals)

    rows = []
    for f in finals:
        rows.append({
            "uid": f["uid"], "level": f["level"], "scope": "chain" if f["day2"] else "single_city",
            "cities": "+".join(f["city_sequence"]),
            "static_closure": f["static"]["closure"],
            "static_schedule_ok": f["static"]["schedule_ok"],
            "static_budget_ok": f["static"]["budget_ok_static"],
            "route_coverage": f["checks"]["route_coverage"],
            "weather_coverage": f["checks"]["weather_coverage"],
            "opening_known": f["checks"]["opening_known"],
            "budget_ok": f["checks"]["budget_ok"],
            "time_ok": f["checks"]["time_ok"],
            "intercity_ok": f["checks"]["intercity_ok"],
            "total_cost": f["cost"]["total"], "budget_limit": f["cost"]["limit"],
            "status": f["status"],
            "unknown_price_items": ";".join(f["cost"]["unknown"]),
            "opening_unknown": ";".join(f["checks"]["opening_unknown"]),
        })
    csv_path = OUT / f"evaluation_{name}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

    def agg(rs):
        by = {}
        for lv in ("easy", "hard", "human"):
            sub = [r for r in rs if r["level"] == lv]
            if not sub:
                continue
            by[lv] = {
                "tasks": len(sub),
                "static_closure_avg": round(statistics.mean(r["static_closure"] for r in sub), 3),
                "static_schedule_ok": sum(1 for r in sub if r["static_schedule_ok"]),
                "route_cov_avg": round(statistics.mean(r["route_coverage"] for r in sub), 3),
                "weather_cov_avg": round(statistics.mean(r["weather_coverage"] for r in sub), 3),
                "opening_known": sum(1 for r in sub if r["opening_known"]),
                "budget_ok": sum(1 for r in sub if r["budget_ok"]),
                "time_ok": sum(1 for r in sub if r["time_ok"]),
                "status": dict(Counter(r["status"] for r in sub)),
            }
        return by

    summary = {
        "tasks": len(finals),
        "levels": agg(rows),
        "status_total": dict(Counter(r["status"] for r in rows)),
        "scope_total": dict(Counter(r["scope"] for r in rows)),
        "status_by_scope": {s: dict(Counter(r["status"] for r in rows if r["scope"] == s))
                            for s in ("single_city", "chain")},
        "responses": len(responses),
        "detail_calls": len(details),
        "details_with_hours": sum(1 for d in details.values() if d.get("hours_window")),
        "requests_planned": sum(len(p["requests"]) for p in plans),
        "by_city": {},
    }
    for city in ("西安", "厦门", "宁波", "长沙", "青岛"):
        sub = [r for r in rows if city in r["cities"]]
        if sub:
            summary["by_city"][city] = {"tasks": len(sub),
                                        "status": dict(Counter(r["status"] for r in sub)),
                                        "closure": round(statistics.mean(r["static_closure"] for r in sub), 3)}
    write_json(OUT / f"summary_{name}.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=1)[:2500])


if __name__ == "__main__":
    main()
