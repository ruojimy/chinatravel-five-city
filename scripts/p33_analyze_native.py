import csv, json, collections, re
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "ChinaTravel"


def load_q(split):
    split = split.replace("_p33", "")
    d = {}
    for f in (root / "chinatravel/data" / f"{split}_p33").glob("*.json"):
        q = json.loads(f.read_text(encoding="utf-8"))
        d[q["uid"]] = q
    return d


def categorize(text):
    if "cost" in text or "price" in text:
        return "budget/cost"
    if "activity_tickets" in text:
        return "tickets"
    if "attraction_names" in text or "activity_position(activity)" in text:
        return "required attraction"
    if "restaurant_names" in text or "['breakfast', 'lunch', 'dinner']" in text:
        return "restaurant"
    if "hotel_names" in text or "hotel_feature" in text:
        return "hotel"
    if "room" in text:
        return "room"
    if "transport" in text or "go_start_time" in text or "return_start_time" in text:
        return "transport/time"
    if "day_count" in text or "dayactivities" in text or "attraction_count" in text:
        return "days/count"
    if "people_count" in text:
        return "people"
    return "other"


for split, method in (("easy_p33", "ShortTrip_easy"),
                      ("medium_p33", "ShortTrip_medium"),
                      ("human_p33", "ShortTrip_human")):
    qs = load_q(split)
    rows = list(csv.DictReader(open(
        root / f"eval_res/splits_{split}/{method}/logical_py.csv", encoding="utf-8-sig")))
    cols = [c for c in rows[0] if c != "data_id"]
    print("=" * 22, split, "queries", len(rows), "constraints", len(cols))
    per_index = []
    for c in cols:
        vals = [int(r[c]) for r in rows if r[c] != ""]
        per_index.append((sum(vals) / len(vals) if vals else None, c))
    for rate, c in sorted(per_index)[:8]:
        print(f"  weakest idx {c}: {rate:.2%}")

    cat = collections.Counter()
    examples = {}
    failed_queries = set()
    for r in rows:
        q = qs.get(r["data_id"])
        if not q:
            continue
        logic = q.get("hard_logic_py") or []
        for i, c in enumerate(cols):
            if r.get(c) == "0":
                text = logic[i] if i < len(logic) else ""
                k = categorize(text)
                cat[k] += 1
                failed_queries.add(r["data_id"])
                examples.setdefault(k, (r["data_id"], text[:180]))
    print("  failed constraints by category:", cat.most_common())
    print("  queries with >=1 hard failure:", len(failed_queries), "/", len(rows))
    for k, (uid, t) in examples.items():
        print("   example", k, uid, t.replace("\n", " "))
