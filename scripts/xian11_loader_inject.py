"""Inject the 11th city (Xi'an) into the OFFICIAL ChinaTravel loaders at runtime.

The frozen 10-city baseline under ChinaTravel/ is never modified. Instead:

1. Build `data/xian11_merged_sandbox/`, byte-identical to the official
   `environment/database/` layout for the original 10 cities, plus the Xi'an
   exports. Missing intercity pairs are filled with empty arrays so
   IntercityTransport's exhaustive 11x10 loop does not crash.
2. Patch `relative_database_path` in `language` and in every api module that
   imported it by name, pointing at the merged sandbox (an absolute path, which
   os.path.join discards the api-module prefix for).
3. Append `xian` / 西安 to CITY_SLUGS and CITY_NAMES.
4. Reload `symbol_verification.commonsense_constraint` if it was already
   imported, because that module constructs its five sandbox singletons AT
   IMPORT TIME. Without the reload the checker keeps the 10-city singletons.

Call install() BEFORE importing `shorttrip.checker` / any evaluation module.

Usage:
    python scripts/xian11_loader_inject.py --check     # build + self-test
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "ChinaTravel")]

NATIVE_DB = ROOT / "ChinaTravel" / "chinatravel" / "environment" / "database"
XIAN = ROOT / "data" / "xian11_sandbox"
MERGED = ROOT / "data" / "xian11_merged_sandbox"

SLUG = "xian"
CITY_ZH = "西安"
CITY_EN = "Xi'an"

API_MODULES = (
    "chinatravel.environment.tools.accommodations.apis",
    "chinatravel.environment.tools.attractions.apis",
    "chinatravel.environment.tools.intercity_transport.apis",
    "chinatravel.environment.tools.poi.apis",
    "chinatravel.environment.tools.restaurants.apis",
    "chinatravel.environment.tools.transportation.apis",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_native() -> dict:
    """Mirror the original 10-city database byte-for-byte, with a hash receipt."""
    receipt = {}
    if not NATIVE_DB.exists():
        raise FileNotFoundError(NATIVE_DB)
    for src in sorted(NATIVE_DB.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(NATIVE_DB)
        # intercity_transport is rebuilt from native + xian below; skip for now
        if rel.parts[0] == "intercity_transport":
            continue
        dst = MERGED / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        receipt[rel.as_posix()] = sha(src)
    return receipt


def _clean_csv(src: Path, dst: Path) -> int:
    """Strip the UTF-8 BOM from exported Xi'an CSVs (columns must match native)."""
    text = src.read_text(encoding="utf-8-sig")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")
    return len(text.splitlines()) - 1


def _fill_accommodation_gaps() -> dict:
    """Xi'an accommodation exports have no real price/bed data (2/761 and 4/761
    populated even in the upstream catalog). Official Accommodations.__init__
    calls .dropna() and then .iloc[0], so an all-NaN column empties the table
    and crashes the loader.

    We do NOT invent prices. Missing numeric fields become the explicit sentinel
    -1, which is not a plausible room rate; the official checker then reports a
    normal "incorrect accommodation price/cost" violation instead of throwing.
    Missing text fields become "" (not NaN). Rows without coordinates are
    dropped (they cannot be located at all). Every substitution is counted and
    written into the manifest so the limitation is auditable.
    """
    import csv as _csv
    path = MERGED / "accommodations" / SLUG / "accommodations.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(_csv.DictReader(handle))
        fields = list(rows[0].keys()) if rows else []
    kept, dropped_no_coord = [], 0
    counts = {"price": 0, "numbed": 0, "hotelname_en": 0, "featurehoteltype": 0}
    for row in rows:
        if not (row.get("lat") or "").strip() or not (row.get("lon") or "").strip():
            dropped_no_coord += 1
            continue
        # pandas reads "" as NaN and .dropna() would delete the row again, so
        # text gaps use an explicit non-empty UNKNOWN sentinel.
        for key, sentinel in (("price", -1), ("numbed", -1),
                              ("hotelname_en", "UNKNOWN"),
                              ("featurehoteltype", "UNKNOWN")):
            if not (row.get(key) or "").strip():
                row[key] = sentinel
                counts[key] += 1
        kept.append(row)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = _csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(kept)
    return {"rows_in": len(rows), "rows_kept": len(kept),
            "dropped_without_coordinates": dropped_no_coord,
            "sentinel_substitutions": counts,
            "sentinel": -1,
            "disclosure": "-1 is a data-gap sentinel, NOT a real price. Any commonsense "
                          "judgement depending on Xi'an accommodation price or bed count "
                          "is not trustworthy and must be reported separately."}


def _merge_airplane() -> dict:
    out = MERGED / "intercity_transport" / "airplane.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    seen, rows = set(), []
    for src in (NATIVE_DB / "intercity_transport" / "airplane.jsonl",
                XIAN / "intercity_transport" / "airplane.jsonl"):
        if not src.exists():
            continue
        for line in src.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            key = obj.get("FlightID") or obj.get("flight_id") or line.strip()
            if key in seen:
                continue
            seen.add(key)
            rows.append(line.strip())
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return {"rows": len(rows), "native": 720, "xian_extra": len(rows) - 720}


