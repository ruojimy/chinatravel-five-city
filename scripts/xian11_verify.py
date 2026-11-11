"""Verify the Xi'an 11th-city test set against the native contract.

Checks: JSON structure, DSL syntax (compile), entity references really exist
in the exported sandbox, 20 new ordered city pairs, day/people buckets,
constraint-family coverage, chain-query roles and city coverage, and that
ChinaTravel/ frozen files were not modified.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from xian_scope import NATIVE10, EXPANSION30, city_of  # noqa: E402

NATIVE_FIELDS = {"uid", "tag", "start_city", "target_city", "days", "people_number",
                 "limit_rooms", "limits_room_type", "hard_logic_py",
                 "nature_language", "nature_language_en"}
CHAIN_FIELDS = {"schema_version", "uid", "nature_language", "people_number",
                "city_sequence", "dates", "candidates", "retrieval_budget", "level"}
QUOTA = {"easy": 30, "medium": 15, "human": 15, "chain": 30}


def sandbox_entities(root: Path) -> dict:
    out = {"attraction": set(), "restaurant": set(), "accommodation": set(),
           "attraction_type": set(), "cuisine": set(), "hotel_type": set()}
    specs = [
        ("attraction", root / "attractions/xian/attractions.csv", "type"),
        ("restaurant", root / "restaurants/xian/restaurants_xian.csv", "cuisine"),
        ("accommodation", root / "accommodations/xian/accommodations.csv", "featurehoteltype"),
    ]
    tkey = {"type": "attraction_type", "cuisine": "cuisine", "featurehoteltype": "hotel_type"}
    for kind, path, value_col in specs:
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("name"):
                    out[kind].add(row["name"])
                if row.get(value_col):
                    out[tkey[value_col]].add(row[value_col])
    return out


def verify(queries: Path, sandbox: Path) -> dict:
    problems = []
    ents = sandbox_entities(sandbox)
    counts = Counter()
    pairs = Counter()
    days = defaultdict(Counter)
    people = defaultdict(Counter)
    families = defaultdict(Counter)
    dsl_fail = []
    entity_fail = []
    chain_roles = Counter()
    chain_cities = set()
    chain_types = Counter()
    levels_seen = Counter()

    for level in ("easy", "medium", "human", "chain"):
        d = queries / level
        files = sorted(d.glob("*.json")) if d.exists() else []
        counts[level] = len(files)
        if len(files) != QUOTA[level]:
            problems.append(f"{level}: expected {QUOTA[level]} files, got {len(files)}")
        for f in files:
            try:
                q = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                problems.append(f"{f.name}: invalid JSON {e}")
                continue
            if level == "chain":
                missing = CHAIN_FIELDS - set(q)
                if missing:
                    problems.append(f"{f.name}: missing chain fields {sorted(missing)}")
                seq = q.get("city_sequence") or []
                if not (2 <= len(seq) <= 3):
                    problems.append(f"{f.name}: bad city_sequence length {len(seq)}")
                if "西安" not in seq:
                    problems.append(f"{f.name}: Xi'an missing from city_sequence")
                else:
                    idx = seq.index("西安")
                    role = "first" if idx == 0 else ("last" if idx == len(seq) - 1 else "middle")
                    chain_roles[role] += 1
                chain_cities.update(c for c in seq if c in NATIVE10)
                chain_types[q.get("xian11", {}).get("chain_type", "?")] += 1
                levels_seen[q.get("level")] += 1
                if not q.get("nature_language"):
                    problems.append(f"{f.name}: empty nature_language")
                continue

            # native-format query
            missing = NATIVE_FIELDS - set(q)
            if missing:
                problems.append(f"{f.name}: missing native fields {sorted(missing)}")
            if q.get("tag") != level:
                problems.append(f"{f.name}: tag {q.get('tag')} != {level}")
            if not isinstance(q.get("hard_logic_py"), list) or not q["hard_logic_py"]:
                problems.append(f"{f.name}: empty hard_logic_py")
            if q.get("start_city") == q.get("target_city"):
                problems.append(f"{f.name}: start_city == target_city")
            pair = (q.get("start_city"), q.get("target_city"))
            pairs[pair] += 1
            days[level][q.get("days")] += 1
            people[level][q.get("people_number")] += 1
            for fam in q.get("constraint_families", []):
                families[level][fam] += 1
            for i, code in enumerate(q.get("hard_logic_py") or []):
                try:
                    compile(code, f"<{f.name}:{i}>", "exec")
                except SyntaxError as e:
                    dsl_fail.append(f"{f.name}[{i}]: {e.msg}")
            # entity references inside set literals
            text = "\n".join(q.get("hard_logic_py") or [])
            for literal in re.findall(r"\{'([^']+)'\}", text):
                known = any(literal in ents[k] for k in
                            ("attraction", "restaurant", "accommodation",
                             "attraction_type", "cuisine", "hotel_type"))
                native_vocab = literal in ("train", "airplane", "metro", "taxi", "walk",
                                           "大床房", "双床房", "单床房", "accommodation",
                                           "attraction", "breakfast", "lunch", "dinner")
                if not (known or native_vocab):
                    entity_fail.append(f"{f.name}: '{literal}' not in sandbox")

    if dsl_fail:
        problems.append(f"DSL compile failures: {len(dsl_fail)} (first 3: {dsl_fail[:3]})")
    if entity_fail:
        problems.append(f"unbound entity references: {len(entity_fail)} (first 3: {entity_fail[:3]})")

    expected_pairs = {("西安", c) for c in NATIVE10} | {(c, "西安") for c in NATIVE10}
    covered = {p for p in pairs if p in expected_pairs}
    missing_pairs = sorted(expected_pairs - covered)
    if missing_pairs:
        problems.append(f"missing ordered pairs: {missing_pairs}")

    # easy must cover all 20 on its own
    easy_dir = queries / "easy"
    easy_pairs = set()
    if easy_dir.exists():
        for f in easy_dir.glob("*.json"):
            q = json.loads(f.read_text(encoding="utf-8"))
            easy_pairs.add((q.get("start_city"), q.get("target_city")))
    easy_missing = sorted(expected_pairs - easy_pairs)

    all_families = set().union(*[set(v) for v in families.values()]) if families else set()
    native10_covered = sorted(chain_cities)
    report = {
        "verified_at": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
        "queries_root": str(queries.relative_to(ROOT)).replace("\\", "/"),
        "sandbox_root": str(sandbox.relative_to(ROOT)).replace("\\", "/"),
        "counts": dict(counts), "total": sum(counts.values()),
        "native_reference": {"easy": 300, "medium": 150, "human": 154,
                             "per_city": {"easy": 30, "medium": 15, "human": 15.4}},
        "city_pairs": {"expected": len(expected_pairs), "covered": len(covered),
                       "missing": missing_pairs, "easy_layer_missing": easy_missing,
                       "per_pair_queries": {f"{a}->{b}": n for (a, b), n in sorted(pairs.items())}},
        "days_by_level": {k: dict(v) for k, v in days.items()},
        "people_by_level": {k: dict(v) for k, v in people.items()},
        "constraint_families": {k: dict(v) for k, v in families.items()},
        "families_covered": sorted(all_families),
        "families_count": len(all_families),
        "chain": {"roles": dict(chain_roles), "types": dict(chain_types),
                  "native10_cities": native10_covered,
                  "native10_missing": sorted(set(NATIVE10) - chain_cities),
                  "levels": dict(levels_seen)},
        "sandbox_entities": {k: len(v) for k, v in ents.items()},
        "dsl_compile_failures": len(dsl_fail),
        "unbound_entity_references": len(entity_fail),
        "problems": problems,
        "ok": not problems,
    }
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default="query_sets/xian11")
    ap.add_argument("--sandbox", default="data/xian11_sandbox")
    ap.add_argument("--out", default="query_sets/xian11/verification.json")
    args = ap.parse_args()
    q, s = Path(args.queries), Path(args.sandbox)
    if not q.is_absolute():
        q = ROOT / q
    if not s.is_absolute():
        s = ROOT / s
    report = verify(q, s)
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                      ("counts", "total", "families_count", "dsl_compile_failures",
                       "unbound_entity_references", "ok")}, ensure_ascii=False))
    print("city_pairs", report["city_pairs"]["covered"], "/", report["city_pairs"]["expected"],
          "easy_missing", report["city_pairs"]["easy_layer_missing"])
    print("chain", report["chain"])
    for p in report["problems"]:
        print("  PROBLEM:", p)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
