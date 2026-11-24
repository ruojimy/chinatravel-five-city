"""Verify the published acceptance receipts and derive comparable counts."""
from collections import Counter
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ARCHIVE = REPO / "results/v19-20261118"
STANDARD = ARCHIVE / "luna_v19_standard_36"


def read(path):
    return json.loads(path.read_bytes())


def by_id(items):
    rows = {r["id"]: r for r in items}
    if len(rows) != len(items):
        raise ValueError("Duplicate case IDs")
    return rows


def verify():
    data = read(HERE / "data-replay.json")
    run = read(HERE / "rule-planning.json")
    scored = read(HERE / "benchmark-scores.json")
    manifest = read(STANDARD / "public/manifest.json")["cases"]
    plans, scores, transport = map(by_id, (run["cases"], scored["cases"], data["transport_cases"]))
    assert manifest.keys() == plans.keys() == scores.keys() == transport.keys() and len(manifest) == 36
    assert data["snapshot"] == run["snapshot"] == scored["snapshot"] == "trial-" + data["overlay_sha256"][:24]
    assert len(data["catalog_by_city"]) == 12
    for uid, plan in plans.items():
        score = scores[uid]
        assert plan["destination"] == transport[uid]["destination"]
        if plan["state"] == "complete":
            assert score["overall"] in ("pass", "fail", "unknown")
            text = json.dumps(plan["recommended_itinerary"], ensure_ascii=False)
            assert score["plan_sha256"] in {
                hashlib.sha256((text + newline).encode("utf-8")).hexdigest() for newline in ("\n", "\r\n")
            }
            assert score["query_sha256"] == hashlib.sha256((STANDARD / "private" / f"{uid}.json").read_bytes()).hexdigest()
        else:
            assert score["overall"] == "no_plan"

    def metrics(ids):
        return {
            "total": len(ids), "executed": sum(plans[i]["state"] != "execution_error" for i in ids),
            "accepted_by_shorttrip": sum(plans[i]["state"] == "complete" for i in ids),
            "passes_original_rules": sum(scores[i]["overall"] == "pass" for i in ids),
            "priced_roundtrip": sum(transport[i]["priced_roundtrip_found"] for i in ids),
            "intercity_fare_within_budget": sum(transport[i]["within_intercity_budget"] for i in ids),
        }

    overall = metrics(list(plans))
    assert tuple(overall.values()) == (36, 36, 20, 16, 36, 35)
    db = data["database"]
    assert data["snapshot"] in db["active_snapshots"]
    candidate = db["supplemental_xiamen_flights"]
    assert candidate["record_count"] == 432 and candidate["active"] is False
    counts = {key: sum(row["rows"] for row in values) for key, values in db["lookup_counts"].items()}
    assert counts == {"catalog": 9216, "reference": 1607, "quarantine": 7557}
    receipts = read(REPO / "results/shorttrip-2.2-data-20261124/verification.json")
    assert receipts["database_readback"]["free_catalog_by_city"] == {"厦门": 270, "西安": 256}
    for city in ("厦门", "西安"):
        assert data["catalog_by_city"][city]["accommodation"]["eligible_hotel_price_below_10"] == 0

    print(json.dumps({
        "overall": overall,
        "by_city": {city: metrics([uid for uid, p in plans.items() if p["destination"] == city])
                    for city in ("西安", "厦门")},
        "by_difficulty": {level: metrics([uid for uid, p in plans.items() if p["difficulty"] == code])
                          for code, level in (("e", "Easy"), ("m", "Medium"), ("h", "Human"))},
        "planning_states": dict(Counter(p["state"] for p in plans.values())),
        "original_rule_results": dict(Counter(s["overall"] for s in scores.values())),
        "db_lookup_counts": {**counts, "pending": counts["quarantine"] - counts["reference"]},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    verify()