def _merge_trains(city_names: list[str]) -> dict:
    """IntercityTransport loops over EVERY ordered city pair; all must exist."""
    train_dir = MERGED / "intercity_transport" / "train"
    train_dir.mkdir(parents=True, exist_ok=True)
    native_dir = NATIVE_DB / "intercity_transport" / "train"
    xian_dir = XIAN / "intercity_transport" / "train"
    made = empty = merged = 0
    for a in city_names:
        for b in city_names:
            if a == b:
                continue
            name = f"from_{a}_to_{b}.json"
            rows, ids = [], set()
            for src in (native_dir / name, xian_dir / name):
                if not src.exists():
                    continue
                value = json.loads(src.read_text(encoding="utf-8"))
                if not isinstance(value, list):
                    value = [value]
                for item in value:
                    key = item.get("TrainID") or json.dumps(item, ensure_ascii=False, sort_keys=True)
                    if key not in ids:
                        ids.add(key)
                        rows.append(item)
                if src == xian_dir / name:
                    merged += 1
            if not rows:
                empty += 1
            (train_dir / name).write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n",
                                          encoding="utf-8")
            made += 1
    return {"pairs_written": made, "pairs_empty": empty, "pairs_with_xian_source": merged}


def _merge_subways() -> dict:
    """Official subways.json is {city_slug: [{name: line, stations: [...]}]}."""
    native = json.loads((NATIVE_DB / "transportation" / "subways.json").read_text(encoding="utf-8"))
    xian_src = XIAN / "subway_stations" / "xian" / "subway_stations.json"
    by_line = defaultdict(list)
    if xian_src.exists():
        for s in json.loads(xian_src.read_text(encoding="utf-8")):
            pos = s.get("position")
            if isinstance(pos, (list, tuple)) and len(pos) >= 2:
                pos = f"{pos[0]},{pos[1]}"
            by_line[s.get("line", "西安地铁")].append({"name": s.get("name", ""), "position": pos})
    native[SLUG] = [{"name": line, "stations": stations} for line, stations in by_line.items()]
    out = MERGED / "transportation" / "subways.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(native, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"cities": list(native), "xian_lines": len(by_line),
            "xian_stations": sum(len(v) for v in by_line.values())}


