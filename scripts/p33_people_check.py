import csv
import json
from pathlib import Path

CT = Path(__file__).resolve().parents[1] / "ChinaTravel"
qs = {}
for f in (CT / "chinatravel/data/medium_p33").glob("*.json"):
    q = json.loads(f.read_text(encoding="utf-8"))
    qs[q["uid"]] = q
rows = list(csv.DictReader(open(
    CT / "eval_res/splits_medium_p33/ShortTrip_medium/logical_py.csv", encoding="utf-8-sig")))
cols = [c for c in rows[0] if c != "data_id"]
n = 0
for r in rows:
    q = qs.get(r["data_id"])
    if not q:
        continue
    lg = q.get("hard_logic_py") or []
    for i, c in enumerate(cols):
        if r[c] == "0" and i < len(lg) and "people_count" in lg[i]:
            plan = json.loads((CT / "results/ShortTrip_medium" / f"{q['uid']}.json").read_text(encoding="utf-8"))
            print(q["uid"], "query people", q["people_number"], "plan people", plan.get("people_number"),
                  "constraint", lg[i].strip())
            n += 1
            break
    if n >= 6:
        break
