"""Build an 11th-city (Xi'an) ChinaTravel-style test set.

Produces, without touching ChinaTravel/ or any frozen snapshot:
  data/xian11_sandbox/    Xi'an environment in native ChinaTravel layout
  query_sets/xian11/{easy,medium,human,chain}/*.json

Query schema matches the official Phase-1 splits exactly; hard_logic_py
templates are re-parameterised from the 14/15/17 native DSL shapes. Every
entity name / type value referenced by a DSL constraint is taken from the
exported sandbox, so no constraint points at a non-existent entity.

Design: 60 single-city queries (30/15/15) = the per-city average of the
native 604-query development set, plus 30 multi-city chain queries using the
project's shorttrip-dynamic-v1 contract. See
collector_agent/xian_single_city/xian11_testset_policy.json.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from xian_scope import NATIVE10 as CITY10, EXPANSION30, city_of  # noqa: E402

SOURCE_SNAPSHOT = ROOT / "results/xian_claude_20261108_145612/snapshot_v4/catalog.sqlite3"
SANDBOX = ROOT / "data/xian11_sandbox"
QUERIES = ROOT / "query_sets/xian11"
POLICY = ROOT / "collector_agent/xian_single_city/xian11_testset_policy.json"
CITY = "西安"
SLUG = "xian"
LEVELS = ("easy", "medium", "human", "chain")
QUOTA = {"easy": 30, "medium": 15, "human": 15, "chain": 30}
CHAIN_LEVELS = {"easy": 10, "medium": 10, "human": 10}

# ---------------------------------------------------------------- DSL shapes
# Copied from the native splits (see 报告/36_…), parameterised. Each entry is
# (semantic_family, constraint_key, builder) where builder receives a context.
def _days(ctx):
    return f"result=(day_count(plan)=={ctx['days']})"


def _people(ctx):
    return f"result=(people_count(plan)=={ctx['people']})"


def _tickets(ctx):
    return ("result=True\nfor activity in allactivities(plan):\n"
            f"  if activity_type(activity) in ['attraction', 'airplane', 'train'] and activity_tickets(activity)!={ctx['people']}: result=False\n"
            f"  if innercity_transport_type(activity_transports(activity))=='metro'and metro_tickets(activity_transports(activity))!={ctx['people']}: result=False")


def _taxi(ctx):
    return ("result=True\nfor activity in allactivities(plan):\n"
            "  if innercity_transport_type(activity_transports(activity))=='taxi'and taxi_cars(activity_transports(activity))!=1: result=False")


def _budget(ctx):
    return ("total_cost=0 \nfor activity in allactivities(plan):\n"
            "    total_cost+=activity_cost(activity)\n"
            "    total_cost += innercity_transport_cost(activity_transports(activity))\n"
            f"result=(total_cost<={ctx['budget']})")


def _room_count(ctx):
    return ("result=True\nfor activity in allactivities(plan):\n"
            f"  if activity_type(activity)=='accommodation' and room_count(activity)!={ctx['rooms']}: result=False")


def _room_type(ctx):
    return ("result=True\nfor activity in allactivities(plan):\n"
            f"  if activity_type(activity)=='accommodation' and room_type(activity)!='{ctx['room_type']}': result=False")


def _attraction_type(ctx):
    return ("attraction_type_set=set()\nfor activity in allactivities(plan):\n"
            "  if activity_type(activity)=='attraction': attraction_type_set.add(attraction_type(activity, target_city(plan)))\n"
            f"result=({{'{ctx['attraction_type']}'}}<=attraction_type_set)")


def _restaurant_type(ctx):
    return ("restaurant_type_set=set()\nfor activity in allactivities(plan):\n"
            "  if activity_type(activity) in ['breakfast', 'lunch', 'dinner']: restaurant_type_set.add(restaurant_type(activity, target_city(plan)))\n"
            f"result=({{'{ctx['cuisine']}'}}<=restaurant_type_set)")


def _accommodation_type(ctx):
    return ("accommodation_type_set=set()\nfor activity in allactivities(plan):\n"
            "  if activity_type(activity) == 'accommodation': accommodation_type_set.add(accommodation_type(activity, target_city(plan)))\n"
            f"result=({{'{ctx['hotel_type']}'}}<=accommodation_type_set)")


def _attraction_name(ctx):
    return ("attraction_name_set=set()\nfor activity in allactivities(plan):\n"
            "  if activity_type(activity)=='attraction': attraction_name_set.add(activity_position(activity))\n"
            f"result=({{'{ctx['attraction']}'}}<=attraction_name_set)")


def _restaurant_name(ctx):
    return ("restaurant_name_set=set()\nfor activity in allactivities(plan):\n"
            "  if activity_type(activity) in ['breakfast', 'lunch', 'dinner']: restaurant_name_set.add(activity_position(activity))\n"
            f"result=({{'{ctx['restaurant']}'}}<=restaurant_name_set)")


def _accommodation_name(ctx):
    return ("accommodation_name_set=set()\nfor activity in allactivities(plan):\n"
            "  if activity_type(activity)=='accommodation': accommodation_name_set.add(activity_position(activity))\n"
            f"result=({{'{ctx['hotel']}'}}<=accommodation_name_set)")


def _intercity(ctx):
    return ("intercity_transport_set=set()\nfor activity in allactivities(plan):\n"
            "  if activity_type(activity) in ['train', 'airplane']: intercity_transport_set.add(intercity_transport_type(activity))\n"
            f"result=({{'{ctx['intercity']}'}}==intercity_transport_set)")


def _innercity(ctx):
    return ("innercity_transport_set=set()\nfor activity in allactivities(plan):\n"
            "  if activity_transports(activity)!=[]: innercity_transport_set.add(innercity_transport_type(activity_transports(activity)))\n"
            f"result=(innercity_transport_set<={{'{ctx['innercity']}'}})")


def _innercity_include(ctx):
    return ("innercity_transport_set=set()\nfor activity in allactivities(plan):\n"
            "  if activity_transports(activity)!=[]: innercity_transport_set.add(innercity_transport_type(activity_transports(activity)))\n"
            f"result=({{'{ctx['innercity']}'}}<=innercity_transport_set)")


def _hotel_cost(ctx):
    return ("hotel_cost=0\nfor activity in allactivities(plan):\n"
            "  if activity_type(activity)=='accommodation': hotel_cost+=activity_cost(activity)\n"
            f"result=(hotel_cost/people_count(plan)/(day_count(plan)-1)<= {ctx['hotel_cap']})")


def _food_cost(ctx):
    return ("food_cost,food_count=0,0\nfor activity in allactivities(plan):\n"
            "    if activity_type(activity) in ['breakfast', 'lunch', 'dinner']:\n"
            "        food_cost+=activity_cost(activity)\n"
            "        food_count+=1\n"
            f"result=(food_cost/food_count/people_count(plan)<={ctx['food_cap']})")


def _go_start(ctx):
    return ("go_start_time = 0\nfor activity in allactivities(plan):\n"
            "  if activity_type(activity) in ['train','airplane'] and intercity_transport_origin(activity) == start_city(plan): go_start_time = activity_start_time(activity)\n"
            f"result=(go_start_time>='{ctx['go_after']}')")


def _return_start(ctx):
    return ("return_start_time = 0\nfor activity in allactivities(plan):\n"
            "  if activity_type(activity) in ['train','airplane'] and intercity_transport_origin(activity) == target_city(plan): return_start_time = activity_start_time(activity)\n"
            f"result=(return_start_time<='{ctx['return_before']}')")


def _attraction_pair(ctx):
    a, b = ctx["pair"]
    return ("day_attraction_name_set=set()\nfor activity in dayactivities(plan, "
            f"{ctx['pair_day']}):\n"
            "  if activity_type(activity)=='attraction': day_attraction_name_set.add(activity_position(activity))\n"
            f"result=({{'{a}', '{b}'}}<=day_attraction_name_set)")


# ---- Phase-2 DSL shapes, taken verbatim (parameterised) from the official
# competition_test split so the remaining 6 semantic families are covered.
def _walking_budget(ctx):
    return ("total_walking_distance=0\nfor activity in allactivities(plan):\n"
            "  total_walking_distance+=innercity_transport_distance(activity_transports(activity), 'walk')\n"
            f"result=(total_walking_distance<={ctx['walk_km']})")


def _travel_time_budget(ctx):
    return ("innercity_travel_minutes=0\nfor activity in allactivities(plan):\n"
            "  innercity_travel_minutes+=innercity_transport_time(activity_transports(activity))\n"
            f"result=(innercity_travel_minutes<={ctx['travel_minutes']})")


def _mode_count(ctx):
    return ("transport_journey_count=0\nfor activity in allactivities(plan):\n"
            f"  if innercity_transport_type(activity_transports(activity))=='{ctx['innercity']}': transport_journey_count+=1\n"
            f"result=(transport_journey_count<={ctx['journey_cap']})")


def _attraction_count_day(ctx):
    return (f"day_attraction_count=0\nfor activity in dayactivities(plan, {ctx['count_day']}):\n"
            "  if activity_type(activity)=='attraction': day_attraction_count+=1\n"
            f"result=(day_attraction_count>={ctx['min_attr']})")


def _meals_on_day(ctx):
    return (f"day_meal_type_set=set()\nfor activity in dayactivities(plan, {ctx['count_day']}):\n"
            "  if activity_type(activity) in ['breakfast', 'lunch', 'dinner']: day_meal_type_set.add(activity_type(activity))\n"
            "result=({'breakfast', 'lunch', 'dinner'}<=day_meal_type_set)")


def _attraction_time_window(ctx):
    return ("result=False\nfor activity in allactivities(plan):\n"
            f"  if activity_type(activity)=='attraction' and activity_position(activity)=='{ctx['attraction']}':\n"
            f"    if activity_start_time(activity)>='{ctx['window_start']}' and activity_end_time(activity)<='{ctx['window_end']}': result=True")


def _attraction_on_day(ctx):
    return (f"day_attraction_name_set=set()\nfor activity in dayactivities(plan, {ctx['count_day']}):\n"
            "  if activity_type(activity)=='attraction': day_attraction_name_set.add(activity_position(activity))\n"
            f"result=({{'{ctx['attraction']}'}}<=day_attraction_name_set)")


def _attraction_order(ctx):
    a, b = ctx["pair"]
    return ("seen_first=False\nresult=False\nfor activity in allactivities(plan):\n"
            f"  if activity_type(activity)=='attraction' and activity_position(activity)=='{a}': seen_first=True\n"
            f"  if activity_type(activity)=='attraction' and activity_position(activity)=='{b}' and seen_first: result=True")


def _cross_category_order(ctx):
    return ("first_activity_seen=False\nresult=False\nfor activity in allactivities(plan):\n"
            f"  if activity_type(activity)=='attraction' and activity_position(activity)=='{ctx['attraction']}': first_activity_seen=True\n"
            f"  if activity_type(activity)=='accommodation' and activity_position(activity)=='{ctx['hotel']}' and first_activity_seen: result=True")


def _forbidden_restaurant_types(ctx):
    return ("restaurant_type_set=set()\nfor activity in allactivities(plan):\n"
            "  if activity_type(activity) in ['breakfast', 'lunch', 'dinner']: restaurant_type_set.add(restaurant_type(activity, target_city(plan)))\n"
            f"result=not({{'{ctx['forbidden_cuisine']}'}}&restaurant_type_set)")


def _forbidden_attraction_names(ctx):
    return ("attraction_name_set=set()\nfor activity in allactivities(plan):\n"
            "  if activity_type(activity)=='attraction': attraction_name_set.add(activity_position(activity))\n"
            f"result=not({{'{ctx['forbidden_attraction']}'}}&attraction_name_set)")


def _either_requirement(ctx):
    return ("result_list=[]\nresult=False\nfor activity in allactivities(plan):\n"
            f"  if activity_type(activity)=='attraction' and activity_position(activity)=='{ctx['attraction']}': result=True\n"
            "result_list.append(result)\nattraction_minutes=0\nfor activity in allactivities(plan):\n"
            "  if activity_type(activity)=='attraction': attraction_minutes+=activity_time(activity)\n"
            f"result=(attraction_minutes>={ctx['min_minutes']})\nresult_list.append(result)\n"
            "result=False\nfor r in result_list:\n  result=result or r")


TEMPLATES = {
    "trip_days": ("basic", _days),
    "people_number": ("basic", _people),
    "tickets_match_people": ("basic", _tickets),
    "taxi_cars": ("transport", _taxi),
    "total_budget": ("budget", _budget),
    "room_count": ("room", _room_count),
    "room_type": ("room", _room_type),
    "required_attraction_types": ("name_type", _attraction_type),
    "required_restaurant_types": ("name_type", _restaurant_type),
    "required_accommodation_types": ("name_type", _accommodation_type),
    "required_attraction_names": ("name_type", _attraction_name),
    "required_restaurant_names": ("name_type", _restaurant_name),
    "required_accommodation_names": ("name_type", _accommodation_name),
    "intercity_modes_include": ("transport", _intercity),
    "inner_transport_modes_subset": ("transport", _innercity),
    "daily_budget": ("budget", _budget),
    "accommodation_budget": ("budget", _hotel_cost),
    "restaurant_budget": ("budget", _food_cost),
    "outbound_departure_deadline": ("schedule", _go_start),
    "return_departure_earliest": ("schedule", _return_start),
    "attraction_pair_on_day": ("relation", _attraction_pair),
    "walking_distance_budget": ("transport_metrics", _walking_budget),
    "innercity_travel_time_budget": ("transport_metrics", _travel_time_budget),
    "inner_transport_mode_count": ("transport_metrics", _mode_count),
    "attraction_count_on_day": ("count", _attraction_count_day),
    "required_meals_on_day": ("count", _meals_on_day),
    "attraction_time_window": ("day_time", _attraction_time_window),
    "attraction_on_day": ("day_time", _attraction_on_day),
    "attraction_order": ("sequence", _attraction_order),
    "cross_category_order": ("relation", _cross_category_order),
    "forbidden_restaurant_types": ("negative", _forbidden_restaurant_types),
    "forbidden_attraction_names": ("negative", _forbidden_attraction_names),
    "either_requirement": ("logic", _either_requirement),
}

# Native per-level template frequency, used to pick the optional constraints.
OPTIONAL_POOL = {
    "easy": ["total_budget", "room_count", "room_type", "required_attraction_types",
             "required_restaurant_types", "required_accommodation_types",
             "required_attraction_names", "required_restaurant_names",
             "required_accommodation_names", "intercity_modes_include",
             "inner_transport_modes_subset"],
    "medium": ["total_budget", "room_count", "required_restaurant_types",
               "required_attraction_types", "required_attraction_names",
               "required_restaurant_names", "required_accommodation_types",
               "intercity_modes_include", "daily_budget", "accommodation_budget",
               "restaurant_budget", "outbound_departure_deadline"],
    "human": ["total_budget", "required_attraction_types", "required_restaurant_types",
              "required_attraction_names", "intercity_modes_include",
              "inner_transport_modes_subset", "return_departure_earliest",
              "attraction_pair_on_day", "accommodation_budget"],
}

# Extra Phase-2 families that must appear somewhere in the corpus. They are
# distributed round-robin over medium/human queries so all 13 families are
# exercised without inflating the per-query constraint count.
FAMILY_FILL = [
    "walking_distance_budget", "innercity_travel_time_budget", "inner_transport_mode_count",
    "attraction_count_on_day", "required_meals_on_day", "attraction_time_window",
    "attraction_on_day", "attraction_order", "cross_category_order",
    "forbidden_restaurant_types", "forbidden_attraction_names", "either_requirement",
]

NL_TEMPLATES = {
    "total_budget": ("预算{budget}元", "with a budget of {budget} RMB"),
    "daily_budget": ("每天预算不超过{budget}元", "with a daily budget under {budget} RMB"),
    "room_count": ("住{rooms}间房", "book {rooms} room(s)"),
    "room_type": ("要{room_type}", "require a {room_type} room"),
    "required_attraction_types": ("想去{attraction_type}类景点", "want to visit {attraction_type} attractions"),
    "required_restaurant_types": ("想吃{cuisine}", "want to try {cuisine} food"),
    "required_accommodation_types": ("酒店要有{hotel_type}", "the hotel should offer {hotel_type}"),
    "required_attraction_names": ("一定要去{attraction}", "must visit {attraction}"),
    "required_restaurant_names": ("想去{restaurant}吃饭", "want to eat at {restaurant}"),
    "required_accommodation_names": ("住{hotel}", "stay at {hotel}"),
    "intercity_modes_include": ("往返坐{intercity_zh}", "travel by {intercity} both ways"),
    "inner_transport_modes_subset": ("市内只坐{innercity_zh}", "use only {innercity} within the city"),
    "accommodation_budget": ("每晚人均住宿不超过{hotel_cap}元", "hotel cost under {hotel_cap} RMB per person per night"),
    "restaurant_budget": ("每餐人均不超过{food_cap}元", "meal cost under {food_cap} RMB per person"),
    "outbound_departure_deadline": ("去程{go_after}之后出发", "depart after {go_after}"),
    "return_departure_earliest": ("返程{return_before}之前出发", "return before {return_before}"),
    "attraction_pair_on_day": ("第{pair_day}天要去{pair_a}和{pair_b}", "visit {pair_a} and {pair_b} on day {pair_day}"),
}


# ---------------------------------------------------------------- sandbox export
def load_records() -> dict[str, list[dict]]:
    conn = sqlite3.connect(SOURCE_SNAPSHOT.resolve().as_uri() + "?mode=ro", uri=True)
    out: dict[str, list[dict]] = defaultdict(list)
    for kind, name, payload, gate in conn.execute(
            "select kind,name,payload,gate from records where city=?", (CITY,)):
        if not json.loads(gate).get("discovery_ok"):
            continue
        out[kind].append({"name": name, **json.loads(payload).get("data", {})})
    conn.close()
    return out


def _write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def export_sandbox(records: dict[str, list[dict]]) -> dict:
    counts = {}
    # numeric primary keys, as native schema requires an int id
    def rows_for(kind, fields, transform):
        out = []
        for i, r in enumerate(records.get(kind, []), 1):
            row = {"id": i, "name": r.get("name")}
            row.update(transform(r))
            out.append({k: (row.get(k) if row.get(k) not in ("", None) else "") for k in fields})
        return out

    att = rows_for("attraction",
                   ["id", "name", "type", "lat", "lon", "opentime", "endtime", "price",
                    "recommendmintime", "recommendmaxtime"],
                   lambda r: {k: r.get(k) for k in
                              ("type", "lat", "lon", "opentime", "endtime", "price",
                               "recommendmintime", "recommendmaxtime")})
    _write_csv(SANDBOX / "attractions" / SLUG / "attractions.csv",
               ["id", "name", "type", "lat", "lon", "opentime", "endtime", "price",
                "recommendmintime", "recommendmaxtime"], att)
    counts["attractions"] = len(att)

    rest = rows_for("restaurant",
                    ["id", "name", "lat", "lon", "price", "cuisine", "opentime", "endtime", "recommendedfood"],
                    lambda r: {k: r.get(k) for k in
                               ("lat", "lon", "price", "cuisine", "opentime", "endtime", "recommendedfood")})
    _write_csv(SANDBOX / "restaurants" / SLUG / f"restaurants_{SLUG}.csv",
               ["id", "name", "lat", "lon", "price", "cuisine", "opentime", "endtime", "recommendedfood"], rest)
    counts["restaurants"] = len(rest)

    acc = rows_for("accommodation",
                   ["id", "name", "hotelname_en", "featurehoteltype", "lat", "lon", "price", "numbed"],
                   lambda r: {k: r.get(k) for k in
                              ("hotelname_en", "featurehoteltype", "lat", "lon", "price", "numbed")})
    _write_csv(SANDBOX / "accommodations" / SLUG / "accommodations.csv",
               ["id", "name", "hotelname_en", "featurehoteltype", "lat", "lon", "price", "numbed"], acc)
    counts["accommodations"] = len(acc)

    def dump(path: Path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # native poi.json is a list of {name, position:[lat,lon]}; our catalog
    # stores poi as a list [lat, lon] and metro as a "lon,lat" string.
    def as_latlon(value):
        if isinstance(value, list) and len(value) == 2:
            return [value[0], value[1]]
        if isinstance(value, str) and "," in value:
            lon, lat = value.split(",")[:2]
            try:
                return [float(lat), float(lon)]
            except ValueError:
                return None
        return None

    poi = []
    for r in records.get("poi", []):
        pos = as_latlon(r.get("position"))
        if pos:
            poi.append({"name": r["name"], "position": pos})
    dump(SANDBOX / "poi" / SLUG / "poi.json", poi)
    counts["poi"] = len(poi)

    metro = []
    for r in records.get("metro_station", []):
        pos = as_latlon(r.get("position"))
        if pos:
            metro.append({"name": r["name"], "position": pos, "line": r.get("line")})
    dump(SANDBOX / "subway_stations" / SLUG / "subway_stations.json", metro)
    counts["subway_stations"] = len(metro)

    # intercity: native naming is from_<start_city>_to_<end_city>.json, so
    # normalise station names to city names first.
    train_dir = SANDBOX / "intercity_transport" / "train"
    train_dir.mkdir(parents=True, exist_ok=True)
    grouped = defaultdict(list)
    skipped_pair = 0
    for r in records.get("train", []):
        a, b = city_of(r.get("From")), city_of(r.get("To"))
        if a == "OUT" or b == "OUT" or a == b:
            skipped_pair += 1
            continue
        grouped[(a, b)].append({k: r.get(k) for k in
                               ("TrainID", "TrainType", "From", "To", "BeginTime", "EndTime", "Duration", "Cost")})
    for (a, b), rows in grouped.items():
        dump(train_dir / f"from_{a}_to_{b}.json", rows)
    counts["train_files"] = len(grouped)
    counts["train_pairs_skipped"] = skipped_pair
    flights = [{k: r.get(k) for k in
                ("FlightID", "From", "To", "BeginTime", "EndTime", "Duration", "Cost")}
               for r in records.get("flight", [])]
    with (SANDBOX / "intercity_transport" / "airplane.jsonl").open("w", encoding="utf-8") as f:
        for row in flights:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    counts["flights"] = len(flights)
    return counts


# ---------------------------------------------------------------- entity pools
def build_pools(records: dict[str, list[dict]]) -> dict:
    def clean(values, min_len=2, max_len=18, numeric=False):
        out = []
        for v in values:
            if v in (None, ""):
                continue
            s = str(v).strip()
            if not (min_len <= len(s) <= max_len):
                continue
            if numeric and not s.replace(".", "", 1).isdigit():
                continue
            if "'" in s or "\\" in s or "{" in s:
                continue
            out.append(s)
        return sorted(set(out))

    pools = {
        "attraction": clean(r["name"] for r in records.get("attraction", []) if r.get("lat")),
        "restaurant": clean(r["name"] for r in records.get("restaurant", []) if r.get("lat")),
        "hotel": clean(r["name"] for r in records.get("accommodation", []) if r.get("lat")),
        "attraction_type": clean(r.get("type") for r in records.get("attraction", []) if r.get("lat")),
        "cuisine": clean(r.get("cuisine") for r in records.get("restaurant", []) if r.get("lat")),
        "hotel_type": clean(r.get("featurehoteltype") for r in records.get("accommodation", []) if r.get("lat")),
        "room_type": ["大床房", "双床房", "单床房"],
        "intercity": ["train", "airplane"],
        "innercity": ["metro", "taxi", "walk"],
    }
    # native type vocab is descriptive Chinese, not amap typecodes / dish names
    def readable(s):
        return bool(re.fullmatch(r"[\u4e00-\u9fa5A-Za-z·]{2,12}", s)) and not any(
            ch.isdigit() for ch in s)

    pools["attraction_type"] = [x for x in pools["attraction_type"] if readable(x)]
    pools["cuisine"] = [x for x in pools["cuisine"]
                        if readable(x) and x not in ("中餐", "中餐厅", "其他中餐")]
    pools["hotel_type"] = [x for x in pools["hotel_type"] if readable(x)]
    # dish-like single items are not cuisine categories in the native sense
    pools["cuisine"] = [x for x in pools["cuisine"]
                        if x.endswith(("菜", "餐", "食", "小吃", "火锅", "烧烤", "面", "料理", "风味"))
                        or x in ("清真", "茶座", "咖啡厅", "自助餐")]
    if not pools["attraction_type"]:
        pools["attraction_type"] = ["历史古迹", "自然风光"]
    if not pools["cuisine"]:
        pools["cuisine"] = ["陕菜", "川菜", "西北菜"]
    if not pools["hotel_type"]:
        pools["hotel_type"] = ["经济型", "商务酒店"]
    return pools


def make_ctx(rng: random.Random, pools: dict, level: str, pair: tuple[str, str],
             days: int, people: int) -> dict:
    ctx = {
        "days": days, "people": people,
        "budget": rng.choice([1000, 1500, 2000, 3000, 5000, 6000, 8000]),
        "rooms": max(1, (people + 1) // 2),
        "room_type": rng.choice(pools["room_type"]),
        "attraction": rng.choice(pools["attraction"]),
        "restaurant": rng.choice(pools["restaurant"]),
        "hotel": rng.choice(pools["hotel"]),
        "attraction_type": rng.choice(pools["attraction_type"]),
        "cuisine": rng.choice(pools["cuisine"]),
        "hotel_type": rng.choice(pools["hotel_type"]),
        "intercity": rng.choice(pools["intercity"]),
        "innercity": rng.choice(pools["innercity"]),
        "hotel_cap": rng.choice([300, 500, 700]),
        "food_cap": rng.choice([40, 60, 80]),
        "go_after": rng.choice(["08:00", "10:00", "12:00", "17:00"]),
        "return_before": rng.choice(["12:00", "17:00", "19:00"]),
        "pair_day": rng.randint(1, max(1, days - 1)),
        "pair": tuple(rng.sample(pools["attraction"], 2)),
        "walk_km": rng.choice([5.0, 10.0, 15.0, 21.2]),
        "travel_minutes": rng.choice([120, 180, 240, 356]),
        "journey_cap": rng.choice([4, 6, 8]),
        "count_day": rng.randint(1, max(1, days - 1)),
        "min_attr": rng.choice([1, 2, 3]),
        "window_start": rng.choice(["09:00", "10:00", "11:00"]),
        "window_end": rng.choice(["13:40", "16:00", "18:00"]),
        "min_minutes": rng.choice([120, 240, 360]),
        "forbidden_cuisine": rng.choice(pools["cuisine"]),
        "forbidden_attraction": rng.choice(pools["attraction"]),
    }
    ctx["intercity_zh"] = "火车" if ctx["intercity"] == "train" else "飞机"
    ctx["innercity_zh"] = {"metro": "地铁", "taxi": "出租车", "walk": "步行"}[ctx["innercity"]]
    return ctx


def build_single(rng, pools, level, pair, days, people, uid, family_key=None):
    ctx = make_ctx(rng, pools, level, pair, days, people)
    start, target = pair
    # mandatory native four
    keys = ["trip_days", "people_number", "tickets_match_people", "taxi_cars"]
    n_optional = {"easy": 1, "medium": 4, "human": rng.choice([0, 1, 2])}[level]
    # ensure family coverage rotates across the corpus
    extra = list(OPTIONAL_POOL[level])
    rng.shuffle(extra)
    keys += extra[:n_optional]
    if family_key and family_key not in keys:
        keys.append(family_key)
    logic = [TEMPLATES[k][1](ctx) for k in keys]
    families = sorted({TEMPLATES[k][0] for k in keys})

    zh_parts, en_parts = [], []
    for k in keys:
        if k in NL_TEMPLATES:
            zh, en = NL_TEMPLATES[k]
            try:
                zh_parts.append(zh.format(**ctx, pair_a=ctx["pair"][0], pair_b=ctx["pair"][1]))
                en_parts.append(en.format(**ctx, pair_a=ctx["pair"][0], pair_b=ctx["pair"][1]))
            except (KeyError, IndexError):
                pass
    head_zh = f"当前位置{start}。{people_text(people, zh=True)}想去{target}玩{days}天"
    head_en = f"Currently in {start}. {people_text(people, zh=False)} want to travel to {target} for {days} day(s)"
    suffix_zh = "，".join(zh_parts)
    suffix_en = ", ".join(en_parts)
    nl_zh = head_zh + ("，" + suffix_zh if suffix_zh else "") + "，请给我一个旅行规划。"
    nl_en = head_en + ("; " + suffix_en if suffix_en else "") + ". Please provide a travel plan."
    if level == "human":
        # native human split reads like a real request, not a keyword list
        opener = rng.choice([
            "想找个轻松点的行程，", "别安排得太赶，", "第一次去，",
            "希望能玩得舒服些，", "时间比较自由，", "尽量少折腾，",
        ])
        body = suffix_zh or "帮忙推荐一条合适的路线"
        nl_zh = (f"[当前位置{start},目标位置{target},旅行人数{people},旅行天数{days}] "
                 f"{opener}{body}。帮我规划一下。")

    return {
        "uid": uid,
        "tag": level,
        "start_city": start,
        "target_city": target,
        "days": days,
        "people_number": people,
        "limit_rooms": False,
        "limits_room_type": "room_type" in keys,
        "hard_logic_py": logic,
        "nature_language": nl_zh,
        "nature_language_en": nl_en,
        "constraint_keys": keys,
        "constraint_families": families,
        "xian11": {"city_role": "target" if target == CITY else "start",
                   "translation": "controlled_template",
                   "native_compatible": True},
    }


def people_text(n: int, zh: bool) -> str:
    if zh:
        return {1: "我一个人", 2: "我们两个人", 3: "我们三个人", 4: "我们四个人", 5: "我们五个人"}.get(n, f"我们{n}个人")
    return {1: "I", 2: "we two", 3: "three of us", 4: "four of us", 5: "five of us"}.get(n, f"{n} of us")


def build_chain(rng, pools, level, idx, uid):
    # round-robin over the 10 native cities so every city appears at least once
    cities = list(CITY10)
    a = cities[idx % len(cities)]
    b = cities[(idx * 7 + 3) % len(cities)]
    if a == b:
        b = cities[(idx + 5) % len(cities)]
    form = idx % 3
    if form == 0:
        seq, role = [CITY, a], "first"
    elif form == 1:
        seq, role = [a, CITY], "last"
    else:
        seq, role = [a, CITY, b], "middle"
    dates = [f"2026-11-{10 + i:02d}" for i in range(len(seq) + 1)]
    people = rng.choice([1, 2, 3, 4])
    attraction = rng.choice(pools["attraction"])
    # the attraction belongs to the city where Xi'an actually sits in the chain
    nl = (f"{people}人从{seq[0]}出发，{'途经' if len(seq) == 3 else '前往'}"
          f"{'、'.join(seq[1:])}，共{len(seq) + 1}天；"
          f"{'在' + CITY if role != 'first' else '离开' + CITY + '前'}安排{attraction}，"
          "请核对跨城班次与到达时刻，没有班次或坐标证据时保留待定连接，切勿编造车次。")
    return {
        "schema_version": "shorttrip-dynamic-v1",
        "uid": uid,
        "nature_language": nl,
        "people_number": people,
        "city_sequence": seq,
        "dates": dates,
        "level": level,
        "candidates": [],
        "retrieval_budget": 8,
        "requirements": {"must_visit": [attraction], "city_role": role},
        "xian11": {"chain_type": {0: "two_city_xian_first", 1: "two_city_xian_last",
                                  2: "three_city_xian_middle"}[form],
                   "xian_role": role, "translation": "controlled_template",
                   "native_compatible": False},
    }


# ---------------------------------------------------------------- main
def main() -> int:
    global SOURCE_SNAPSHOT, SANDBOX
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261108)
    ap.add_argument("--source-snapshot", default=str(SOURCE_SNAPSHOT))
    ap.add_argument("--out-queries", default=str(QUERIES))
    ap.add_argument("--out-sandbox", default=str(SANDBOX))
    ap.add_argument("--skip-sandbox", action="store_true")
    args = ap.parse_args()
    SOURCE_SNAPSHOT = Path(args.source_snapshot).resolve()
    SANDBOX = Path(args.out_sandbox)
    rng = random.Random(args.seed)
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    records = load_records()
    pools = build_pools(records)

    if not args.skip_sandbox:
        counts = export_sandbox(records)
        print("sandbox:", json.dumps(counts, ensure_ascii=False))

    out = Path(args.out_queries)
    # 20 ordered pairs; easy covers all 20, medium/human rotate to cover all too
    pairs = [(CITY, c) for c in CITY10] + [(c, CITY) for c in CITY10]
    day_opts = {"easy": [1, 2, 3], "medium": [2, 3, 4], "human": [1, 2, 3, 4, 5, 6]}
    ppl_opts = {"easy": [1, 2, 3, 4], "medium": [1, 2, 3, 4], "human": [1, 2, 3, 4, 5]}
    written = Counter()
    # distribute the 12 Phase-2-only constraint keys over medium + human
    family_slots = [None] * QUOTA["easy"]
    other_slots = [None] * (QUOTA["medium"] + QUOTA["human"])
    for i, key in enumerate(FAMILY_FILL):
        other_slots[i % len(other_slots)] = key
    family_iter = iter(family_slots + other_slots[:QUOTA["medium"]] +
                       other_slots[QUOTA["medium"]:])
    for level in ("easy", "medium", "human"):
        d = out / level
        d.mkdir(parents=True, exist_ok=True)
        n = QUOTA[level]
        # rotate pairs so each of the 20 appears at least once in every level
        ordered = (pairs * ((n // len(pairs)) + 1))[:n]
        rng.shuffle(ordered)
        if n >= 20:
            ordered[:20] = pairs
            rng.shuffle(ordered[:20])
        for i in range(n):
            uid = f"x11{level[0]}{i + 1:03d}"
            pair = ordered[i]
            q = build_single(rng, pools, level, pair,
                             rng.choice(day_opts[level]), rng.choice(ppl_opts[level]), uid,
                             family_key=next(family_iter, None))
            (d / f"{uid}.json").write_text(json.dumps(q, ensure_ascii=False, indent=1) + "\n",
                                           encoding="utf-8")
            written[level] += 1

    d = out / "chain"
    d.mkdir(parents=True, exist_ok=True)
    i = 0
    for level, n in CHAIN_LEVELS.items():
        for j in range(n):
            uid = f"x11c{i + 1:03d}"
            q = build_chain(rng, pools, level, i, uid)
            (d / f"{uid}.json").write_text(json.dumps(q, ensure_ascii=False, indent=1) + "\n",
                                           encoding="utf-8")
            i += 1
            written["chain"] += 1

    manifest = {
        "version": policy["version"], "seed": args.seed,
        "source_snapshot": str(SOURCE_SNAPSHOT.relative_to(ROOT)).replace("\\", "/"),
        "sandbox": "data/xian11_sandbox", "queries": "query_sets/xian11",
        "counts": dict(written), "total": sum(written.values()),
        "policy": "collector_agent/xian_single_city/xian11_testset_policy.json",
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                                       encoding="utf-8")
    print("queries:", json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