def build_merged_sandbox() -> dict:
    """Idempotent. Returns a manifest with hash receipts for auditability."""
    MERGED.mkdir(parents=True, exist_ok=True)
    receipt = _copy_native()
    # Quality-tiered views: only L1-complete rows enter the planner/loader path.
    # L1-incomplete rows stay queryable under reference_only/ instead of being
    # mixed in with sentinels and crashing the whole checker on one NaN.
    from xian11_tier import build_tiered_view
    tiers = build_tiered_view()
    csv_rows = {k: v["main_view_rows"] for k, v in tiers["kinds"].items()}
    poi = json.loads((XIAN / "poi" / "xian" / "poi.json").read_text(encoding="utf-8"))
    poi_out = MERGED / "poi" / SLUG / "poi.json"
    poi_out.parent.mkdir(parents=True, exist_ok=True)
    poi_out.write_text(json.dumps(poi, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    from chinatravel.environment.language import CITY_NAMES
    base_names = list(CITY_NAMES["zh"])
    all_names = base_names + ([CITY_ZH] if CITY_ZH not in base_names else [])
    airplanes = _merge_airplane()
    trains = _merge_trains(all_names)
    subways = _merge_subways()

    manifest = {
        "merged_sandbox": MERGED.relative_to(ROOT).as_posix(),
        "native_db": NATIVE_DB.relative_to(ROOT).as_posix(),
        "native_files_copied": len(receipt),
        "native_sha256": receipt,
        "xian_csv_rows": csv_rows,
        "xian_tiers": {k: v["tiers"] for k, v in tiers["kinds"].items()},
        "tier_policy": tiers["policy"],
        "tier_index": "data/xian11_merged_sandbox/TIER_INDEX.json",
        "xian_poi": len(poi),
        "airplanes": airplanes,
        "trains": trains,
        "subways": subways,
        "city_order_zh": all_names,
        "note": "10-city files are byte-identical copies; ChinaTravel/ is never written",
    }
    (MERGED / "INJECTION_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return manifest


def install() -> dict:
    """Patch official loaders in memory. Must run before importing any evaluator."""
    manifest = build_merged_sandbox()

    import chinatravel.environment.language as language
    if SLUG not in language.CITY_SLUGS:
        language.CITY_SLUGS.append(SLUG)
    for lang, name in (("zh", CITY_ZH), ("en", CITY_EN)):
        if name not in language.CITY_NAMES[lang]:
            language.CITY_NAMES[lang].append(name)

    def merged_path(lang=None, *parts):
        # Absolute path: os.path.join(curdir, this, ...) discards curdir.
        suffix = "/".join(str(p) for p in parts)
        return (MERGED / suffix).as_posix() if suffix else MERGED.as_posix()

    language.relative_database_path = merged_path
    patched = []
    for name in API_MODULES:
        mod = importlib.import_module(name)
        if hasattr(mod, "relative_database_path"):
            mod.relative_database_path = merged_path
            patched.append(name)

    # The commonsense verifier builds its tool singletons at import time.
    reloaded = []
    for name in ("chinatravel.symbol_verification.commonsense_constraint",
                 "chinatravel.symbol_verification.hard_constraint"):
        if name in sys.modules:
            importlib.reload(sys.modules[name])
            reloaded.append(name)

    # Belt-and-braces NaN guard: even if a future query reaches a record with a
    # malformed time field, one bad value must not abort the whole question.
    # For valid "HH:MM" inputs this is byte-for-byte the original behaviour,
    # so the frozen 10-city baseline is unaffected.
    import chinatravel.symbol_verification.commonsense_constraint as sv
    _orig_time_cmp = sv.time_compare_if_earlier_equal

    def guarded_time_compare(time_1, time_2):
        try:
            return _orig_time_cmp(time_1, time_2)
        except (TypeError, ValueError, AttributeError, IndexError):
            return False

    if not getattr(_orig_time_cmp, "_xian_guarded", False):
        guarded_time_compare._xian_guarded = True
        sv.time_compare_if_earlier_equal = guarded_time_compare
    guard = {"function": "time_compare_if_earlier_equal",
             "behaviour": "returns False on malformed/NaN time instead of raising",
             "valid_input_behaviour": "unchanged (delegates to original)"}

    return {"registered": True, "slug": SLUG,
            "cities": len(language.CITY_SLUGS), "patched_modules": patched,
            "reloaded_modules": reloaded, "nan_guard": guard,
            "merged_sandbox": MERGED.as_posix(), "manifest": manifest}


def self_test() -> dict:
    info = install()
    from chinatravel.environment.tools.attractions.apis import Attractions
    from chinatravel.environment.tools.restaurants.apis import Restaurants
    from chinatravel.environment.tools.accommodations.apis import Accommodations
    from chinatravel.environment.tools.intercity_transport.apis import IntercityTransport
    from chinatravel.environment.tools.transportation.apis import Transportation
    from chinatravel.environment.tools.poi.apis import Poi

    a = Attractions()
    r = Restaurants()
    h = Accommodations()
    ic = IntercityTransport()
    t = Transportation()
    p = Poi()
    # Official loaders rename slug keys to Chinese city names at the end of
    # __init__, so probe with CITY_ZH, not the slug.
    out = {
        "xian_attractions": len(a.data.get(CITY_ZH, [])),
        "xian_restaurants": len(r.data.get(CITY_ZH, [])),
        "xian_accommodations": len(h.data.get(CITY_ZH, [])),
        "intercity_pairs": len(ic.train_df_dict),
        "xian_to_beijing_trains": len(ic.train_df_dict.get((CITY_ZH, "北京"), [])),
        "xian_subway_lines": len(t.city_lines_dict.get(SLUG, [])),
        "xian_stations": len(t.city_stations_dict.get(SLUG, [])),
        "xian_poi_probe": None,
        "ten_city_unchanged": None,
    }
    try:
        out["xian_poi_probe"] = p.search(CITY_ZH, "西安城墙 Xi'an City Wall")
    except Exception as exc:  # noqa: BLE001
        out["xian_poi_probe_error"] = f"{type(exc).__name__}: {exc}"

    # Prove the 10-city baseline bytes are untouched. subways.json is a GLOBAL
    # file (not per-city); it necessarily gains an "xian" key, so verify it
    # separately by comparing the original city keys byte-for-byte in JSON.
    m = info["manifest"]["native_sha256"]
    bad = [k for k, v in m.items()
           if k != "transportation/subways.json"
           and (not (MERGED / k).exists() or sha(MERGED / k) != v)]
    native_sub = json.loads((NATIVE_DB / "transportation" / "subways.json").read_text(encoding="utf-8"))
    merged_sub = json.loads((MERGED / "transportation" / "subways.json").read_text(encoding="utf-8"))
    sub_changed = [c for c in native_sub if merged_sub.get(c) != native_sub[c]]
    out["ten_city_unchanged"] = not bad and not sub_changed
    out["ten_city_hash_mismatches"] = bad[:5]
    out["native_subway_cities_preserved"] = list(native_sub)
    out["native_subway_cities_changed"] = sub_changed
    out["subways_global_file_note"] = (
        "transportation/subways.json is intentionally extended with one new "
        "'xian' key; all original city keys are byte-identical in JSON content."
    )
    out.update({k: info[k] for k in ("cities", "patched_modules", "reloaded_modules")})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="build merged sandbox and self-test")
    args = ap.parse_args()
    if args.check:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"merged_sandbox": MERGED.as_posix(),
                          "call": "import this module and call install() before importing checkers"},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
