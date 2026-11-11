"""P31 static stage: build draft plans and gap/request lists from frozen v4 data.

No network. Every request is explicit; nothing is fetched silently.

Output:
  results/p31_five_city_96/static/plans.json
  results/p31_five_city_96/static/requests.json
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

from p31_common import (CST, OUT, ROOT, entity_coord, haversine_km, hhmm_to_min, known,
                        load_tasks, min_to_hhmm, parse_window, read_json, write_json)

ADCODE = {"西安": "610100", "厦门": "350200", "宁波": "330200", "长沙": "430100", "青岛": "370200",
          "北京": "110000", "上海": "310000", "杭州": "330100", "广州": "440100",
          "成都": "510100", "武汉": "420100", "南京": "320100", "深圳": "440300"}
TRAVEL_KMH = 18.0
TRANSFER_BUFFER = 8
DEFAULT_VISIT_MIN = 90
LUNCH_MIN = 60
LUNCH_WINDOW = (11 * 60, 13 * 60 + 30)


def travel_estimate(a, b):
    """Minutes between two coord dicts; marked as estimate, never as evidence."""
    if not a or not b:
        return None
    km = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
    return max(12, int(round(km / TRAVEL_KMH * 60 + TRANSFER_BUFFER)))


def coord_of_cand(c):
    co = entity_coord(c)
    if not co:
        return None
    return {"lat": co[0], "lon": co[1], "system": co[2]}


def visit_minutes(c):
    d = c["data"]
    if known(d.get("recommendmintime")):
        v = float(d["recommendmintime"]) * 60
    else:
        v = DEFAULT_VISIT_MIN
    if known(d.get("recommendmaxtime")):
        v = min(v, float(d["recommendmaxtime"]) * 60)
    return int(max(45, min(v, 240)))


def window_of(c):
    d = c["data"]
    return parse_window(d.get("opentime"), d.get("endtime"))


def schedule_order(atts, restaurant, start_coord, start_min, deadline, *, lunch=True):
    """Try restaurant at every position; return the best timeline and its warnings."""
    seq = list(atts)
    options = []
    if lunch and restaurant:
        for pos in range(len(seq) + 1):
            options.append((seq[:pos], seq[pos:]))
    else:
        options.append((seq, []))
    best = None
    for before, after in options:
        r = _run_sequence(before, restaurant if lunch else None, after, start_coord, start_min, deadline)
        key = (len(r["reasons"]), r["end"])
        if best is None or key < best[0]:
            best = (key, r)
    return best[1]


def _run_sequence(before, restaurant, after, start_coord, start_min, deadline):
    timeline = []
    cur, cur_name, t = start_coord, "start", start_min
    travel_total = wait_total = 0
    hard, soft = [], []

    def move(to, to_name, label):
        nonlocal cur, cur_name, t, travel_total
        mins = travel_estimate(cur, to)
        if mins is None:
            hard.append(f"missing_coord:{label}")
            mins = 30
        timeline.append({"type": "travel", "from": cur_name, "to": to_name, "start": min_to_hhmm(t),
                         "end": min_to_hhmm(t + mins), "minutes": mins, "status": "estimate"})
        t += mins
        travel_total += mins
        cur, cur_name = to, to_name

    def visit(c, label):
        nonlocal t, wait_total
        win = window_of(c)
        dur = visit_minutes(c)
        arrive = t
        if win:
            o, cl = win
            if arrive < o:
                timeline.append({"type": "wait", "at": label, "start": min_to_hhmm(arrive),
                                 "end": min_to_hhmm(o), "minutes": o - arrive})
                wait_total += o - arrive
                t = o
                arrive = o
            if arrive + dur > cl:
                hard.append(f"closing_conflict:{label}")
                t = max(arrive, cl - dur)
        timeline.append({"type": "visit", "entity": label, "start": min_to_hhmm(t),
                         "end": min_to_hhmm(t + dur), "minutes": dur,
                         "opening_status": "known" if win else "unknown"})
        t += dur

    for a in before:
        move(coord_of_cand(a), a["name"], a["name"])
        visit(a, a["name"])
    if restaurant:
        move(coord_of_cand(restaurant), restaurant["name"], restaurant["name"])
        if t < LUNCH_WINDOW[0]:
            timeline.append({"type": "wait", "at": restaurant["name"], "start": min_to_hhmm(t),
                             "end": min_to_hhmm(LUNCH_WINDOW[0]), "minutes": LUNCH_WINDOW[0] - t})
            wait_total += LUNCH_WINDOW[0] - t
            t = LUNCH_WINDOW[0]
        if t > LUNCH_WINDOW[1]:
            soft.append(f"late_lunch:{min_to_hhmm(t)}")
        timeline.append({"type": "meal", "entity": restaurant["name"], "start": min_to_hhmm(t),
                         "end": min_to_hhmm(t + LUNCH_MIN), "minutes": LUNCH_MIN})
        t += LUNCH_MIN
    for a in after:
        move(coord_of_cand(a), a["name"], a["name"])
        visit(a, a["name"])
    move(start_coord, "start", "start")
    if t > deadline:
        soft.append(f"late_return:{min_to_hhmm(t)}")
    return {"timeline": timeline, "end": t, "travel_min": travel_total, "wait_min": wait_total,
            "feasible": not hard, "reasons": hard, "warnings": soft}


def choose_best_schedule(atts, restaurant, start_coord, start_min, deadline):
    best = None
    for perm in itertools.permutations(atts):
        r = schedule_order(list(perm), restaurant, start_coord, start_min, deadline,
                           lunch=bool(restaurant))
        if r["feasible"] and (best is None or r["end"] < best["end"]):
            best = r
    if best:
        best["order"] = [x["entity"] for x in best["timeline"] if x["type"] == "visit"]
        return best
    # keep the first permutation for diagnostics
    r = schedule_order(list(atts), restaurant, start_coord, start_min, deadline, lunch=bool(restaurant))
    r["order"] = [x["entity"] for x in r["timeline"] if x["type"] == "visit"]
    return r


def fields_required(task):
    req = []
    for c in task["candidates"]:
        if c["kind"] == "attraction":
            req += [(c["entity_id"], f) for f in ("price", "opentime", "endtime", "lat", "lon")]
        elif c["kind"] == "restaurant":
            req += [(c["entity_id"], f) for f in ("price", "opentime", "endtime")]
        elif c["kind"] == "accommodation":
            req += [(c["entity_id"], f) for f in ("price", "lat", "lon")]
        elif c["kind"] in ("train", "flight"):
            req += [(c["entity_id"], f) for f in ("From", "To", "BeginTime", "EndTime", "Duration", "Cost")]
    if task.get("old_city"):
        oa = task["old_city"]["attraction"]
        req += [(oa["entity_id"], f) for f in ("price", "opentime", "endtime")]
    return req


def missing_fields(task):
    gaps = []
    for c in task["candidates"]:
        d = c["data"]
        fields = {"attraction": ("price", "opentime", "endtime", "lat", "lon"),
                  "restaurant": ("price", "opentime", "endtime"),
                  "accommodation": ("price", "lat", "lon"),
                  "train": ("From", "To", "BeginTime", "EndTime", "Duration", "Cost"),
                  "flight": ("From", "To", "BeginTime", "EndTime", "Duration", "Cost")}.get(c["kind"], ())
        for f in fields:
            if not known(d.get(f)):
                gaps.append({"gap_id": f"{c['entity_id']}:{f}", "kind": "entity_field",
                             "entity_id": c["entity_id"], "entity": c["name"], "field": f,
                             "city": c["city"], "resolvable_by": "amap_place" if c["kind"] in ("attraction", "restaurant") else "static_only"})
    if task.get("old_city"):
        oa = task["old_city"]["attraction"]
        for f in ("price", "opentime", "endtime"):
            if not known(oa["data"].get(f)):
                gaps.append({"gap_id": f"{oa['entity_id']}:{f}", "kind": "entity_field",
                             "entity_id": oa["entity_id"], "entity": oa["name"], "field": f,
                             "city": task["old_city"]["city"], "resolvable_by": "static_only"})
    return gaps


def build_plan(task):
    people = task["people_number"]
    start = task["start"]
    cons = task["constraints"]
    start_min = hhmm_to_min(cons.get("start_time") or "09:00")
    deadline = hhmm_to_min(cons["window"][1])
    atts = [c for c in task["candidates"] if c["kind"] == "attraction"]
    rests = [c for c in task["candidates"] if c["kind"] == "restaurant"]
    hotels = [c for c in task["candidates"] if c["kind"] == "accommodation"]
    inter = task.get("intercity")
    start_coord = {"lat": start["position_wgs84"][0], "lon": start["position_wgs84"][1], "system": "WGS84"}

    days = []
    schedule = choose_best_schedule(atts, rests[0] if rests else None, start_coord, start_min, deadline)
    day1 = {"date": task["dates"][0], "city": task["city_sequence"][0],
            "start": {"name": start["name"], "time": min_to_hhmm(start_min)},
            "timeline": schedule["timeline"], "end": min_to_hhmm(schedule["end"]),
            "feasible": schedule["feasible"], "reasons": schedule["reasons"],
            "warnings": schedule.get("warnings", []),
            "travel_min": schedule["travel_min"], "wait_min": schedule["wait_min"]}
    days.append(day1)

    hotel = hotels[0] if hotels else None
    day2 = None
    if inter and len(task["city_sequence"]) > 1:
        oa = task["old_city"]["attraction"]
        dep = inter["data"].get("BeginTime")
        dep_min = hhmm_to_min(dep)
        arrive_min = None
        if dep_min is not None and known(inter["data"].get("Duration")):
            arrive_min = dep_min + int(float(inter["data"]["Duration"]) * 60)
        day2 = {"date": task["dates"][1], "city": task["city_sequence"][1],
                "departure": dep, "arrival": min_to_hhmm(arrive_min) if arrive_min else None,
                "intercity": inter["name"], "old_attraction": oa["name"],
                "feasible": None, "reasons": []}
        # old attraction visit after arrival + 60 min transfer
        if arrive_min is not None:
            visit_start = arrive_min + 45
            win = parse_window(oa["data"].get("opentime"), oa["data"].get("endtime"))
            dur = 60
            if win:
                o, cl = win
                visit_start = max(visit_start, o)
                if visit_start + dur > cl:
                    day2["reasons"].append("old_closing_conflict")
                    day2["feasible"] = False
                else:
                    day2["feasible"] = True
            else:
                day2["reasons"].append("old_hours_unknown")
            day2.update({"visit_start": min_to_hhmm(visit_start), "visit_end": min_to_hhmm(visit_start + dur)})
        else:
            day2["reasons"].append("intercity_arrival_unknown")
            day2["feasible"] = False
        days.append(day2)

    gaps = missing_fields(task)
    # weather gap per day/city
    for d in days:
        gaps.append({"gap_id": f"weather:{d['city']}:{d['date']}", "kind": "weather",
                     "city": d["city"], "date": d["date"], "resolvable_by": "amap_weather"})
    # route gaps
    legs = []
    prev = {"name": start["name"], "coord": start_coord}
    pending_dep = min_to_hhmm(start_min)
    for x in day1["timeline"]:
        if x["type"] == "travel":
            pending_dep = x["start"]
        elif x["type"] in ("visit", "meal"):
            c = next(c for c in task["candidates"] if c["name"] == x["entity"])
            co = coord_of_cand(c)
            legs.append({"from": prev["name"], "to": c["name"], "from_coord": prev["coord"], "to_coord": co,
                         "departure": pending_dep})
            prev = {"name": c["name"], "coord": co}
    legs.append({"from": prev["name"], "to": start["name"], "from_coord": prev["coord"], "to_coord": start_coord,
                 "departure": pending_dep})
    for i, lg in enumerate(legs):
        gaps.append({"gap_id": f"route:{task['uid']}:{i}", "kind": "route", "from": lg["from"], "to": lg["to"],
                     "from_coord": lg["from_coord"], "to_coord": lg["to_coord"], "date": task["dates"][0],
                     "departure_hint": lg["departure"], "resolvable_by": "amap_transit"})

    # requests: weather first, then routes (max 4), then place (max 2)
    requests = []
    for d in days:
        requests.append({"req_id": f"{task['uid']}-W-{d['city']}", "type": "weather",
                         "city": d["city"], "date": d["date"], "adcode": ADCODE[d["city"]]})
    for i, lg in enumerate(legs):
        if lg["from_coord"] and lg["to_coord"]:
            requests.append({"req_id": f"{task['uid']}-R-{i}", "type": "route", "from": lg["from"], "to": lg["to"],
                             "from_coord": lg["from_coord"], "to_coord": lg["to_coord"],
                             "city": task["city_sequence"][0], "date": task["dates"][0],
                             "departure": lg["departure"]})
    place_targets = []
    for c in task["candidates"]:
        if c["kind"] in ("attraction", "restaurant") and (
                not known(c["data"].get("opentime")) or not known(c["data"].get("lat"))):
            place_targets.append(c)
    for c in place_targets[:2]:
        requests.append({"req_id": f"{task['uid']}-P-{c['entity_id'][-6:]}", "type": "place",
                         "entity_id": c["entity_id"], "name": c["name"], "city": c["city"],
                         "adcode": ADCODE[c["city"]]})
    # cap at 6; keep weather and at most 4 routes
    weather = [r for r in requests if r["type"] == "weather"]
    all_routes = [r for r in requests if r["type"] == "route"][:5]
    places = [r for r in requests if r["type"] == "place"][:2]
    requests = weather + all_routes + places
    requests = requests[:8]

    required = fields_required(task)
    present = 0
    for (eid, f) in required:
        c = next((x for x in task["candidates"] if x["entity_id"] == eid), None)
        if c is None and task.get("old_city") and task["old_city"]["attraction"]["entity_id"] == eid:
            c = task["old_city"]["attraction"]
        if c is not None and known((c.get("data") or {}).get(f)):
            present += 1
    # static cost
    costs = []
    unknown_cost = []
    for c in task["candidates"]:
        d = c["data"]
        if c["kind"] == "attraction":
            if known(d.get("price")):
                costs.append(float(d["price"]) * people)
            else:
                unknown_cost.append(c["name"] + ":price")
        elif c["kind"] == "restaurant" and c in rests:
            if known(d.get("price")):
                costs.append(float(d["price"]) * people)
            else:
                unknown_cost.append(c["name"] + ":price")
        elif c["kind"] == "accommodation":
            if known(d.get("price")):
                costs.append(float(d["price"]))
            else:
                unknown_cost.append(c["name"] + ":price")
        elif c["kind"] in ("train", "flight"):
            if known(d.get("Cost")):
                costs.append(float(d["Cost"]) * people)
            else:
                unknown_cost.append(c["name"] + ":Cost")
    known_cost = round(sum(costs), 1)
    transit_est = 5 * people * len(legs)
    budget_ok = (not unknown_cost) and (known_cost + transit_est <= task["static_estimate"]["budget_limit"])

    return {
        "uid": task["uid"], "level": task["level"], "people": people,
        "days": days, "hotel": hotel["name"] if hotel else None,
        "intercity": inter["name"] if inter else None,
        "gaps": gaps,
        "requests": requests,
        "static": {
            "required_fields": len(required), "present_fields": present,
            "closure": round(present / len(required), 4) if required else 1.0,
            "missing_field_gaps": len([g for g in gaps if g["kind"] == "entity_field"]),
            "route_gaps": len([g for g in gaps if g["kind"] == "route"]),
            "weather_gaps": len([g for g in gaps if g["kind"] == "weather"]),
            "schedule_ok": bool(schedule["feasible"]) and all(d.get("feasible") is not False for d in days),
            "known_cost": known_cost, "transit_estimate": transit_est,
            "budget_limit": task["static_estimate"]["budget_limit"],
            "unknown_cost_items": unknown_cost, "budget_ok_static": budget_ok,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default=None, choices=["easy", "hard", "human"])
    a = ap.parse_args()
    tasks = load_tasks(a.level)
    plans = [build_plan(t) for t in tasks]
    OUT.joinpath("static").mkdir(parents=True, exist_ok=True)
    name = a.level or "all_96"
    write_json(OUT / "static" / f"plans_{name}.json", plans)
    write_json(OUT / "static" / f"requests_{name}.json",
               [{"uid": p["uid"], "requests": p["requests"]} for p in plans])
    print(json.dumps({"plans": len(plans), "requests": sum(len(p["requests"]) for p in plans),
                      "avg_requests": round(sum(len(p["requests"]) for p in plans) / len(plans), 2),
                      "schedule_ok": sum(p["static"]["schedule_ok"] for p in plans),
                      "closure_avg": round(sum(p["static"]["closure"] for p in plans) / len(plans), 3)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
