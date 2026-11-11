"""Offline read-only diagnosis of the expanded snapshot, with explicit denominators.

Run from any directory with reproduction/.venv/Scripts/python.exe.
No network requests, source writes, identity merges or guessed business values.
"""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import sqlite3
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from shorttrip.freshness import POLICIES, parse_time
from shorttrip.bulk_business import gaps

SOURCE = ROOT / "data/business_catalog_v1_7_20261023T021649Z/catalog.sqlite3"
OUT = ROOT / "results/p26_dataset_diagnosis"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def known(value):
    return value is not None and value != ""


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm(value):
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    before = digest(SOURCE)
    manifest = json.loads(SOURCE.with_name("manifest.json").read_text(encoding="utf-8"))
    at = parse_time(manifest["built_at"])
    db = sqlite3.connect(SOURCE.as_uri() + "?mode=ro", uri=True)
    counts = collections.Counter()
    distributions = collections.defaultdict(collections.Counter)
    fields = collections.defaultdict(collections.Counter)
    cities = collections.defaultdict(collections.Counter)
    blockers = collections.Counter()
    families = collections.Counter()
    flags = collections.Counter()
    names = collections.defaultdict(list)
    assertion_fields = collections.Counter()
    assertion_authorities = collections.Counter()
    assertion_entities = collections.defaultdict(set)
    refs = collections.Counter()
    offer_map = collections.defaultdict(list)
    offer_summary = collections.Counter()
    examples = []
    for entity, payload in db.execute("SELECT entity_id,payload FROM room_offers"):
        o = json.loads(payload)
        offer_map[entity].append(o)
        offer_summary["offers"] += 1
        observed = parse_time(o.get("observed_at"))
        if observed:
            offer_summary["known_observation"] += 1
            offer_summary["expired_at_snapshot_300s"] += (at-observed).total_seconds() >= 300
        else:
            offer_summary["unknown_observation"] += 1
        offer_summary["with_checkin_checkout"] += bool(o.get("checkin") and o.get("checkout"))
    for kind, city, name, city_match, ready, payload, gate_text in db.execute(
        "SELECT kind,city,name,provider_city_match,planning_ready,payload,gate FROM records ORDER BY id"
    ):
        p, g = json.loads(payload), json.loads(gate_text)
        rid, data = p["record_id"], p["data"]
        counts["records"] += 1
        counts["planning_ready"] += bool(ready)
        counts["discovery_ok"] += bool(g["discovery_ok"])
        counts["entity_verified"] += p["entity_verified"] is True
        counts["provider_city_match"] += bool(city_match)
        counts["record_source_observation_known"] += parse_time(p.get("observed_at")) is not None
        counts["excluded_from_static_planning"] += bool(p.get("exclude_from_static_planning"))
        cities[city]["records"] += 1
        cities[city][kind] += 1
        cities[city]["provider_city_match"] += bool(city_match)
        for dim in ("source_id", "authority", "coordinate_system", "trust_status", "licence_status"):
            distributions[dim][p.get(dim)] += 1
        distributions["kind"][kind] += 1
        distributions["city_assignment"][p["source_locator"].get("city_assignment", "not_declared")] += 1
        blockers.update(set(g["planning_blockers"]))
        families.update({x.split(":")[0] for x in g["planning_blockers"]})
        flags.update(set(p["uncertainty_flags"]))
        names[(city, kind, norm(name))].append({"id": rid, "name": name, "lat": data["lat"], "lon": data["lon"], "coordinate_system": p["coordinate_system"]})
        for key, value in data.items():
            f = fields[(kind, key)]
            f["records"] += 1
            f["nonnull"] += value is not None
            if not known(value):
                f["empty_string"] += value == ""
                continue
            f["nonempty"] += 1
            prov = p["field_provenance"][key]
            f["status:" + prov["status"]] += 1
            observed = parse_time(prov.get("observed_at"))
            if observed:
                f["known_observation"] += 1
                age = (at - observed).total_seconds()
                ttl = POLICIES[p["field_policies"][key]][0]
                # Only observation age, NOT overall eligibility or contextual truth.
                f["within_age_ttl_only"] += -300 <= age < ttl
            else:
                f["unknown_observation"] += 1
        missing = gaps(p, offer_map[rid])
        for gap in missing:
            refs[kind + ":" + gap] += 1
        if not missing:
            counts["reference_core_complete:" + kind] += 1
            cities[city]["reference_core_complete:" + kind] += 1
        required = {
            "attraction": ("price", "opentime", "endtime", "recommendmintime", "recommendmaxtime"),
            "restaurant": ("price", "cuisine", "opentime", "endtime"),
            "accommodation": ("price", "numbed"),
        }[kind]
        complete = all(known(data.get(k)) for k in required)
        counts["native_core_complete:" + kind] += complete
        cities[city]["native_core_complete:" + kind] += complete
        h = p.get("today_hours_structured") or {}
        counts["structured_hours:" + kind] += bool(h.get("segments"))
        if h.get("segments"):
            counts["structured_hours_not_native_pair:" + kind] += not (known(data.get("opentime")) and known(data.get("endtime")))
            distributions["structured_hours_request_date"][h.get("provider_request_date")] += 1
        for a in p.get("operator_assertions", []):
            counts["operator_assertions"] += 1
            assertion_fields[a["field"]] += 1
            assertion_authorities[a["authority"]] += 1
            assertion_entities[a["field"]].add(rid)
            counts["operator_assertions_known_observation"] += parse_time(a.get("observed_at")) is not None
        if any(x in p["uncertainty_flags"] for x in ("source_city_conflicts_with_research_window", "source_property_address_conflicts_require_review", "untrusted_website_source_requires_review")):
            examples.append({"id": rid, "city": city, "kind": kind, "name": name,
                             "city_assertions": p["source_locator"].get("city_assertions"),
                             "flags": p["uncertainty_flags"]})
    ev = collections.Counter()
    ev_authority = collections.Counter()
    for (payload,) in db.execute("SELECT payload FROM evidence"):
        e = json.loads(payload)
        ev["records"] += 1
        ev["known_observation"] += parse_time(e.get("observed_at")) is not None
        ev_authority[e["authority"]] += 1
    duplicate_groups = [{"city": k[0], "kind": k[1], "normalized_name": k[2], "records": v}
                        for k, v in names.items() if len(v) > 1]
    integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    fk_errors = db.execute("PRAGMA foreign_key_check").fetchall()
    table_counts = {t: db.execute('SELECT COUNT(*) FROM "'+t+'"').fetchone()[0]
                    for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    db.close()
    after = digest(SOURCE)
    checks = {
        "source_unchanged": before == after,
        "source_hash_matches_published": before == next(x["sha256"] for x in manifest["files"] if x["file"].endswith("catalog.sqlite3")),
        "record_count_matches_manifest": counts["records"] == manifest["records"],
        "native_coverage_matches_manifest": all(fields[(kind, k[8:])]["nonnull"] == value for kind, cov in manifest["coverage"].items() for k, value in cov.items() if k.startswith("nonnull:")),
        "semantic_gap_counts_match_manifest": dict(refs) == manifest["remaining_missing_business_fields"],
        "integrity_ok": integrity == "ok", "foreign_keys_ok": not fk_errors,
        "operator_assertions_match_manifest": counts["operator_assertions"] == manifest["operator_assertions"],
    }
    report = {"source": str(SOURCE), "sha256": before, "evaluated_at_snapshot": manifest["built_at"],
              "scope": "offline exhaustive snapshot profile; no new API or LLM test; nonnull/age alone never imply eligibility",
              "counts": dict(counts), "distributions": dict(distributions),
              "blockers_per_entity": dict(blockers), "blocker_families_per_entity": dict(families),
              "uncertainty_flags_per_entity": dict(flags), "semantic_missing_fields": dict(refs),
              "evidence": dict(ev), "evidence_authorities": dict(ev_authority),
              "operator_assertion_fields": dict(assertion_fields), "operator_assertion_authorities": dict(assertion_authorities),
              "entities_per_assertion_field": {k: len(v) for k,v in assertion_entities.items()},
              "room_offers": {**dict(offer_summary), "entities": len(offer_map)},
              "candidate_duplicate_groups": len(duplicate_groups),
              "candidate_duplicate_records": sum(len(g["records"]) for g in duplicate_groups),
              "table_counts": table_counts, "checks": checks}
    # offer_map is a defaultdict accessed for each record above; use actual nonempty offers.
    report["room_offers"]["entities"] = sum(bool(v) for v in offer_map.values())
    dump(OUT / "dataset_profile.json", report)
    dump(OUT / "duplicate_candidates.json", duplicate_groups)
    dump(OUT / "flagged_examples.json", examples)
    field_rows = [{"kind": k[0], "field": k[1], **dict(v),
                   "nonnull_pct": round(100*v["nonnull"]/v["records"], 4)} for k,v in sorted(fields.items())]
    city_rows = [{"city": k, **dict(v)} for k,v in sorted(cities.items())]
    for filename, rows in (("field_coverage.csv", field_rows), ("city_coverage.csv", city_rows)):
        headers = sorted({k for row in rows for k in row})
        with (OUT / filename).open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, headers)
            w.writeheader(); w.writerows(rows)
    dump(OUT / "field_coverage.json", field_rows)
    dump(OUT / "city_coverage.json", city_rows)
    print(json.dumps({"counts": counts, "checks": checks, "output": str(OUT)}, ensure_ascii=False, indent=2))
    if not all(checks.values()):
        raise SystemExit("Profile disagrees with published snapshot; inspect checks")


if __name__ == "__main__":
    main()
