"""Continuous quality campaign: refill fields until grade-A ratio >= target.

This is a long-running loop, not a 2-hour scheduled batch. Each round:
  bulk API collection (raw bytes persisted) -> xian_ingest.apply_enrichment
  (only null fields) -> xian_quality.classify (re-derives evidence, contract,
  source score, grade) -> hard-failure rollback -> progress log.

It stops when A ratio >= target (and hard_failures == 0), on a plateau,
on a provider quota stop, or at --max-rounds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from shorttrip.expansion_contract import validate_record  # noqa: E402
from xian_ingest import apply_enrichment  # noqa: E402
from xian_quality import classify, load_config  # noqa: E402
from xian_verify import audit  # noqa: E402
from xian_bulk_enrich import run_round  # noqa: E402


def load_items(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def apply(conn: sqlite3.Connection, rows: list[dict]) -> dict:
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    result = apply_enrichment(conn, rows, stamp)
    conn.commit()
    return {"applied": len(result["applied"]),
            "fields": sum(len(a["fields"]) for a in result["applied"]),
            "skipped": len(result["skipped"])}


def rollback_hard(conn: sqlite3.Connection, snapshot: Path) -> int:
    """Undo fields whose evidence fails the audit hard gate."""
    v = audit(snapshot, None)
    targets = {}
    for p in v["problems"]:
        if p["issue"] in ("raw_sha256_mismatch", "quote_not_verbatim", "name_not_in_raw",
                          "evidence_not_in_table", "quote_not_verbatim_in_raw"):
            targets.setdefault(p["id"], set()).add(p.get("field"))
    fixed = 0
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    for rid, fields in targets.items():
        row = conn.execute("select payload from records where id=?", (rid,)).fetchone()
        if not row:
            continue
        payload = json.loads(row[0])
        changed = False
        for key in fields:
            if key not in (payload.get("data") or {}):
                continue
            old = payload["data"][key]
            payload["data"][key] = None
            payload.setdefault("field_provenance", {}).setdefault(key, {}).update({
                "status": "unknown", "source_id": None, "source_url": None,
                "observed_at": None, "evidence_id": None,
                "quote": f"回滚：{old} 未通过审计硬门", "valid_until": None})
            changed = True
        if changed:
            gate = validate_record(payload, now=stamp)
            conn.execute("update records set payload=?,gate=?,planning_ready=? where id=?",
                         (json.dumps(payload, ensure_ascii=False),
                          json.dumps(gate, ensure_ascii=False),
                          1 if gate.get("planning_ready") else 0, rid))
            fixed += 1
    if fixed:
        conn.commit()
    return fixed


def write_manifest(snapshot: Path, report: dict, extra: dict) -> None:
    db = snapshot / "catalog.sqlite3"
    digest = hashlib.sha256(db.read_bytes()).hexdigest()
    conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    total = conn.execute("select count(*) from records").fetchone()[0]
    integrity = conn.execute("pragma integrity_check").fetchone()[0]
    conn.close()
    out = snapshot / "manifest.json"
    manifest = {"snapshot": snapshot.name, "catalog_sha256": digest,
                "sqlite_integrity_check": integrity, "record_count": total,
                "checked_at": report["checked_at"],
                "quality": {"grades": report["grades"],
                            "high_quality_ratio": report["high_quality_ratio"],
                            "hard_failures": report["hard_failures"]},
                **extra}
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def run(args) -> int:
    config = load_config()
    snapshot = Path(args.snapshot)
    if not snapshot.is_absolute():
        snapshot = ROOT / snapshot
    snapshot = snapshot.resolve()
    run_dir = Path(args.run)
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    run_dir = run_dir.resolve()
    parent = snapshot / "catalog.sqlite3"
    conn = sqlite3.connect(parent)
    target = args.target if args.target is not None else config["target"]["high_quality_ratio"]
    progress_path = run_dir / "quality_progress.jsonl"
    state_path = run_dir / "campaign_state.json"
    history = []
    if args.resume and progress_path.exists():
        history = [json.loads(l) for l in progress_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    start_round = len(history) + 1
    prev_ratio = history[-1]["ratio"] if history else 0.0
    plateau = 0
    stop_reason = None

    # one-off enrichment files produced by auto subagents
    if args.extra_enrich:
        rows = []
        for f in args.extra_enrich:
            rows += load_items(Path(f))
        if rows:
            result = apply(conn, rows)
            print(f"[subagent] applied {result['applied']} records / {result['fields']} fields", flush=True)

    for round_no in range(start_round, args.max_rounds + 1):
        worker = f"bulk_r{round_no:03d}"
        bulk_args = argparse.Namespace(
            run=str(run_dir), snapshot=str(parent), worker=worker,
            kinds=args.kinds, offset=(round_no - 1) * args.offset_step,
            max_calls=args.calls_per_round, pages=args.pages, sleep=args.sleep)
        try:
            collected = run_round(bulk_args)
        except Exception as exc:  # noqa: BLE001
            stop_reason = f"collector_error:{type(exc).__name__}:{exc}"
            break
        rows = load_items(ROOT / collected["out"]) if not Path(collected["out"]).is_absolute() else load_items(Path(collected["out"]))
        applied = apply(conn, rows) if rows else {"applied": 0, "fields": 0, "skipped": 0}
        report, _ = classify(parent, config)
        hard = report["hard_failures"]
        rolled = 0
        if hard:
            rolled = rollback_hard(conn, parent)
            report, _ = classify(parent, config)
            hard = report["hard_failures"]
        ratio = report["high_quality_ratio"]
        entry = {"round": round_no, "checked_at": report["checked_at"],
                 "ratio": ratio, "A": report["grades"].get("A", 0),
                 "by_kind_A": {k: v.get("A", 0) for k, v in report["by_kind"].items()},
                 "calls": collected["calls"], "items": collected["items"],
                 "applied": applied["applied"], "fields": applied["fields"],
                 "hard_failures": hard, "rolled_back": rolled,
                 "collector_stop": collected["stop"]}
        with progress_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        history.append(entry)
        state_path.write_text(json.dumps({"last_round": round_no, "ratio": ratio,
                                         "stop_reason": stop_reason, "target": target},
                                        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"[round {round_no}] A={entry['A']} ratio={ratio:.2%} "
              f"calls={collected['calls']} items={collected['items']} "
              f"fields+={applied['fields']} hard={hard}", flush=True)
        if ratio >= target and hard == 0:
            stop_reason = "target_reached"
            break
        if ratio - prev_ratio < 0.005:
            plateau += 1
        else:
            plateau = 0
        if plateau >= 3:
            stop_reason = "plateau_no_growth"
            break
        if collected["stop"]:
            stop_reason = collected["stop"]
            break
        prev_ratio = ratio
    else:
        stop_reason = stop_reason or "max_rounds"

    conn.close()
    report, grades = classify(parent, config)
    verification = audit(parent, None)
    (snapshot / "verification.json").write_text(
        json.dumps(verification, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (snapshot / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (snapshot / "quality_grades.jsonl").write_text(
        "\n".join(json.dumps(g, ensure_ascii=False) for g in grades) + "\n", encoding="utf-8")
    write_manifest(snapshot, report, {"stop_reason": stop_reason,
                                      "rounds": len(history),
                                      "target": target,
                                      "verification": {"hard_failures": verification["hard_failures"],
                                                       "integrity": verification["integrity_check"]}})
    print(json.dumps({"stop_reason": stop_reason, "rounds": len(history),
                      "ratio": report["high_quality_ratio"],
                      "A": report["grades"].get("A", 0),
                      "hard_failures": report["hard_failures"]}, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--target", type=float)
    ap.add_argument("--max-rounds", type=int, default=30)
    ap.add_argument("--calls-per-round", type=int, default=48)
    ap.add_argument("--offset-step", type=int, default=24)
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--sleep", type=float, default=0.8)
    ap.add_argument("--kinds", nargs="+", default=["attraction", "restaurant", "accommodation"])
    ap.add_argument("--extra-enrich", nargs="*", default=[])
    ap.add_argument("--resume", action="store_true")
    return run(ap.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
