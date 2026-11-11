"""Quality-tiered access for the 11th city, aligned with the ORIGINAL 10-city baseline.

The frozen ChinaTravel database is 99.5-100% complete on both L1 (static) and
L2 (runtime) fields, which is why its official checker never needs NaN guards.
The Xi'an export is not: only ~2.9%/10.7%/0.1% of attraction/restaurant/
accommodation rows satisfy both.

Instead of filling every gap with a sentinel and mixing broken rows into the
main path (which makes the whole route crash on one NaN), this module:

  tier=ready          L1 + L2 complete  -> preferred exposure
  tier=l1_only        L1 complete, L2 gaps -> accessible, gaps declared
  tier=reference_only L1 incomplete -> kept queryable, NOT in the planner path

Only `ready` + `l1_only` rows are written into the merged sandbox loader view,
so opentime/endtime are always valid "HH:MM" strings and the official checker
cannot hit `'float' object has no attribute 'split'`. L1-incomplete rows are
preserved verbatim under reference_only/ (never deleted).

Field sets come from collector_agent/xian_single_city/quality_model.json,
not from ad-hoc definitions.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUALITY_MODEL = ROOT / "collector_agent" / "xian_single_city" / "quality_model.json"
XIAN = ROOT / "data" / "xian11_sandbox"
MERGED = ROOT / "data" / "xian11_merged_sandbox"

# 2026-11-10 用户口径：featurehoteltype 允许留空，不得作为 planner 准入条件。
# 只放宽「准入」，不改 quality_model 的 A 类评级口径（A 类仍要求该字段齐全）。
ADMISSION_L1 = {
    "accommodation": ["lat", "lon"],
    "attraction": ["lat", "lon", "opentime", "endtime"],
    "restaurant": ["lat", "lon", "opentime", "endtime"],
}

SOURCES = {
    "attraction": ("attractions/xian/attractions.csv", "attractions", "xian", "attractions.csv"),
    "restaurant": ("restaurants/xian/restaurants_xian.csv", "restaurants", "xian", "restaurants_xian.csv"),
    "accommodation": ("accommodations/xian/accommodations.csv", "accommodations", "xian", "accommodations.csv"),
}

NUMERIC = {"price", "numbed", "Cost", "recommendmintime", "recommendmaxtime"}
TIER_ORDER = {"ready": 0, "l1_only": 1, "reference_only": 2}


def load_model() -> dict:
    return json.loads(QUALITY_MODEL.read_text(encoding="utf-8"))


def _present(value) -> bool:
    if value is None:
        return False
    s = str(value).strip()
    return bool(s) and s.lower() not in {"nan", "none", "unknown", "null", "nat"}


def classify(row: dict, l1: list[str], l2: set[str], columns: list[str]) -> dict:
    l1_gaps = [c for c in l1 if c in columns and not _present(row.get(c))]
    l2_present = [c for c in columns if c in l2]
    l2_gaps = [c for c in l2_present if not _present(row.get(c))]
    if l1_gaps:
        tier = "reference_only"
    elif l2_gaps:
        tier = "l1_only"
    else:
        tier = "ready"
    return {"tier": tier, "l1_gaps": l1_gaps, "l2_gaps": l2_gaps}


def build_tiered_view() -> dict:
    """Write main loader views + reference_only copies + a full tier index."""
    model = load_model()
    l1_map = model["L1_static_fields"]
    l2 = set(model["L2_runtime_dependent"])
    index = {"quality_model": QUALITY_MODEL.relative_to(ROOT).as_posix(),
             "policy": "P0+P1 admission (coords, opening hours); P2 attributes (type/cuisine/price) optional and graded L3; see docs/data_grading_standard.md",
             "l2_fields": sorted(l2), "kinds": {}}

    for kind, (src, sub, city, filename) in SOURCES.items():
        src_path = XIAN / src
        with src_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
            columns = list(rows[0].keys()) if rows else []
        l1 = ADMISSION_L1.get(kind, l1_map[kind])

        main, reference, records = [], [], []
        other_gaps_total = 0
        for row in rows:
            verdict = classify(row, l1, l2, columns)
            records.append({"name": row.get("name", ""), **verdict})
            if verdict["tier"] == "reference_only":
                reference.append(dict(row))
                continue
            # Keep every non-L1 gap explicit and typed. L1 completeness is the
            # admission gate, but Accommodations.__init__ calls .dropna() over
            # ALL columns, so an empty hotelname_en (neither L1 nor L2) would
            # silently delete the row. Numeric -> -1, text -> UNKNOWN; these
            # are data-gap markers, never real values.
            fixed = dict(row)
            other_gaps = [c for c in columns
                          if c not in l1 and c not in verdict["l2_gaps"]
                          and not _present(fixed.get(c))]
            for col in verdict["l2_gaps"] + other_gaps:
                fixed[col] = "-1" if col in NUMERIC else "UNKNOWN"
            other_gaps_total += len(other_gaps)
            main.append(fixed)

        for col in ("opentime", "endtime"):
            if col in columns:
                bad = [r.get(col) for r in main if not _present(r.get(col))]
                if bad:
                    raise RuntimeError(f"{kind}: {len(bad)} main-view rows still lack {col}")

        out = MERGED / sub / city / filename
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(main)

        ref_out = MERGED / "reference_only" / f"{kind}.csv"
        ref_out.parent.mkdir(parents=True, exist_ok=True)
        with ref_out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(reference)

        counts = {t: sum(1 for r in records if r["tier"] == t) for t in TIER_ORDER}
        index["kinds"][kind] = {
            "L1_fields": l1, "L2_columns_in_file": [c for c in columns if c in l2],
            "total": len(rows), "tiers": counts,
            "main_view_rows": len(main), "reference_only_rows": len(reference),
            "non_l1_non_l2_gaps_filled": other_gaps_total,
            "main_view": out.relative_to(ROOT).as_posix(),
            "reference_only": ref_out.relative_to(ROOT).as_posix(),
            "sentinel": {"numeric": -1, "text": "UNKNOWN",
                         "disclosure": "L2 gaps only; not real values. Any commonsense verdict "
                                       "depending on them is not trustworthy and is reported separately."},
        }
    (MERGED / "TIER_INDEX.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return index


def tier_by_name() -> dict:
    """Lookup used by the C bridge: name -> {tier, l1_gaps, l2_gaps}."""
    model = load_model()
    l1_map, l2 = model["L1_static_fields"], set(model["L2_runtime_dependent"])
    out = {}
    for kind, (src, *_rest) in SOURCES.items():
        with (XIAN / src).open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
            columns = list(rows[0].keys()) if rows else []
        for row in rows:
            out.setdefault(kind, {})[row.get("name", "")] = classify(
                row, l1_map[kind], l2, columns)
    return out


if __name__ == "__main__":
    print(json.dumps(build_tiered_view(), ensure_ascii=False, indent=2))
