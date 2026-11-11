import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CT = ROOT / "ChinaTravel"

METHOD = {"easy": "ShortTrip_easy", "medium": "ShortTrip_medium", "human": "ShortTrip_human"}


def load(split):
    qs, plans = {}, {}
    for f in (CT / "chinatravel/data" / f"{split}_p33").glob("*.json"):
        q = json.loads(f.read_text(encoding="utf-8"))
        qs[q["uid"]] = q
    for f in (CT / "results" / METHOD[split]).glob("*.json"):
        plans[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return qs, plans


PATTERNS = {
    "required_restaurant_name": "restaurant_name_set",
    "required_hotel_name": "hotel_name_set",
    "required_attraction_name": "attraction_name_set",
    "other_dayactivities": "dayactivities",
    "other_forbidden": "not({",
    "hotel_feature": "hotel_feature",
    "budget": "total_cost<= ",
}


def main():
    for split in ("easy", "medium", "human"):
        qs, plans = load(split)
        base = CT / f"eval_res/splits_{split}_p33" / METHOD[split]
        rows = list(csv.DictReader(open(base / "logical_py.csv", encoding="utf-8-sig")))
        cols = [c for c in rows[0] if c != "data_id"]
        found = {}
        for r in rows:
            uid = r["data_id"]
            q = qs.get(uid)
            if not q or uid not in plans:
                continue
            logic = q.get("hard_logic_py") or []
            for i, c in enumerate(cols):
                if r[c] != "0":
                    continue
                text = logic[i] if i < len(logic) else ""
                for name, pat in PATTERNS.items():
                    if pat in text and name not in found:
                        found[name] = (uid, text)
            if len(found) >= len(PATTERNS):
                break
        print("#" * 28, split, "found", list(found))
        for name, (uid, text) in found.items():
            q, p = qs[uid], plans[uid]
            print("=" * 18, name, uid, "|", q.get("days"), "days", q.get("people_number"),
                  "people", q.get("start_city"), "->", q.get("target_city"))
            print("constraint:", text.replace("\n", " ")[:300])
            for day in p["itinerary"]:
                acts = [(a["type"], a.get("position") or a.get("TrainID") or a.get("FlightID"),
                         a["start_time"], a["end_time"], a.get("price"), a.get("cost"),
                         a.get("rooms"), a.get("room_type")) for a in day["activities"]]
                print(" plan day", day["day"], acts)
        print()


if __name__ == "__main__":
    main()
