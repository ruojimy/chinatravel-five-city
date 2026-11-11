import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CT = ROOT / "ChinaTravel"
NAT = ROOT / "results/p33_native_planner"


def load_queries(split):
    split = split.replace("_p33", "")
    out = {}
    for f in (CT / "chinatravel/data" / f"{split}_p33").glob("*.json"):
        q = json.loads(f.read_text(encoding="utf-8"))
        out[q["uid"]] = q
    return out


def kind_of(text):
    t = text
    if "day_count(plan)" in t:
        return "days"
    if "food_cost" in t and "food_count" in t:
        return "per_meal_cost"
    if "people_count(plan)" in t:
        return "people"
    if "room_type" in t:
        return "room_type"
    if "room_count" in t:
        return "room_count"
    if "taxi_cars" in t:
        return "taxi_cars"
    if "metro_tickets" in t:
        return "metro_tickets"
    if "activity_tickets" in t:
        return "tickets"
    if "accommodation_type_set" in t or "accommodation_type(activity" in t:
        return "hotel_feature"
    if "hotel_feature" in t or "accommodation_feature" in t:
        return "hotel_feature"
    if "attraction_name_set" in t:
        return "required_attraction_name"
    if "attraction_type_set" in t or "attraction_type(activity" in t:
        return "attraction_type"
    if "restaurant_name_set" in t:
        return "required_restaurant_name"
    if "restaurant_type_set" in t or "restaurant_type(activity" in t:
        return "restaurant_type"
    if "hotel_name_set" in t or "accommodation_name_set" in t:
        return "required_hotel_name"
    if "intercity_transport_set" in t:
        return "intercity_type"
    if "innercity_transport_set" in t:
        return "innercity_type"
    if "go_start_time" in t or "return_start_time" in t:
        return "time_window"
    if "dayactivities" in t:
        return "day_attraction_count"
    if "attraction_count" in t:
        return "attraction_count"
    if "not({" in t:
        return "forbidden"
    if re.search(r"(total_cost|attraction_cost|accommodation_cost|restaurant_cost|"
                 r"inner_city_transportation_cost|food_price|hotel_price)", t):
        return "budget"
    return "other"


def main():
    summary = {}
    for split, method in (("easy_p33", "ShortTrip_easy"),
                          ("medium_p33", "ShortTrip_medium"),
                          ("human_p33", "ShortTrip_human")):
        qs = load_queries(split)
        base = CT / f"eval_res/splits_{split}/{method}"
        schema = list(csv.DictReader(open(base / "schema.csv", encoding="utf-8-sig")))
        common = list(csv.DictReader(open(base / "commonsense.csv", encoding="utf-8-sig")))
        logical = list(csv.DictReader(open(base / "logical_py.csv", encoding="utf-8-sig")))
        plan_rows = {r["uid"]: r for r in json.loads(
            (NAT / f"{split.replace('_p33', '')}_{method}.json").read_text(encoding="utf-8"))["rows"]}

        # commonsense violation columns
        ccols = [c for c in common[0] if c != "data_id"]
        cviol = Counter()
        for r in common:
            for c in ccols:
                if str(r[c]) not in ("0", "0.0", ""):
                    cviol[c] += 1

        # hard failures by kind
        lcols = [c for c in logical[0] if c != "data_id"]
        fail_kind = Counter()
        fail_queries = set()
        fail_counts = Counter()
        missing = 0
        for r in logical:
            uid = r["data_id"]
            q = qs.get(uid)
            logic = (q or {}).get("hard_logic_py") or []
            n_fail = 0
            for i, c in enumerate(lcols):
                if r[c] == "0":
                    n_fail += 1
                    fail_kind[kind_of(logic[i] if i < len(logic) else "")] += 1
            if n_fail:
                fail_queries.add(uid)
                fail_counts[n_fail] += 1
            if uid not in plan_rows or not plan_rows[uid].get("written"):
                missing += 1
        summary[split] = {
            "queries": len(logical),
            "schema_pass": sum(int(r["schema"]) for r in schema),
            "commonsense_pass": sum(1 for r in common if all(str(r[c]) in ("0", "0.0", "") for c in ccols)),
            "commonsense_violations": cviol.most_common(),
            "hard_pass": sum(1 for r in logical if all(r[c] != "0" for c in lcols)),
            "hard_fail_queries": len(fail_queries),
            "hard_fail_kinds": fail_kind.most_common(),
            "fail_count_dist": dict(sorted(fail_counts.items())),
            "missing_plans": missing,
        }
        print("=" * 24, split)
        print(json.dumps(summary[split], ensure_ascii=False, indent=1))

    (NAT / "failure_structure.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
