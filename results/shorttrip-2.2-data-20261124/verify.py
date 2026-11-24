"""Verify the two ShortTrip free-attraction acceptance rounds."""

import argparse
from collections import Counter
import csv
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import sys


REPORT = Path(__file__).resolve().parent
REPO = REPORT.parents[1]
REVIEWED_BASIS = "reviewed_public_free_access"
CITIES = ("厦门", "西安")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_bytes())


def freeze(row):
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


@lru_cache(maxsize=None)
def source_rows(relative_path, sha256):
    path = REPO / relative_path
    require(hashlib.sha256(path.read_bytes()).hexdigest() == sha256, f"Source changed: {relative_path}")
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def verify_catalog(rounds, figures):
    manifest = read(REPO / "apps/shorttrip/references/v20-reviewed-free-places.json")["places"]
    all_rows = [row for batch in rounds for row in batch["places"]]
    require(len({row["id"] for row in all_rows}) == len(all_rows) == 296, "Duplicate or missing decisions")
    require(len(manifest) == len(all_rows), "Review manifest count differs")
    by_id = {row["id"]: row for row in manifest}

    catalogs = {}
    for label, expected in (("baseline", {"厦门": 95, "西安": 135}), ("final", {"厦门": 270, "西安": 256})):
        doc = read(REPORT / f"catalog-{label}.json")
        require(doc["catalog_snapshot"] == figures["base_catalog_commit"][:7], "Catalog revision differs")
        catalog = doc["free_attraction_references"]
        require(Counter(row["city"] for row in catalog) == expected, f"Wrong {label} catalog counts")
        require(all(row["amount_cny"] == 0 for row in catalog), f"Nonzero {label} admission")
        catalogs[label] = catalog
    final = catalogs["final"]
    retained = [row for row in final if row["basis"] != REVIEWED_BASIS]
    require(Counter(map(freeze, retained)) == Counter(map(freeze, catalogs["baseline"])),
            "A baseline reference changed")
    additions = {(row["city"], row["name"], freeze(row["source_locator"])): row
                 for row in final if row["basis"] == REVIEWED_BASIS}
    require(len(additions) == len(all_rows), "Catalog additions differ from review scope")

    expected_counts = ((146, 33, 48, 26), (29, 9, 73, 11))
    cumulative = len(catalogs["baseline"])
    for index, (batch, counts) in enumerate(zip(rounds, expected_counts), start=1):
        observed = {}
        for city_index, city in enumerate(CITIES):
            rows = [r for r in batch["places"] if r["city"] == city]
            total, planned = counts[city_index * 2:city_index * 2 + 2]
            require(len(rows) == total and sum(row["planner_eligible"] for row in rows) == planned,
                    f"Round {index} counts differ for {city}")
            observed[city] = {"reviewed": total, "planner_eligible": planned,
                              "reference_only": total - planned}
        cumulative += len(batch["places"])
        require(figures["rounds"][index - 1] == {
            "round": index, "by_city": observed, "catalog_total": cumulative,
        }, f"Round {index} summary differs")
        require(batch["planner_snapshot"] == figures["planner_snapshots"][index]["id"], "Planner revision differs")
        for row in batch["places"]:
            identity = row["id"]
            decision = by_id[identity]
            require(all(row[key] == value for key, value in decision.items()), f"Review evidence differs: {identity}")
            require(type(row["planner_eligible"]) is bool and (not row["planner_eligible"] or row["trial_allowed"]),
                    f"Unapproved planner entry: {identity}")
            source = row["source_locator"]
            original = source_rows(source["file"], source["file_sha256"])[source["row_index_0based"]]
            require(original["id"] == identity.rsplit(":", 1)[-1] and original["name"] == row["name"],
                    f"Source row differs: {identity}")
            added = additions.pop((row["city"], row["name"], freeze(source)))
            require(added["amount_cny"] == row["catalog_admission_cny"] == 0
                    and all(added[key] == row[key] for key in ("scope", "reason", "reviewed_on", "trial_allowed"))
                    and added["source_urls"] == row["urls"], f"Catalog evidence differs: {identity}")
    require(not additions, "Unchecked catalog additions")
    print("Catalog and V20 source rows verified: 296 reviewed, 79 planner-eligible, 217 reference-only.")


def verify_planner(release, rounds, figures):
    sys.path.insert(0, str(release / "combined version_personalized"))
    from chinatravel.environment.sandbox.__main__ import configuration, default_installation

    installation = default_installation()
    os.environ.update(configuration(installation))
    sys.path.insert(0, os.environ["CT_SANDBOX_RUNTIME_DIR"])
    from sandbox_adapter import Sandbox
    from shorttrip_planner_preview import policy, sandbox_for

    for index, batch in enumerate(rounds, start=1):
        snapshot = batch["planner_snapshot"]
        path = installation.parent / snapshot / "reference-preview.json"
        require(hashlib.sha256(path.read_bytes()).hexdigest() == figures["planner_snapshots"][index]["sha256"],
                f"Planner snapshot bytes differ: {snapshot}")
        os.environ["SHORTTRIP_REFERENCE_PREVIEW"] = str(path)
        policy.cache_clear()
        sandbox = sandbox_for(Sandbox)
        for city in CITIES:
            accepted = {item["record_id"]: item["payload"]["data"]
                        for _, item in sandbox._eligible("attraction", city)}
            for row in batch["places"]:
                if row["city"] != city:
                    continue
                identity = row["id"].removeprefix("v20:")
                require((identity in accepted) == row["planner_eligible"], f"Planner result differs: {identity}")
                if identity in accepted:
                    visit = accepted[identity]
                    require(visit["price"] == 0 and visit["opentime"] and visit["endtime"],
                            f"Missing planner price or time: {identity}")
        print(f"Planner round {index} passed: {len(batch['places'])} rows ({snapshot}).")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, help="Replay both rounds from an installed ShortTrip 2.2 release.")
    args = parser.parse_args()
    rounds = [read(REPORT / f"round-{index}.json") for index in (1, 2)]
    figures = read(REPORT / "verification.json")
    verify_catalog(rounds, figures)
    if args.release:
        verify_planner(args.release.resolve(), rounds, figures)


if __name__ == "__main__":
    main()
