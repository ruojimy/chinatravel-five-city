"""Replay the catalog, openGauss, and 36-case transport data acceptance checks."""
import argparse
from collections import Counter
from datetime import timedelta
from functools import lru_cache
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
BASE = "6de12f4"
PREVIEW = "trial-5e2d7c000735607f6ada8c42"
CITIES = ("厦门", "西安")
KINDS = ("attraction", "restaurant", "accommodation")
sys.path.insert(0, str(REPO / "scripts"))
from replay_benchmark12_v20 import FIRST, dated_pairs, intercity_lower_bound, service_rows


def read(path):
    return json.loads(path.read_bytes())


def number(value):
    try:
        v = float(value)
        return v if isfinite(v) and v >= 0 else None
    except (TypeError, ValueError):
        return None


def catalogs(box):
    out = {}
    for city in box.cities:
        out[city] = {}
        for kind in KINDS:
            _, _, raw, _, _, _, _ = box._catalog(kind, city)
            listing = box.catalog_list(kind, city, limit=1)
            assert len(raw) == listing["source_row_count"]
            ready = [r for _, r in box._eligible(kind, city)]
            priced = [r for r in ready if number(r["payload"]["data"].get("price")) is not None]
            operating = ("numbed",) if kind == "accommodation" else ("opentime", "endtime")
            if kind == "accommodation":
                complete = [r for r in priced if (number(r["payload"]["data"].get("numbed")) or 0) >= 1]
            else:
                complete = [r for r in priced if all(r["payload"]["data"].get(key) for key in operating)]
            out[city][kind] = {
                "source_rows": len(raw), "exact_poi": listing["exact_poi_rows"],
                "aliases": listing["aliased_rows"], "unresolved_poi": listing["unresolved_rows"],
                "discoverable": listing["catalog_total"], "sandbox_eligible": len(ready),
                "eligible_with_price": len(priced), "eligible_with_price_and_operating_fields": len(complete),
                "source_price_missing_or_placeholder": sum(number(row.get("price")) is None for row in raw),
                "source_beds_or_hours_missing": sum(
                    (number(row.get("numbed")) or 0) < 1 if kind == "accommodation"
                    else any(not row.get(field) for field in operating) for row in raw
                ),
                "eligible_hotel_price_below_10": sum(number(r["payload"]["data"]["price"]) < 10 for r in priced)
                if kind == "accommodation" else None,
            }
    return out


def transport_suite(box, inputs):
    @lru_cache(maxsize=None)
    def find(origin, destination, mode, day=None):
        result = box.intercity_search(origin, destination, mode, travel_date=day)
        if result["errors"]:
            raise RuntimeError("Transport search failed")
        return service_rows(result, mode), result["dated_observations"]

    rows = []
    for uid, case in inputs.items():
        a, b = case["origin"], case["destination"]
        days, people, budget = case["days"], case["party"], case["budget"]
        finish = FIRST + timedelta(days=days - 1)
        undated, dated = [], []
        for origin, destination, day in [(a, b, FIRST), (b, a, finish)]:
            undated.append([r for mode in case["allowed_modes"] for r in find(origin, destination, mode)[0]])
            dated.append([r for mode in case["allowed_modes"]
                          for r in find(origin, destination, mode, day.isoformat())[1]])
        historic = intercity_lower_bound(*undated, days)
        display, _ = dated_pairs(*dated, finish, people, budget)
        fares = [historic["fare_per_person"] * people] if historic else []
        if display:
            fares.append(display["party_displayed_fare"])
        fare_floor = round(min(fares), 2) if fares else None
        rows.append({"id": uid, "destination": b, "difficulty": case["difficulty"],
                     "origin": a, "allowed_modes": case["allowed_modes"], "days": days, "people": people,
                     "budget": budget, "priced_roundtrip_found": bool(fares),
                     "minimum_reference_fare": fare_floor,
                     "within_intercity_budget": bool(fares) and (budget is None or fare_floor <= budget),
                     "historic_roundtrip": historic, "dated_observations_roundtrip": display})
    return rows


