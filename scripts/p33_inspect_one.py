import json, collections
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "ChinaTravel"
qs = {}
for f in (root / "chinatravel/data/easy_p33").glob("*.json"):
    q = json.loads(f.read_text(encoding="utf-8"))
    qs[q["uid"]] = q

uid = "e20241028160323008998"
q = qs[uid]
print(json.dumps({k: q.get(k) for k in ("uid", "days", "people_number", "start_city", "target_city",
                                        "nature_language")}, ensure_ascii=False, indent=1))
for i, c in enumerate(q.get("hard_logic_py") or []):
    print(f"--- logic {i} ---")
    print(c)

plan = json.loads((root / f"results/ShortTrip_easy/{uid}.json").read_text(encoding="utf-8"))
print("plan days", len(plan["itinerary"]))
for day in plan["itinerary"]:
    print("day", day["day"], [(a["type"], a.get("position") or a.get("TrainID") or a.get("FlightID"),
                               a["start_time"], a["end_time"], a["cost"]) for a in day["activities"]])

# logic_py_5 across easy queries
texts = collections.Counter()
for q2 in qs.values():
    lg = q2.get("hard_logic_py") or []
    if len(lg) > 5:
        texts[lg[5][:120]] += 1
print("\nlogic index 5 variants:", len(texts))
for t, n in texts.most_common(5):
    print(n, t.replace("\n", " "))
