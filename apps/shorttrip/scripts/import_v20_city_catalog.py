"""Index the pinned V20 Xi'an and Xiamen data in ShortTrip's openGauss database."""

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
from functools import lru_cache
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import sys


CITIES = {"西安": "xian", "厦门": "xiamen"}
PLACE_KINDS = ("attraction", "restaurant", "accommodation")
PREFIX = "v20:%"
PRICE_BOUNDARY = "historical_or_benchmark_only"
RECEIPT = "city_catalog_v20_xian_xiamen"


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


@lru_cache(maxsize=None)
def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def present(value):
    return isinstance(value, str) and value.strip().lower() not in {"", "none", "nan", "null", "unknown", "未知", "待核实", "需确认"}


def number(value, minimum=0):
    return type(value) in (int, float) and math.isfinite(value) and value >= minimum


def date_present(value):
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return True


def hash_present(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


class Catalog:
    def __init__(self, installation):
        self.installation = installation
        self.accepted = {}
        self.quarantine = {}
        self.tags = set()
        self.source_counts = Counter()
        self.aliased_counts = Counter()
        self.reasons = Counter()

    def add(self, kind, city, name, path, index, data, reasons, *, row_id=None, payload=None):
        path = Path(path).resolve()
        relative = path.relative_to(self.installation).as_posix()
        self.source_counts[city, kind] += 1
        if not present(name):
            reasons.append("name")
        if row_id is None:
            row_id = sha256(f"{relative}:{index}".encode()).hexdigest()[:24]
        key = f"v20:{kind}:{row_id}"
        if key in self.accepted or key in self.quarantine:
            raise ValueError(f"Duplicate source identity: {key}")
        reasons = sorted(set(reasons))
        record = {
            **(payload or {}),
            "record_id": key, "city": city, "name": name, "kind": kind, "language": "zh",
            "data": data, "evidence_status": PRICE_BOUNDARY, "needs_live_verification": True,
            "source_locator": {
                **(payload or {}).get("source_locator", {}),
                "file": relative, "file_sha256": digest(path), "row_index_0based": index,
            },
        }
        if reasons:
            self.quarantine[key] = (key, city, kind, name, dump(reasons), dump(record))
            self.reasons.update((city, kind, reason) for reason in reasons)
            return False
        self.accepted[key] = (key, "zh", kind, city, name, dump(record))
        access = record.get("access", {})
        attributes = {
            "grade": [access.get("grade")],
            "category": data.get("category_values") or [],
            "cuisine": data.get("cuisine_values") or [],
        }
        self.tags.update((key, tag, value) for tag, values in attributes.items() for value in values
                         if present(value) and value != "unknown_not_reconstructed")
        return True

    def place_rows(self, sandbox, city, coordinate_check):
        accepted_names, blocked_names = set(), set()
        for kind in PLACE_KINDS:
            path, _, rows, _, _, aliases, _ = sandbox._catalog(kind, city)
            self.aliased_counts[city, kind] = len(aliases)
            for index, row in enumerate(rows):
                if index in aliases:
                    continue
                item = sandbox._record(kind, city, index)
                payload = item["payload"]
                data, access = payload["data"], payload["access"]
                reasons = list(access["planning_required_missing"])
                if not present(row.get("id")):
                    reasons.append("source_id")
                if access["grade"] == "L4":
                    reasons.append("source_grade_L4")
                if not access["planning_position_available"] or not coordinate_check([data.get("lat"), data.get("lon")]):
                    reasons.append("verified_position")
                if kind == "accommodation":
                    if str(row.get("numbed_source_status") or "").startswith("assumed"):
                        reasons.append("verified_bed_count")
                    if access["price_source_status"] == "historical_source_reference_conditional":
                        reasons.append("verified_price_unit")
                if not access["main_path"] and not reasons:
                    reasons.append("source_not_admitted")
                source = {**payload, "source_record_id": item["record_id"]}
                if reasons:
                    source["raw_record"] = row
                eligible = self.add(kind, city, item["name"], path, index, data, reasons,
                                    row_id=f"{CITIES[city]}:{row['id']}" if present(row.get("id")) else None,
                                    payload=source)
                names = accepted_names if eligible else blocked_names
                names.add(item["name"])
                names.update(alias["name"] for alias in payload.get("aliases", []) if present(alias.get("name")))
        return blocked_names - accepted_names

    def local_rows(self, sandbox):
        from chinatravel.environment.tools.transportation.apis import _city_poi_reference, _normalize_station_position

        metro_path = sandbox.db / "transportation/subways.json"
        metro = read(metro_path)
        for city, slug in CITIES.items():
            reference = _city_poi_reference(slug, metro_path)
            if reference is None:
                raise ValueError(f"No coordinate reference for {city}")

            def coordinate_check(position):
                if not isinstance(position, (list, tuple)) or len(position) != 2:
                    return False
                lat, lon = position
                return (number(lat, 15) and number(lon, 70) and lat <= 55 and lon <= 140
                        and abs(lat - reference["latitude"]) <= 2 and abs(lon - reference["longitude"]) <= 3)

            blocked_names = self.place_rows(sandbox, city, coordinate_check)
            poi_path = sandbox.db / "poi" / slug / "poi.json"
            for index, poi in enumerate(read(poi_path)):
                reasons = []
                if not coordinate_check(poi.get("position")):
                    reasons.append("verified_position")
                if poi.get("name") in blocked_names:
                    reasons.append("linked_place_quarantined")
                self.add("poi", city, poi.get("name"), poi_path, index,
                         {**poi, "use_scope": "location_index_only"}, reasons)

            for line_index, line in enumerate(metro[slug]):
                for station_index, row in enumerate(line["stations"]):
                    position = _normalize_station_position(row.get("position"), reference)
                    reasons = [] if present(line.get("name")) else ["metro_line"]
                    if position["state"] != "accepted":
                        reasons.append(position["reason"])
                    data = {
                        **row, "line": line.get("name"), "line_index_0based": line_index,
                        "source_station_index_0based": station_index, "position": position["normalized_position"],
                        "coordinate_order": position["coordinate_order"], "raw_position": row.get("position"),
                        "use_scope": "historical_station_line_membership",
                    }
                    self.add("metro", city, row.get("name"), metro_path, [line_index, station_index], data, reasons,
                             row_id=f"{slug}:{line_index}:{station_index}")

    def transport_rows(self, sandbox):
        from chinatravel.environment.airports import airport_matches
        from sandbox_adapter import _time_valid

        root = sandbox.db / "intercity_transport"

        def admit_schedule(kind, row, path, index, origin, destination, city):
            id_field = "TrainID" if kind == "train" else "FlightID"
            reasons = [key for key in (id_field, "From", "To") if not present(row.get(key))]
            reasons.extend(key for key in ("BeginTime", "EndTime") if not _time_valid(row.get(key)))
            if not number(row.get("Duration")) or row["Duration"] <= 0:
                reasons.append("Duration")
            price = row.get("Cost")
            fare = {"value_cny": price, "scope": "undated_frozen_snapshot"}
            if kind == "train" and number(row.get("BenchmarkHistoricalCost")):
                if (date_present(row.get("BenchmarkFareDate")) and present(row.get("BenchmarkFareSeat"))
                        and hash_present(row.get("BenchmarkFareEvidenceSHA256"))
                        and present(row.get("BenchmarkFareSource"))):
                    fare = {
                        "value_cny": row["BenchmarkHistoricalCost"], "scope": "historical_fare_reference",
                        "observation_date": row["BenchmarkFareDate"], "seat": row["BenchmarkFareSeat"],
                    }
                else:
                    reasons.append("fare_provenance")
            if not number(fare["value_cny"]) or fare["value_cny"] <= 0:
                reasons.append("fare_cny")
            if not present(origin) or not present(destination) or origin == destination:
                reasons.append("origin_destination")
            data = {**row, "origin": origin, "destination": destination, "fare": fare,
                    "use_scope": "historical_or_benchmark_timetable"}
            self.add(kind, city, row.get(id_field), path, index, data, reasons)

        for path in sorted((root / "train").glob("from_*_to_*.json")):
            origin, destination = path.stem.removeprefix("from_").split("_to_")
            matched = [city for city in (origin, destination) if city in CITIES]
            if matched:
                for index, row in enumerate(read(path)):
                    admit_schedule("train", row, path, index, origin, destination, matched[0])

        path = root / "airplane.jsonl"
        with path.open(encoding="utf-8-sig") as stream:
            for index, line in enumerate(stream):
                if not line.strip():
                    continue
                row = json.loads(line)
                ends = [[city for city in sandbox.cities if airport_matches(row.get(end), city, row.get(end + "Name"))]
                        for end in ("From", "To")]
                matched = [city for candidates in ends for city in candidates if city in CITIES]
                if matched:
                    origin, destination = [hits[0] if len(hits) == 1 else None for hits in ends]
                    admit_schedule("flight", row, path, index, origin, destination, matched[0])

        path = self.installation / "sandbox_profiles" / Path(sandbox.db).parent.name / "runtime/dated_transport.json"
        for index, row in enumerate(read(path)["observations"]):
            matched = [city for city in (row.get("origin"), row.get("destination")) if city in CITIES]
            if not matched:
                continue
            mode = row["mode"]
            kind = {"train": "train_observation", "airplane": "flight_observation"}[mode]
            reasons = [key for key in ("service", "origin", "destination", "from", "to", "seat")
                       if not present(row.get(key))]
            try:
                departure = datetime.fromisoformat(row["departure"])
                arrival = datetime.fromisoformat(row["arrival"])
                elapsed = (arrival - departure).total_seconds() / 60
                if elapsed <= 0 or elapsed != row.get("minutes"):
                    reasons.append("duration_minutes")
            except (KeyError, TypeError, ValueError):
                reasons.append("departure_arrival_date_time")
            if not number(row.get("fare_cny")) or row["fare_cny"] <= 0:
                reasons.append("fare_cny")
            source = row.get("source") or {}
            if (not present(source.get("url")) or not hash_present(source.get("sha256"))
                    or not present(source.get("observed_at_utc"))):
                reasons.append("fare_provenance")
            self.add(kind, matched[0], row.get("service"), path, index,
                     {**row, "use_scope": "dated_display_quote_only"}, reasons)

    def summary(self):
        accepted = Counter((v[3], v[2]) for v in self.accepted.values())
        quarantine = Counter((v[1], v[2]) for v in self.quarantine.values())
        return {
            "total_accepted": len(self.accepted),
            "total_quarantined": len(self.quarantine),
            "tags": len(self.tags),
            "counts": [
                {"city": city, "kind": kind, "source": self.source_counts[city, kind] + self.aliased_counts[city, kind],
                 "accepted": accepted[city, kind], "quarantined": quarantine[city, kind],
                 "aliases": self.aliased_counts[city, kind],
                 "quarantine_reasons": {key: n for (c, k, key), n in sorted(self.reasons.items())
                                        if (c, k) == (city, kind)}}
                for city, kind in sorted(self.source_counts)
            ],
        }


def store(db, snapshot, commit, profile, receipt_sha, catalog, summary):
    from shorttrip_cloud.db import execute_batch

    tables = (
        ("st_catalog_record", "id, lang, kind, city, name, payload", "id", catalog.accepted.values()),
        ("st_catalog_quarantine", "id, city, kind, name, reasons, payload", "id", catalog.quarantine.values()),
        ("st_catalog_tag", "record_id, tag, value", "record_id", catalog.tags),
    )
    with db.tx() as cur:
        cur.execute("SELECT commit_sha, profile FROM st_snapshot WHERE id=%s FOR UPDATE", (snapshot,))
        if cur.fetchone() != (commit, profile):
            raise ValueError(f"Unexpected database source for {snapshot}")
        cur.execute("SELECT sha256 FROM st_snapshot_file WHERE snapshot_id=%s AND path=%s",
                    (snapshot, f"sandbox_profiles/{profile}/receipt.json"))
        if cur.fetchone() != (receipt_sha,):
            raise ValueError("Database and verified local source receipts differ")
        for table, columns, key, expected in tables:
            query = f"SELECT {columns} FROM {table} WHERE snapshot_id=%s AND {key} LIKE %s"
            cur.execute(query, (snapshot, PREFIX))
            current = cur.fetchall()
            if not current:
                rows = [(snapshot, *row) for row in sorted(expected)]
                slots = ",".join(["%s"] * (len(columns.split(",")) + 1))
                execute_batch(cur, f"INSERT INTO {table} (snapshot_id, {columns}) VALUES ({slots})", rows)
                cur.execute(query, (snapshot, PREFIX))
                current = cur.fetchall()
            if len(current) != len(expected) or set(current) != set(expected):
                raise ValueError(f"Read-back mismatch in {table}; no catalog changes committed")
        cur.execute("SELECT value FROM st_meta WHERE key=%s", (RECEIPT,))
        stored = cur.fetchone()
        encoded = dump(summary)
        if stored is None:
            cur.execute("INSERT INTO st_meta (key, value) VALUES (%s, %s)", (RECEIPT, encoded))
        elif stored != (encoded,):
            raise ValueError("Stored city import receipt differs from the verified input batch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--check", action="store_true", help="validate the snapshot and calculate counts without writing")
    args = parser.parse_args()
    release = args.release.resolve()
    planner = release / "combined version_personalized"
    sys.path[:0] = [str(release), str(planner)]
    from chinatravel.environment.sandbox.__main__ import configuration
    from chinatravel.environment.sandbox.v20 import COMMIT, PROFILE, RECEIPT_SHA256
    from shorttrip_cloud.config import load
    from shorttrip_cloud.db import Database

    snapshot = COMMIT[:7]
    installation = release / "ShortTrip/artifacts/data" / snapshot
    os.environ.pop("CT_TRAVEL_START_DATE", None)
    os.environ.pop("CT_TRAVEL_END_DATE", None)
    os.environ.update(configuration(installation))
    from chinatravel.environment.planning_access import _sandbox

    sandbox = _sandbox()
    catalog = Catalog(installation)
    catalog.local_rows(sandbox)
    catalog.transport_rows(sandbox)
    if not catalog.accepted or not catalog.quarantine:
        raise ValueError("Expected accepted and quarantined records in this batch")
    summary = {"snapshot": snapshot, "commit": COMMIT, "profile": PROFILE, "source_receipt_sha256": RECEIPT_SHA256,
               **catalog.summary()}
    if not args.check:
        db = Database(load())
        try:
            db.ensure_schema()
            store(db, snapshot, COMMIT, PROFILE, RECEIPT_SHA256, catalog, summary)
        finally:
            db.close()
    report = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    if args.report is not None:
        args.report.write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
