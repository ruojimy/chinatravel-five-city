import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CT = ROOT / "ChinaTravel"
METHOD = {"easy": "ShortTrip_easy", "medium": "ShortTrip_medium", "human": "ShortTrip_human"}

import sys
sys.path.insert(0, str(ROOT / "reproduction/src"))
sys.path.insert(0, str(CT))
from shorttrip.env import get_env  # noqa: E402

env = get_env("zh")

for split in ("easy", "medium", "human"):
    base = CT / f"eval_res/splits_{split}_p33" / METHOD[split]
    rows = list(csv.DictReader(open(base / "commonsense.csv", encoding="utf-8-sig")))
    plans = {f.stem: json.loads(f.read_text(encoding="utf-8"))
             for f in (CT / "results" / METHOD[split]).glob("*.json")}
    bad = [r for r in rows if r["Incorrect Information of Accommodation on price or room type"] not in ("0", "0.0")]
    stats = Counter()
    examples = {}
    for r in bad:
        p = plans.get(r["data_id"])
        if not p:
            stats["missing_plan"] += 1
            continue
        city = p["target_city"]
        table = env.accommodation_table(city)
        for day in p["itinerary"]:
            for a in day["activities"]:
                if a["type"] != "accommodation":
                    continue
                hit = table[table["name"] == a["position"]]
                if hit.empty:
                    stats["hotel_not_found"] += 1
                    continue
                price = float(hit["price"].values[0])
                numbed = int(hit["numbed"].values[0])
                pm = abs(float(a.get("price", -1)) - price) > 0.01
                rm = int(a.get("room_type", -1)) != numbed
                key = ("price" if pm else "") + ("+room_type" if rm else "") or "cost_only"
                stats[key] += 1
                examples.setdefault(key, (r["data_id"], a["position"], a.get("price"),
                                          a.get("room_type"), a.get("rooms"), a.get("cost"),
                                          price, numbed))
    print("=" * 24, split, "violating queries", len(bad))
    print(stats.most_common())
    for k, v in examples.items():
        print(k, v)
