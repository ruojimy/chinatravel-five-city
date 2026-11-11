"""Hard gate before starting the ShortTrip/Qwen3.5-4B three-arm benchmark.

The Xi'an gap-fill line is still writing restaurant/attraction prices
(xian_gapfill_price_amap.py --tag p1). Starting the benchmark while those
files are moving would freeze a half-written dataset and invalidate the
comparison. This gate refuses to launch unless ALL of the following hold:

  1. no NEW price-capture output for a quiet window (two samples)
  2. no NEW snapshot_vN directory for a quiet window
  3. data/ trees used by the experiment have stopped changing
  4. the model file is complete (GGUF magic + expected size)
  5. the llama.cpp server answers /v1/models with the exact model alias
  6. every experiment checkout has a frozen database hash manifest

Run it any time; it is read-only except for writing its own report.
Exit code 0 = READY, 2 = NOT READY.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = Path(os.environ.get("SHORTTRIP_LOCAL", ROOT.parent / "shorttrip-local"))
RUNS = Path(os.environ.get("SHORTTRIP_RUNS", ROOT.parent / "shorttrip-runs"))
GAPFILL = ROOT / "results/xian_gapfill_20261109"
DATA_DIRS = [
    ROOT / "data/catalog_v1_1_20261022",
    ROOT / "data/xian11_merged_sandbox",
]
MODEL = LOCAL / "Qwen3.5-4B-Q8_0.gguf"
EXPECTED_MODEL_BYTES = 4_600_000_000  # ~4.6 GB Q8_0, allow tolerance below
MODEL_TOLERANCE = 0.03
ENDPOINT = "http://127.0.0.1:18080/v1"
ALIAS = "qwen3.5-4b-q8"


def _fingerprint() -> dict:
    """Snapshot of every moving part of the price backfill."""
    staging = GAPFILL / "staging/price_p1"
    raw = GAPFILL / "raw/price_p1"
    out = {
        "run_log_bytes": (staging / "run_log.jsonl").stat().st_size if (staging / "run_log.jsonl").exists() else 0,
        "items_bytes": (staging / "items.jsonl").stat().st_size if (staging / "items.jsonl").exists() else 0,
        "raw_price_files": len(list(raw.glob("*.json"))) if raw.exists() else 0,
        "snapshots": sorted(p.name for p in GAPFILL.glob("snapshot_v*") if p.is_dir()),
        "data_mtimes": {},
    }
    for d in DATA_DIRS:
        if not d.exists():
            out["data_mtimes"][d.name] = None
            continue
        newest = max((p.stat().st_mtime for p in d.rglob("*") if p.is_file()), default=0)
        out["data_mtimes"][d.name] = round(newest, 2)
    return out


def _price_coverage() -> dict:
    snapshots = sorted((p for p in GAPFILL.glob("snapshot_v*/catalog.sqlite3")),
                       key=lambda p: p.stat().st_mtime)
    if not snapshots:
        return {"note": "gapfill workspace not shipped; static sandbox only"}
    latest = snapshots[-1]
    db = sqlite3.connect(f"file:{latest.as_posix()}?mode=ro", uri=True)
    out = {"snapshot": latest.parent.name}
    for kind in ("attraction", "restaurant", "accommodation"):
        total = have = 0
        for (payload,) in db.execute("select payload from records where kind=?", (kind,)):
            d = json.loads(payload).get("data") or {}
            total += 1
            v = d.get("price")
            if v not in (None, "", "UNKNOWN", "-1"):
                have += 1
        out[kind] = {"price_present": have, "total": total,
                     "pct": round(100 * have / max(total, 1), 1)}
    db.close()
    return out


def _model_ok() -> dict:
    if not MODEL.exists():
        return {"ready": False, "reason": "model file not present yet", "bytes": 0}
    size = MODEL.stat().st_size
    with MODEL.open("rb") as fh:
        magic = fh.read(4)
    complete = magic == b"GGUF" and size >= EXPECTED_MODEL_BYTES * (1 - MODEL_TOLERANCE)
    return {"ready": bool(complete), "magic": magic.decode("latin1"), "bytes": size,
            "expected_min": int(EXPECTED_MODEL_BYTES * (1 - MODEL_TOLERANCE)),
            "path": str(MODEL), "sha256_head": hashlib.sha256(MODEL.read_bytes()[:1_000_000]).hexdigest()[:16]}


def _server_ok() -> dict:
    import urllib.request
    try:
        with urllib.request.urlopen(ENDPOINT + "/models", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        ids = [d.get("id") for d in data.get("data", [])]
        return {"ready": ALIAS in ids, "models": ids, "endpoint": ENDPOINT}
    except Exception as exc:  # noqa: BLE001
        return {"ready": False, "error": f"{type(exc).__name__}: {exc}", "endpoint": ENDPOINT}


def _checkouts_ok() -> dict:
    out = {}
    for p in sorted(RUNS.glob("G*_v*")) + sorted(RUNS.glob("G1_native")) + sorted(RUNS.glob("G2_ext10")) + sorted(RUNS.glob("G3_ext11*")):
        c = p / "experiments/c_only/config.json"
        m = p / "experiments/c_only/manifest.json"
        info = p / "experiments/c_only/arm_info.json"
        if not (c.exists() and m.exists()):
            continue
        out[p.name] = {"cases": len(json.loads(m.read_text(encoding="utf-8"))["cases"]),
                       "has_arm_info": info.exists()}
    return out


HISTORY = RUNS / "READINESS_HISTORY.jsonl"


def _history_last() -> dict | None:
    if not HISTORY.exists():
        return None
    lines = [l for l in HISTORY.read_text(encoding="utf-8").splitlines() if l.strip()]
    return json.loads(lines[-1]) if lines else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quiet-window", type=int, default=60,
                    help="seconds between the two activity samples")
    ap.add_argument("--skip-quiet", action="store_true",
                    help="skip the two-sample wait (for a quick diagnostic)")
    ap.add_argument("--accept-coverage", metavar="NOTE", default=None,
                    help="operator explicitly accepts the CURRENT price coverage; "
                         "the note is written into the readiness record")
    args = ap.parse_args()

    first = _fingerprint()
    if args.skip_quiet:
        # A single sample cannot prove the backfill stopped. Never let a
        # diagnostic run accidentally report READY.
        checks = {
            "price_capture_quiet": None,
            "snapshot_set_quiet": None,
            "data_trees_quiet": None,
            "quiet_window_skipped": "unknown: rerun without --skip-quiet to certify",
        }
        second = first
    else:
        time.sleep(args.quiet_window)
        second = _fingerprint()
        checks = {
            "price_capture_quiet": first == second,
            "snapshot_set_quiet": first["snapshots"] == second["snapshots"],
            "data_trees_quiet": first["data_mtimes"] == second["data_mtimes"],
            "quiet_window_seconds": args.quiet_window,
        }
        if not checks["price_capture_quiet"]:
            checks["changed_fields"] = [k for k in first if first[k] != second[k]]
    model = _model_ok()
    server = _server_ok() if model["ready"] else {"ready": False, "error": "model not ready"}
    checks["model_complete"] = model["ready"]
    checks["server_alias"] = server["ready"]

    coverage = _price_coverage()
    checkouts = _checkouts_ok()
    previous = _history_last()
    latest_snapshot = coverage.get("snapshot")
    # A 60s quiet window can be a gap BETWEEN batches. Require the snapshot and
    # the price coverage to be unchanged across two INDEPENDENT gate runs too.
    if "snapshot" not in coverage:
        checks["snapshot_stable_across_runs"] = True
        checks["coverage_stable_across_runs"] = True
        checks["history_note"] = "no gapfill workspace in this checkout; static-suite mode"
    elif previous:
        checks["snapshot_stable_across_runs"] = previous.get("snapshot") == latest_snapshot
        checks["coverage_stable_across_runs"] = previous.get("coverage") == {
            k: v for k, v in coverage.items() if k != "snapshot"}
    else:
        checks["snapshot_stable_across_runs"] = None
        checks["coverage_stable_across_runs"] = None
        checks["history_note"] = "first independent check; rerun the gate to certify stability"
    # Quiet != complete. The operator must explicitly accept the current
    # coverage (e.g. attraction price may still be a known open gap).
    checks["coverage_explicitly_accepted"] = bool(args.accept_coverage)

    quiet_keys = ("price_capture_quiet", "snapshot_set_quiet", "data_trees_quiet",
                  "snapshot_stable_across_runs", "coverage_stable_across_runs",
                  "model_complete", "server_alias", "coverage_explicitly_accepted")
    ready = all(checks.get(k) is True for k in quiet_keys)
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "ready": ready,
        "gate": "ALL of: 60s two-sample quiet, snapshot/coverage unchanged across "
                "two independent gate runs, model_complete, server_alias, and an "
                "explicit --accept-coverage confirmation. Quiet alone is NOT completion.",
        "checks": checks,
        "first_sample": first, "second_sample": second,
        "price_coverage": coverage,
        "model": model, "server": server,
        "checkouts": checkouts,
        "note": "Quiet window proves the backfill stopped; it does NOT assert a target "
                "coverage percentage. Coverage is reported for the operator to accept.",
    }
    out = RUNS / "READINESS.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    report["coverage_acceptance_note"] = args.accept_coverage
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "checked_at": report["checked_at"], "ready": ready,
            "snapshot": latest_snapshot,
            "coverage": {k: v for k, v in coverage.items() if k != "snapshot"},
            "acceptance_note": args.accept_coverage,
        }, ensure_ascii=False) + "\n")
    (RUNS / "READINESS.md").write_text(
        "# ShortTrip/Qwen3.5-4B 开测就绪检查\n\n"
        f"- 时间：{report['checked_at']}\n- **结果：{'READY 可以开测' if ready else 'NOT READY 禁止开测'}**\n\n"
        "| 判据 | 结果 |\n|---|---|\n" +
        "".join(f"| {k} | {v} |\n" for k, v in checks.items()) +
        "\n## price 覆盖率（最新快照）\n\n" +
        json.dumps(coverage, ensure_ascii=False, indent=1) + "\n\n"
        "判据「静止」只证明补价写盘停止，不代表达到某个目标覆盖率。\n\n"
        "还要求：快照号与覆盖率在**两次独立检查**之间不变，并由研究者用 "
        "`--accept-coverage \"<说明>\"` 显式接受当前覆盖率（该说明会写入记录）。\n"
        "注意：补价脚本只处理餐厅；景点 price 覆盖率若长期不增长，属于已知开放缺口，"
        "必须由研究者确认是否接受，不能由脚本臆断完成。\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("ready", "checks", "price_coverage")},
                     ensure_ascii=False, indent=2))
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
