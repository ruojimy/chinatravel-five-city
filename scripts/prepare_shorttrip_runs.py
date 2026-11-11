"""Prepare three ShortTrip experiment checkouts (G1/G2/G3) + the frozen 1/10 sample.

Model: Qwen3.5-4B Q8_0 (identical to the upstream tutorial), served by a single
llama.cpp server at 127.0.0.1:18080/v1; concurrency comes from driver.py's
config['workers'] and the server's -np slots.

Groups
  G1_native : upstream's own ChinaTravel 10-city database + native 604x1/10 queries
  G2_ext10  : OUR catalog_v1_1_20261022 exported into the same ChinaTravel layout
              + the SAME 60 paired UIDs (only the data layer changes)
  G3_ext11  : G2 plus the 11th city (Xi'an) from xian11_merged_sandbox
              + xian11 query set (easy/medium/human; chain v1 is architecture-
                incompatible and is emitted separately, not scored as LLM runs)

Everything except the data layer stays untouched ShortTrip code.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import random
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = Path(os.environ.get("SHORTTRIP_UPSTREAM", ROOT / "ShortTrip-upstream"))
RUNS = Path(os.environ.get("SHORTTRIP_RUNS", ROOT.parent / "shorttrip-runs"))
CATALOG = ROOT / "data/catalog_v1_1_20261022/catalog.sqlite3"
CATALOG_GZ = CATALOG.parent / (CATALOG.name + ".gz")
XIAN11 = ROOT / "data/xian11_merged_sandbox"
NATIVE_DB = ROOT / "ChinaTravel/chinatravel/environment/database"  # vendored official release 2026.08.2
QUERIES = ROOT / "data/query_sets"
SEED = 20261111
WORKERS = int(os.environ.get("SHORTTRIP_WORKERS", "6"))
WALL_SECONDS = 1800
CANDIDATE_TARGET = 20

# 1/10 of each split (the user's 2026-11-11 requirement). Native: 300/150/154
# -> 30/15/15 = 60 (9.93% of 604). Xi'an 11-city: 30/15/15 -> 3/3/3 = 9 (10% of
# the 90 single-city questions; the 30 chain questions are frozen but not run
# because the multi-city contract is incompatible with ShortTrip's planner).
QUOTA = {
    "native": {"easy": 30, "medium": 15, "human": 15},
    "xian11": {"easy": 3, "medium": 3, "human": 3, "chain": 3},
}

CITY_SLUG = {
    "北京": "beijing", "上海": "shanghai", "南京": "nanjing", "苏州": "suzhou",
    "杭州": "hangzhou", "深圳": "shenzhen", "成都": "chengdu", "武汉": "wuhan",
    "广州": "guangzhou", "重庆": "chongqing", "西安": "xian",
}
NATIVE_CITIES = [c for c in CITY_SLUG if c != "西安"]

CSV_SPEC = {
    "attraction": ("attractions", "attractions.csv",
                   ["id", "name", "type", "lat", "lon", "opentime", "endtime",
                    "price", "recommendmintime", "recommendmaxtime"]),
    "restaurant": ("restaurants", "restaurants_{}.csv",
                   ["id", "name", "lat", "lon", "price", "cuisine", "opentime",
                    "endtime", "recommendedfood"]),
    "accommodation": ("accommodations", "accommodations.csv",
                      ["id", "name", "hotelname_en", "featurehoteltype", "lat", "lon",
                       "price", "numbed"]),
}
NUMERIC = {"price", "numbed", "recommendmintime", "recommendmaxtime", "lat", "lon"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_catalog() -> None:
    """The 193 MB catalog ships gzipped (14.5 MB). Rebuild it byte-exactly."""
    if CATALOG.exists():
        return
    if not CATALOG_GZ.exists():
        raise FileNotFoundError(f"missing {CATALOG_GZ}")
    with gzip.open(CATALOG_GZ, "rb") as src, CATALOG.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    print(f"    expanded {CATALOG_GZ.name} -> {CATALOG.stat().st_size} bytes", flush=True)


def fresh_checkout(base: Path) -> Path:
    """Never delete or overwrite an existing run checkout (project convention:
    old result snapshots are immutable). Pick the next free suffixed name."""
    dst = base
    i = 2
    while dst.exists():
        dst = base.parent / f"{base.name}_v{i}"
        i += 1
    return dst


def seed_native_database(database: Path) -> int:
    """The upstream checkout ships NO sandbox data (bootstrap_data.py downloads
    it separately and .gitignore's it). Seed every arm from our vendored, frozen
    official release 2026.08.2 — the exact revision in data_sources.json."""
    if not NATIVE_DB.exists():
        raise FileNotFoundError(NATIVE_DB)
    n = 0
    for src in NATIVE_DB.rglob("*"):
        if not src.is_file():
            continue
        target = database / src.relative_to(NATIVE_DB)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(src.read_bytes())
        n += 1
    return n


def copy_checkout(dst: Path) -> None:
    shutil.copytree(UPSTREAM, dst, ignore=shutil.ignore_patterns(
        ".git", ".venv", "__pycache__", "*.pyc", "download.log"))
    seeded = seed_native_database(dst / "chinatravel/environment/database")
    print(f"    seeded {seeded} official sandbox files", flush=True)
    out = dst / "experiments/c_only"
    for name in ("status", "results", "candidates", "selection", "evaluation",
                 "traces", "logs", "cache", "queries", "prompt_snapshots"):
        d = out / name
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "manifest.json", "summary.json", "all_results.json",
                 "process_exits.json", "itineraries.html"):
        p = out / name
        if p.exists():
            p.unlink()


def _rows_by_kind_city():
    db = sqlite3.connect(f"file:{CATALOG.as_posix()}?mode=ro", uri=True)
    out = defaultdict(lambda: defaultdict(list))
    for payload, city in db.execute("select payload,city from records"):
        d = json.loads(payload)
        kind = d.get("kind") or ""
        data = d.get("data") or {}
        if kind in CSV_SPEC and city in NATIVE_CITIES:
            out[kind][city].append(data)
    db.close()
    return out


def export_extended_10(database: Path) -> dict:
    """Replace the three entity tables with OUR catalog; keep POI/subway/intercity
    from the same upstream release because the query DSL references exact
    TrainID/FlightID and the official loader expects that exact layout."""
    grouped = _rows_by_kind_city()
    stats = {}
    for kind, (sub, filename_template, columns) in CSV_SPEC.items():
        total = filled = 0
        for city in NATIVE_CITIES:
            slug = CITY_SLUG[city]
            seen, rows = set(), []
            for item in grouped[kind][city]:
                name = str(item.get("name") or "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                row = {}
                for col in columns:
                    v = item.get(col, "")
                    if v is None or str(v).strip() == "" or str(v).strip().lower() in {"nan", "none"}:
                        v = "-1" if col in NUMERIC else "UNKNOWN"
                        filled += 1
                    row[col] = v
                row["id"] = len(rows)
                rows.append(row)
            filename = filename_template.format(slug) if "{}" in filename_template else filename_template
            target = database / sub / slug / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=columns)
                w.writeheader()
                w.writerows(rows)
            total += len(rows)
        stats[kind] = {"rows": total, "gap_fields_filled": filled}
    stats["disclosure"] = ("POI / subway / intercity tables are kept from the upstream "
                           "release: query DSLs reference exact TrainID/FlightID and the "
                           "official loaders require that exact file layout.")
    return stats


def inject_11th(database: Path, checkout: Path) -> dict:
    """Copy the 11th-city directory tree and register the city in language.py."""
    copied, skipped = [], []
    for sub in ("attractions", "restaurants", "accommodations", "poi"):
        src = XIAN11 / sub / "xian"
        if not src.exists():
            continue
        # Snapshot the file list first: another agent rebuilds this tree while
        # the price backfill runs, so iterdir() can yield a path that vanishes
        # mid-copy (WinError 3). Read bytes into memory, then write; never use
        # copy2's metadata pass on a moving source.
        for f in sorted(list(src.glob("*"))):
            if not f.is_file():
                continue
            try:
                payload = f.read_bytes()
            except (FileNotFoundError, OSError) as exc:
                skipped.append({"path": str(f), "error": f"{type(exc).__name__}: {exc}"})
                continue
            dst = database / sub / "xian" / f.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(payload)
            copied.append(str(dst.relative_to(database).as_posix()))

    # merge subway lines
    native_sub = database / "transportation/subways.json"
    merged_sub = XIAN11 / "transportation/subways.json"
    if native_sub.exists() and merged_sub.exists():
        d = read(native_sub)
        x = read(merged_sub).get("xian")
        if x:
            d["xian"] = x
            save(native_sub, d)

    # merge intercity pairs (Xi'an-involving ones already exist in xian11 sandbox)
    train_dir = database / "intercity_transport/train"
    train_dir.mkdir(parents=True, exist_ok=True)
    src_train = XIAN11 / "intercity_transport/train"
    added = 0
    if src_train.exists():
        for f in src_train.glob("from_*_to_*.json"):
            dst = train_dir / f.name
            if not dst.exists():
                try:
                    dst.write_bytes(f.read_bytes())
                    added += 1
                except (FileNotFoundError, OSError) as exc:
                    skipped.append({"path": str(f), "error": f"{type(exc).__name__}: {exc}"})
    ap = database / "intercity_transport/airplane.jsonl"
    xap = XIAN11 / "intercity_transport/airplane.jsonl"
    if ap.exists() and xap.exists():
        seen = {l.strip() for l in ap.read_text(encoding="utf-8").splitlines() if l.strip()}
        extra = [l.strip() for l in xap.read_text(encoding="utf-8").splitlines()
                 if l.strip() and l.strip() not in seen]
        ap.write_text(ap.read_text(encoding="utf-8").rstrip("\n") + "\n" + "\n".join(extra) + "\n",
                      encoding="utf-8")

    # register the city (data-layer only; no planner logic touched)
    lang = checkout / "chinatravel/environment/language.py"
    text = lang.read_text(encoding="utf-8")
    if '"xian"' not in text:
        text = text.replace('    "chongqing",\n]', '    "chongqing",\n    "xian",\n]')
    if '"西安"' not in text:
        text = text.replace('"广州", "重庆"]', '"广州", "重庆", "西安"]')
    if "Xi'an" not in text:
        text = text.replace('        "Chongqing",\n    ]', '        "Chongqing",\n        "Xi\'an",\n    ]')
    lang.write_text(text, encoding="utf-8")
    return {"copied_files": copied, "train_pairs_added": added,
            "skipped_due_to_concurrent_rebuild": skipped,
            "city_registered": "xian / 西安 / Xi'an",
            "data_source_note": "data/xian11_merged_sandbox is rebuilt by the parallel "
                                "gap-fill line (snapshot_v16, grading standard v1); "
                                "regenerate this checkout after that line goes quiet."}


def _sample(source: Path, quota: dict, tag: str) -> dict:
    out = {}
    for split, n in quota.items():
        uids = sorted(p.stem for p in (source / split).glob("*.json"))
        if n > len(uids):
            raise ValueError(f"{tag}/{split}: quota {n} > available {len(uids)}")
        out[split] = sorted(random.Random(f"{SEED}:{tag}:{split}").sample(uids, n))
    return out


def sample_native() -> dict:
    return _sample(QUERIES, QUOTA["native"], "native")


def sample_xian11() -> dict:
    return _sample(QUERIES / "xian11", QUOTA["xian11"], "xian11")


def build_cases(checkout: Path, samples: dict, source: Path, skip_chain: bool) -> tuple[list, list]:
    cases, chain_only = [], []
    out = checkout / "experiments/c_only"
    for split, uids in samples.items():
        for i, uid in enumerate(uids, 1):
            q = read(source / split / f"{uid}.json")
            if split == "chain" and skip_chain:
                chain_only.append({"uid": uid, "split": split,
                                   "reason": "shorttrip-dynamic-v1 multi-city contract is "
                                             "incompatible with ShortTrip's single-target planner"})
                continue
            case = f"{split}_{i:03d}_C_r1"
            rel = f"queries/{case}.json"
            save(out / rel, q)
            cases.append({"case": case, "base_case": f"{split}_{i:03d}", "group": "C",
                          "repetition": 1, "split": split, "uid": uid, "query": rel})
    return cases, chain_only


def write_config_manifest(checkout: Path, cases: list, arm: str) -> None:
    out = checkout / "experiments/c_only"
    project = checkout
    save(out / "config.json", {"project": str(project), "workers": WORKERS,
                               "model": "qwen3.5-4b-q8",
                               "base_url": "http://127.0.0.1:18080/v1",
                               "seed": SEED})
    files = [p.relative_to(project).as_posix() for p in (project / "chinatravel").rglob("*.py")
             if not any(part in ("database", "database_en", "__pycache__") for part in p.parts)]
    experiment = ("worker.py", "experiment_agent.py", "rules.py", "dfs_snapshot.py",
                  "catalog.py", "meal_pruning.py", "driver.py", "report.py")
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(), "project": str(project),
        "language": "zh", "groups": ["C"], "repetitions": 1, "arm": arm,
        "wall_seconds": WALL_SECONDS, "candidate_target": CANDIDATE_TARGET,
        "cases": cases, "translation_cache": "fresh_per_case", "oracle_in_planning": False,
        "seed": SEED, "model": "qwen3.5-4b-q8",
        "source_sha256": {f: sha(project / f) for f in files},
        "experiment_sha256": {n: sha(out / n) for n in experiment},
    }
    save(out / "manifest.json", manifest)
    for name in ("prompts.py", "prompts_en.py"):
        shutil.copy2(project / "chinatravel/agent/nesy_agent/prompts" / name,
                     out / "prompt_snapshots" / name)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", choices=["G1", "G2", "G3"], default=None)
    args = ap.parse_args()
    RUNS.mkdir(parents=True, exist_ok=True)
    ensure_catalog()
    native = sample_native()
    xian = sample_xian11()
    # Keep the earlier 1/5 freeze for the record; this run writes a new file.
    legacy = RUNS / "frozen_samples.json"
    if legacy.exists() and not (RUNS / "frozen_samples_1of5.json").exists():
        shutil.copy2(legacy, RUNS / "frozen_samples_1of5.json")
    save(RUNS / "frozen_samples_1of10.json", {
        "seed": SEED,
        "policy": "1/10 of each split, fixed seed, G1/G2 share UIDs; "
                  "xian11 chain frozen but not runnable under ShortTrip C-only",
        "native": {k: len(v) for k, v in native.items()},
        "xian11": {k: len(v) for k, v in xian.items()},
        "native_uids": native, "xian11_uids": xian,
    })

    active_path = RUNS / "ACTIVE_CHECKOUTS.json"
    active = read(active_path) if active_path.exists() else {}
    for arm in ("G1", "G2", "G3"):
        if args.only and arm != args.only:
            continue
        label = {"G1": "G1_native", "G2": "G2_ext10", "G3": "G3_ext11"}[arm]
        checkout = fresh_checkout(RUNS / label)
        print(f"[{arm}] copying checkout -> {checkout}", flush=True)
        copy_checkout(checkout)
        database = checkout / "chinatravel/environment/database"
        info = {}
        if arm in ("G2", "G3"):
            info["extended_10"] = export_extended_10(database)
        if arm == "G3":
            info["xian11"] = inject_11th(database, checkout)
        samples = native if arm in ("G1", "G2") else xian
        source = QUERIES if arm in ("G1", "G2") else QUERIES / "xian11"
        cases, chain_only = build_cases(checkout, samples, source, skip_chain=True)
        write_config_manifest(checkout, cases, arm)
        save(checkout / "experiments/c_only/arm_info.json", {"arm": arm, **info,
             "cases": len(cases), "chain_excluded": chain_only})
        print(f"[{arm}] cases={len(cases)} chain_excluded={len(chain_only)}", flush=True)
        active[label] = str(checkout)
        save(active_path, active)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
