"""P31: build a 96-task layered schema (easy/hard/human) for the five new cities.

Tasks are grounded in the frozen v4 five-city dataset plus the old ChinaTravel
catalog (for the old-city side of chain tasks). No network here.

Output: results/p31_five_city_96/tasks/{easy,hard,human,all_96}.json + protocol.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "data/five_city_reference_v4_20261026/catalog.sqlite3"
OLD = ROOT / "data/catalog_v1_1_20261022/catalog.sqlite3"
OUT = ROOT / "results/p31_five_city_96"

CITY_ADCODE = {"西安": "610100", "厦门": "350200", "宁波": "330200", "长沙": "430100", "青岛": "370200"}
OLD_ADCODE = {"北京": "110000", "上海": "310000", "杭州": "330100", "广州": "440100",
              "成都": "510100", "武汉": "420100", "南京": "320100", "深圳": "440300"}
STATIONS = {
    "西安": ["西安北站", "西安站"],
    "厦门": ["厦门北站", "厦门站"],
    "宁波": ["宁波站"],
    "长沙": ["长沙南站", "长沙站"],
    "青岛": ["青岛北站", "青岛站"],
}

def load_v4():
    db = sqlite3.connect(str(V4))
    rows = [json.loads(p) for (p,) in db.execute("select payload from records")]
    by = {}
    for r in rows:
        by.setdefault((r["city"], r["kind"]), []).append(r)
    return by

def load_old():
    db = sqlite3.connect(str(OLD))
    out = {}
    for city in OLD_ADCODE:
        for kind in ("attraction", "accommodation"):
            rows = []
            for (p,) in db.execute("select payload from records where city=? and kind=? and lang='zh' limit 600", (city, kind)):
                rows.append(json.loads(p))
            out[(city, kind)] = rows
    return out

def known(v):
    return v is not None and v != ""

def data_complete(r, fields):
    return all(known(r["data"].get(f)) for f in fields)

KIND_FIELDS = {
    "attraction": ("id", "name", "type", "lat", "lon", "opentime", "endtime", "price",
                   "recommendmintime", "recommendmaxtime"),
    "restaurant": ("id", "name", "lat", "lon", "price", "cuisine", "opentime", "endtime", "recommendedfood"),
    "accommodation": ("id", "name", "hotelname_en", "featurehoteltype", "lat", "lon", "price", "numbed"),
    "poi": ("name", "position"),
    "train": ("TrainID", "TrainType", "From", "To", "BeginTime", "EndTime", "Duration", "Cost"),
    "flight": ("FlightID", "From", "To", "BeginTime", "EndTime", "Duration", "Cost"),
}


def slim(r, *, with_tags=True):
    d = dict(r)
    fields = KIND_FIELDS.get(r.get("kind"), ())
    return {
        "entity_id": r.get("record_id"),
        "name": r.get("name"),
        "city": r.get("city"),
        "kind": r.get("kind"),
        "data": r.get("data"),
        "coordinate_system": r.get("coordinate_system"),
        "source_url": r.get("source_url"),
        "entity_verified": r.get("entity_verified"),
        "missing_fields": [f for f in fields if not known((r.get("data") or {}).get(f))],
        "tags": [{k: t.get(k) for k in ("tag", "value", "status")} for t in (r.get("tags") or [])][:6] if with_tags else [],
    }

def station_candidate(by, city, idx=0):
    names = STATIONS[city]
    pois = [r for r in by[(city, "poi")] if r["name"] in names]
    pois.sort(key=lambda r: names.index(r["name"]) if r["name"] in names else 9)
    p = pois[idx % len(pois)] if pois else None
    if not p:
        return None
    lat, lon = p["data"]["position"]
    return {"name": p["name"], "city": city, "position_wgs84": [lat, lon],
            "coordinate_system": p.get("coordinate_system"), "entity_id": p.get("record_id")}

def choose_attractions(by, city, n, *, complete=True, start=0, station=None):
    pool = []
    for r in by[(city, "attraction")]:
        d = r["data"]
        if not (known(d.get("lat")) and known(d.get("lon"))):
            continue
        full = data_complete(r, ("price", "opentime", "endtime", "lat", "lon"))
        if full == complete:
            pool.append(r)
    pool.sort(key=lambda r: r["name"])
    if not pool:
        pool = sorted([r for r in by[(city, "attraction")] if known(r["data"].get("lat"))], key=lambda r: r["name"])

    def dist(a, b):
        da, db = a["data"], b["data"]
        return ((float(da["lat"]) - float(db["lat"])) ** 2 + (float(da["lon"]) - float(db["lon"])) ** 2) ** 0.5

    st = station["position_wgs84"] if station else None
    def station_dist(r):
        if not st:
            return 0.0
        return ((float(r["data"]["lat"]) - st[0]) ** 2 + (float(r["data"]["lon"]) - st[1]) ** 2) ** 0.5

    seeds = sorted(pool, key=lambda r: (station_dist(r), r["name"]))
    for attempt in range(min(len(seeds), 10)):
        seed = seeds[(start + attempt) % len(seeds)]
        if station_dist(seed) > 0.35:  # roughly >35 km from the station
            continue
        picked = [seed]
        while len(picked) < n:
            remaining = [p for p in pool if p not in picked]
            if not remaining:
                break
            nxt = min(remaining, key=lambda p: min(dist(p, q) for q in picked))
            if min(dist(nxt, q) for q in picked) > 0.30:  # ~30 km cluster cap
                break
            picked.append(nxt)
        if len(picked) == n:
            return picked
    picked = []
    i = start
    while len(picked) < n:
        picked.append(pool[i % len(pool)])
        i += 1
    return picked

def choose_restaurant(by, city, start=0, require_price=False):
    rs = [r for r in by[(city, "restaurant")] if (known(r["data"].get("price")) or not require_price)]
    rs.sort(key=lambda r: (not (known(r["data"].get("lat")) and known(r["data"].get("lon"))),
                           not known(r["data"].get("price")), r["name"]))
    return rs[start % len(rs)] if rs else None

def choose_hotel(by, city, start=0):
    hs = [r for r in by[(city, "accommodation")]]
    hs.sort(key=lambda r: r["name"])
    # prefer price + coords
    hs.sort(key=lambda r: (not known(r["data"].get("price")), not known(r["data"].get("lat"))))
    return hs[start % len(hs)] if hs else None

def intercity_leg(by, city, target_kind, prefer=None):
    rows = [r for r in by[(city, target_kind)] if known(r["data"].get("Cost"))]
    if prefer:
        rows = [r for r in rows if prefer in str(r["data"].get("To", ""))] or rows
    def score(r):
        t = str(r["data"].get("BeginTime") or "99:99")
        return (0 if "08:00" <= t <= "12:00" else 1, t, r["name"])
    rows.sort(key=score)
    return rows[0] if rows else None

OLD_PICKS = {
    "北京": ["故宫博物院", "天坛公园", "颐和园", "八达岭长城"],
    "上海": ["外滩", "东方明珠", "上海博物馆", "豫园"],
    "杭州": ["西湖风景名胜区", "灵隐寺", "西溪湿地"],
    "广州": ["广州塔", "陈家祠", "长隆野生动物世界"],
    "成都": ["成都大熊猫繁育研究基地", "武侯祠", "宽窄巷子"],
    "武汉": ["黄鹤楼", "湖北省博物馆"],
    "南京": ["夫子庙", "中山陵"],
    "深圳": ["世界之窗", "深圳博物馆"],
}

def old_attraction(old, city, index=0):
    names = OLD_PICKS.get(city, [])
    rows = old[(city, "attraction")]
    by_name = {r["name"]: r for r in rows}
    ordered = [by_name[n] for n in names if n in by_name]
    if not ordered:
        ordered = [r for r in rows if known(r["data"].get("price")) and known(r["data"].get("opentime"))
                   and known(r["data"].get("endtime"))]
        ordered.sort(key=lambda r: r["name"])

    def close_min(r):
        try:
            h, m = str(r["data"].get("endtime")).split(":")[:2]
            v = int(h) * 60 + int(m)
            return v if v > 0 else 24 * 60
        except (ValueError, AttributeError):
            return 0

    late = [r for r in ordered if close_min(r) >= 18 * 60] or ordered
    return late[index % len(late)]

def money(x):
    return None if not known(x) else float(x)

def budget_for(attractions, restaurant=None, hotel=None, leg=None, people=2, transport=120):
    total = 0.0
    unknown = []
    for a in attractions:
        p = money(a["data"].get("price"))
        if p is None:
            unknown.append(a["name"] + ":price")
        else:
            total += p * people
    if restaurant:
        p = money(restaurant["data"].get("price"))
        if p is None:
            unknown.append(restaurant["name"] + ":price")
        else:
            total += p * people
    if hotel:
        p = money(hotel["data"].get("price"))
        if p is None:
            unknown.append(hotel["name"] + ":price")
        else:
            total += p
    if leg:
        p = money(leg["data"].get("Cost"))
        if p is None:
            unknown.append(leg["name"] + ":Cost")
        else:
            total += p * people
    return round(total + transport, -1), round(total, 1), unknown

def task_doc(uid, level, text, city_seq, dates, people, candidates, *, start, constraints,
             intercity=None, old_city=None, budget=0, estimated=0, unknown=None, extra=None):
    doc = {
        "schema_version": "p31-five-city-v1",
        "uid": uid,
        "level": level,
        "nature_language": text,
        "people_number": people,
        "city_sequence": city_seq,
        "dates": dates,
        "start": start,
        "candidates": [slim(c) for c in candidates],
        "constraints": constraints,
        "retrieval_budget": 8,
        "static_estimate": {"budget_limit": budget, "known_cost": estimated, "unknown_price_items": unknown or []},
    }
    if intercity:
        doc["intercity"] = slim(intercity)
    if old_city:
        doc["old_city"] = old_city
    if extra:
        doc.update(extra)
    return doc

def build_easy(by):
    plan = {"西安": 7, "厦门": 6, "宁波": 6, "长沙": 7, "青岛": 6}
    tasks = []
    n = 1
    for city, count in plan.items():
        for k in range(count):
            st = station_candidate(by, city, k)
            atts = choose_attractions(by, city, 2, complete=True, start=k, station=st)
            budget, est, unknown = budget_for(atts, None, None, None, 2)
            names = "、".join(a["name"] for a in atts)
            text = (f"2026-10-28，两人从{st['name']}出发，想去{city}的{names}，坐地铁或公交，"
                    f"当天 18:00 前回到{st['name']}。请核对开放时间、两人门票、当天天气和往返路上要多久，"
                    f"预算 {int(budget)} 元。信息缺失或过期就说明要查什么。")
            uid = f"E{n:02d}"
            tasks.append(task_doc(uid, "easy", text, [city], ["2026-10-28"], 2, atts,
                                  start=st, constraints={"window": ["09:00", "18:00"], "start_time": "09:00", "mode": "public_transit",
                                                         "budget": budget, "return_to_start": True},
                                  budget=budget, estimated=est, unknown=unknown))
            n += 1
    return tasks

def build_hard(by, old):
    tasks = []
    n = 1
    # 20 single-city tight tasks: 4 per city
    for city in CITY_ADCODE:
        for k in range(4):
            st = station_candidate(by, city, k)
            atts = choose_attractions(by, city, 3, complete=(k % 2 == 0), start=k + 1, station=st)
            rest = choose_restaurant(by, city, start=k)
            budget, est, unknown = budget_for(atts, rest, None, None, 2)
            names = "、".join(a["name"] for a in atts)
            text = (f"2026-10-29，两人从{st['name']}出发，一天内看{city}的{names}，午饭在{rest['name']}，"
                    f"全程地铁公交，18:30 前回到{st['name']}。总预算 {int(budget)} 元（含门票、午饭、交通）。"
                    f"请给出顺序和时段，核对开放时间与午饭营业时间；来源冲突或缺失不要猜。")
            uid = f"D{n:02d}"
            tasks.append(task_doc(uid, "hard", text, [city], ["2026-10-29"], 2, atts + [rest],
                                  start=st, constraints={"window": ["09:00", "18:30"], "start_time": "09:00", "mode": "public_transit",
                                                         "budget": budget, "meals": ["lunch"]},
                                  budget=budget, estimated=est, unknown=unknown))
            n += 1
    # 12 chains: new city day1, old city day2
    chains = [
        ("西安", "北京", "train", "北京"), ("西安", "上海", "train", "上海"),
        ("厦门", "上海", "train", "上海"), ("厦门", "杭州", "train", "杭州"),
        ("宁波", "上海", "train", "上海"), ("宁波", "杭州", "train", "杭州"),
        ("长沙", "北京", "flight", "北京"), ("长沙", "上海", "flight", "上海"),
        ("青岛", "北京", "train", "北京"), ("青岛", "上海", "train", "上海"),
        ("西安", "北京", "flight", "北京"), ("厦门", "上海", "flight", "上海"),
    ]
    for city, old_city, kind, pref in chains:
        k = n - 21
        st = station_candidate(by, city, k)
        atts = choose_attractions(by, city, 2, complete=True, start=k, station=st)
        hotel = choose_hotel(by, city, k)
        leg = intercity_leg(by, city, kind, pref)
        oa = old_attraction(old, old_city, k)
        budget, est, unknown = budget_for(atts, None, hotel, leg, 2)
        text = (f"{city}两天一夜：2026-10-28 上午两人从{st['name']}出发，看{atts[0]['name']}和{atts[1]['name']}，"
                f"住{hotel['name']}；10-29 早上坐 {leg['name']}（{leg['data'].get('BeginTime')} 出发）去{old_city}，"
                f"下午看{oa['name']}。请核对车次/航班时刻、酒店价格、两侧开放时间与天气，"
                f"总预算 {int(budget)} 元。城际与市内交通都要给依据。")
        uid = f"D{n:02d}"
        tasks.append(task_doc(uid, "hard", text, [city, old_city], ["2026-10-28", "2026-10-29"], 2,
                              atts + [hotel, leg],
                              start=st, constraints={"window": ["08:00", "20:00"], "start_time": "09:00", "mode": "public_transit",
                                                     "budget": budget, "overnight": True, "chain": True},
                              intercity=leg, old_city={"city": old_city, "attraction": slim(oa)},
                              budget=budget, estimated=est, unknown=unknown))
        n += 1
    return tasks

def build_human(by, old):
    tasks = []
    n = 1
    counts = {"西安": 5, "厦门": 5, "宁波": 4, "长沙": 5, "青岛": 5}
    templates = [
        "带爸妈去{city}，不想太赶，10 点从{st}出发，想看{a}和{b}，晚上想吃点清淡的，预算 {budget} 左右。",
        "我们两个人 {date} 在{city}，预算 {budget} 左右，想去{a}和{b}，怕排队，怎么安排不赶？",
        "去{city}出差，下午 1 点从{st}出发，只看一个景点，6 点前回站，预算 {budget}。",
        "和朋友去{city}，想拍照，{a}和{b}选一个，地铁方便，预算 {budget}。",
        "带孩子去{city}，10 点出发，下午 4 点回酒店，室内为主，预算 {budget}。",
    ]
    for city, count in counts.items():
        for k in range(count):
            n_atts = 1 if k in (2, 3, 4) else 2
            st = station_candidate(by, city, k)
            atts = choose_attractions(by, city, n_atts, complete=(k % 3 != 1), start=k + 2, station=st)
            rest = choose_restaurant(by, city, start=k) if k == 0 else None
            budget, est, unknown = budget_for(atts, rest, None, None, 2)
            budget = int(round(budget * 1.1, -1))
            names = [a["name"] for a in atts] + [atts[-1]["name"]] * max(0, 2 - len(atts))
            text = templates[k].format(city=city, st=st["name"], a=names[0], b=names[1],
                                       budget=budget, date="10-29")
            cons = {"window": ["09:00", "18:00"], "start_time": ("13:00" if k == 2 else "10:00"),
                    "mode": "public_transit", "budget": budget,
                    "soft": ["slow_pace", "elderly" if k == 0 else ("efficient" if k == 1 else "half_day"),
                             "rain_backup" if k == 4 else "normal"]}
            uid = f"N{n:02d}"
            tasks.append(task_doc(uid, "human", text, [city], ["2026-10-29"], 2,
                                  atts + ([rest] if rest else []),
                                  start=st, constraints=cons, budget=budget, estimated=est, unknown=unknown))
            n += 1
    # 8 chains natural
    chains = [("西安", "北京", "train", "北京"), ("西安", "上海", "flight", "上海"),
              ("厦门", "杭州", "train", "杭州"), ("宁波", "上海", "train", "上海"),
              ("长沙", "北京", "flight", "北京"), ("长沙", "上海", "flight", "上海"),
              ("青岛", "北京", "train", "北京"), ("青岛", "上海", "train", "上海")]
    for i, (city, old_city, kind, pref) in enumerate(chains):
        k = n
        st = station_candidate(by, city, k)
        atts = choose_attractions(by, city, 1, complete=True, start=k, station=st)
        hotel = choose_hotel(by, city, k)
        leg = intercity_leg(by, city, kind, pref)
        oa = old_attraction(old, old_city, i)
        budget, est, unknown = budget_for(atts, None, hotel, leg, 2)
        budget = int(round(budget * 1.1, -1))
        text = (f"我们两个人想{city}玩一天，再去{old_city}，10-28 上午到{st['name']}，"
                f"住{hotel['name']}，10-29 坐 {leg['name']} 过去，下午在{old_city}看{oa['name']}。"
                f"预算 {budget} 左右，不想太赶，帮我们排一下并说明要查什么。")
        uid = f"N{n:02d}"
        tasks.append(task_doc(uid, "human", text, [city, old_city], ["2026-10-28", "2026-10-29"], 2,
                              atts + [hotel, leg], start=st,
                              constraints={"window": ["08:00", "20:00"], "start_time": "09:00", "mode": "public_transit",
                                           "budget": budget, "overnight": True, "chain": True,
                                           "soft": ["slow_pace"]},
                              intercity=leg, old_city={"city": old_city, "attraction": slim(oa)},
                              budget=budget, estimated=est, unknown=unknown))
        n += 1
    return tasks

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    out = Path(a.out)
    by = load_v4()
    old = load_old()
    easy = build_easy(by)
    hard = build_hard(by, old)
    human = build_human(by, old)
    all_tasks = easy + hard + human
    assert len(easy) == 32 and len(hard) == 32 and len(human) == 32, (len(easy), len(hard), len(human))
    # uniqueness
    uids = [t["uid"] for t in all_tasks]
    assert len(set(uids)) == 96, "duplicate uid"
    out.mkdir(parents=True, exist_ok=True)
    (out / "tasks").mkdir(exist_ok=True)
    for name, rows in (("easy", easy), ("hard", hard), ("human", human), ("all_96", all_tasks)):
        (out / "tasks" / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    protocol = {
        "schema": "p31-five-city-v1",
        "created_at": "2026-10-26T18:30:00+08:00",
        "levels": {"easy": 32, "hard": 32, "human": 32},
        "cities": list(CITY_ADCODE),
        "dates": {"easy": ["2026-10-28"], "hard": ["2026-10-29"], "human": ["2026-10-29"]},
        "design": "easy=1-2 complete attractions + station start; hard=3 attractions+lunch or 2-day chain to an old city; human=natural-language soft constraints, some chains",
        "grounding": "candidates copied from data/five_city_reference_v4_20261026 and data/catalog_v1_1_20261022",
        "retrieval_budget_per_task": 8,
        "amap_scope": ["weather forecast", "public-transit route", "place text/detail for missing hours or coordinates"],
        "amap_excluded": ["intercity schedule (use frozen v4 records)", "ticket price (not provided by Amap place API)"],
        "note": "Human tasks are researcher-written natural expressions, not real user utterances; levels reuse entities.",
    }
    (out / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=1), encoding="utf-8")
    files = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(out.rglob("*.json"))}
    (out / "manifest.json").write_text(json.dumps({"files": files, "count": len(all_tasks)}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"easy": len(easy), "hard": len(hard), "human": len(human),
                      "uids": uids[:3] + uids[-3:]}, ensure_ascii=False))

if __name__ == "__main__":
    main()
