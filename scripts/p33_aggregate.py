import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CT = ROOT / "ChinaTravel"
NAT = ROOT / "results/p33_native_planner"

RUNS = [
    ("easy", "ShortTrip_easy", "ShortTrip_easy_fix"),
    ("medium", "ShortTrip_medium", "ShortTrip_medium_fix"),
    ("human", "ShortTrip_human", "ShortTrip_human_fix"),
]


def read_csv(p):
    return list(csv.DictReader(open(p, encoding="utf-8-sig")))


def rates(split, method):
    base = CT / f"eval_res/splits_{split}_p33/{method}"
    schema = read_csv(base / "schema.csv")
    common = read_csv(base / "commonsense.csv")
    logical = read_csv(base / "logical_py.csv")
    ccols = [c for c in common[0] if c != "data_id"]
    lcols = [c for c in logical[0] if c != "data_id"]
    s_pass = {r["data_id"] for r in schema if r["schema"] == "1"}
    c_pass = {r["data_id"] for r in common
              if all(str(r[c]) in ("0", "0.0", "") for c in ccols)}
    l_pass = {r["data_id"] for r in logical
              if all(str(r[c]) != "0" for c in lcols)}
    all_pass = s_pass & c_pass & l_pass
    return {
        "queries": len(schema),
        "schema_rate": round(100 * len(s_pass) / len(schema), 2),
        "commonsense_macro": round(100 * len(c_pass) / len(schema), 2),
        "logical_macro": round(100 * len(l_pass) / len(schema), 2),
        "all_pass": round(100 * len(all_pass) / len(schema), 2),
        "all_pass_uids": sorted(all_pass),
        "s_uids": s_pass, "c_uids": c_pass, "l_uids": l_pass,
    }


def main():
    out = {}
    for split, method, fix in RUNS:
        qs = {}
        for f in (CT / "chinatravel/data" / f"{split}_p33").glob("*.json"):
            q = json.loads(f.read_text(encoding="utf-8"))
            qs[q["uid"]] = q
        for label, m in (("as_is", method), ("fix", fix)):
            r = rates(split, m)
            all_uids = set(r["all_pass_uids"])
            by_days = Counter(qs[u]["days"] for u in all_uids)
            by_days_total = Counter(q["days"] for q in qs.values())
            by_city = Counter(qs[u]["target_city"] for u in all_uids)
            by_city_total = Counter(q["target_city"] for q in qs.values())
            out[f"{split}_{label}"] = {
                "queries": r["queries"],
                "schema_rate": r["schema_rate"],
                "commonsense_macro": r["commonsense_macro"],
                "logical_macro": r["logical_macro"],
                "all_pass_rate": r["all_pass"],
                "by_days": {str(d): [by_days.get(d, 0), by_days_total[d]] for d in sorted(by_days_total)},
                "by_city": {c: [by_city.get(c, 0), by_city_total[c]] for c in sorted(by_city_total)},
            }
            print(split, label, {k: out[f"{split}_{label}"][k] for k in
                                ("queries", "schema_rate", "commonsense_macro",
                                 "logical_macro", "all_pass_rate")})
    (NAT / "aggregate.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