def read_database(release, overlay_hash):
    sys.path.insert(0, str(release))
    from shorttrip_cloud.config import load
    from shorttrip_cloud.db import Database

    version = "workbench-8795-reference-2.2"
    db = Database(load())
    try:
        with db.tx() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SELECT version()")
            assert "opengauss" in cur.fetchone()[0].lower()
            cur.execute("SELECT snapshot_ids FROM st_release WHERE version=%s", (version,))
            active = cur.fetchone()[0].split(",")
            assert BASE in active and PREVIEW in active
            cur.execute(
                "SELECT id, file_count FROM st_snapshot WHERE id IN (%s,%s,%s)",
                (BASE, PREVIEW, "xmn-flight-20261124-c73acb03bf"),
            )
            files = dict(cur.fetchall())
            cur.execute("SELECT sha256 FROM st_snapshot_file WHERE snapshot_id=%s AND path=%s",
                        (PREVIEW, "reference-preview.json"))
            assert cur.fetchone()[0] == overlay_hash
            flight_snapshot = "xmn-flight-20261124-c73acb03bf"
            cur.execute(
                "SELECT COUNT(*) FROM st_catalog_record WHERE snapshot_id=%s AND kind=%s",
                (flight_snapshot, "flight_observation"),
            )
            supplemental_flights = {"snapshot": flight_snapshot, "record_count": cur.fetchone()[0],
                                    "active": flight_snapshot in active}
            counts = {}
            for scope, table in (("catalog", "st_catalog_record"), ("reference", "st_catalog_reference"),
                                 ("quarantine", "st_catalog_quarantine")):
                cur.execute(f"SELECT city, kind, COUNT(*) FROM {table} WHERE snapshot_id=%s GROUP BY city,kind", (BASE,))
                counts[scope] = [{"city": a, "kind": b, "rows": n} for a, b, n in sorted(cur.fetchall())]
            cur.execute("SELECT reasons FROM st_catalog_quarantine WHERE snapshot_id=%s", (BASE,))
            reasons = Counter(reason for (raw,) in cur.fetchall() for reason in json.loads(raw))
            return {"backend": "openGauss", "active_release": version, "active_snapshots": active,
                    "snapshot_file_counts": files, "lookup_counts": counts, "quarantine_reasons": dict(reasons),
                    "supplemental_xiamen_flights": supplemental_flights}
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", action="store_true")
    args = parser.parse_args()
    release = args.release.resolve()
    sys.path.insert(0, str(release / "combined version_personalized"))
    from chinatravel.environment.sandbox.__main__ import configuration
    data = release / "ShortTrip/artifacts/data"
    overlay = data / PREVIEW / "reference-preview.json"
    os.environ["SHORTTRIP_REFERENCE_ENGINE"] = str(release / "ShortTrip/artifacts/trial-engine")
    os.environ["SHORTTRIP_REFERENCE_PREVIEW"] = str(overlay)
    os.environ["CT_XIAMEN_HISTORICAL_FARES"] = "1"
    os.environ.update(configuration(data / BASE))
    from chinatravel.environment.planning_access import _sandbox
    box = _sandbox()

    source = read(REPO / "results/v20-20261119/transport_preflight_v19_v20.json")
    cases = source["cases"]
    manifest = read(REPO / "results/v19-20261118/luna_v19_standard_36/public/manifest.json")["cases"]
    assert len(cases) == 36 and cases.keys() == manifest.keys()
    overlay_hash = hashlib.sha256(overlay.read_bytes()).hexdigest()
    assert PREVIEW == "trial-" + overlay_hash[:24]

    totals = catalogs(box)
    rows = transport_suite(box, cases)
    output = {"snapshot": PREVIEW, "overlay_sha256": overlay_hash, "sample_date": FIRST.isoformat(),
              "catalog_by_city": totals, "transport_cases": rows}
    if args.database:
        output["database"] = read_database(release, overlay_hash)
    with args.output.open("x", encoding="utf-8", newline="\n") as target:
        json.dump(output, target, ensure_ascii=False, indent=2, allow_nan=False)
        target.write("\n")
    print(f"{len(totals)} cities, {len(rows)} transport cases; "
          f"{sum(r['priced_roundtrip_found'] for r in rows)} priced roundtrips, "
          f"{sum(r['within_intercity_budget'] for r in rows)} within intercity budget.")


if __name__ == "__main__":
    main()
