"""Xi'an collection campaign controller: targets, status, run lifecycle.

Read-only against data/, ChinaTravel/ and existing results snapshots.
Writes only: collector_agent/xian_single_city/targets.json (with --write),
new results/xian_claude_<timestamp>/ directories, and the campaign log.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shorttrip.expansion_contract import FIELDS, OPTIONAL_VALUES  # noqa: E402

SANDBOX = ROOT / "ChinaTravel/chinatravel/environment/database"
TARGETS = ROOT / "collector_agent/xian_single_city/targets.json"
LOG = ROOT / "collector_agent/memory/xian_campaign_log.jsonl"
CITY = "西安"
CLASSES = {"attraction": "景点", "restaurant": "餐饮", "accommodation": "住宿"}

CITY_SLUGS = {
    "beijing": "北京", "chengdu": "成都", "chongqing": "重庆", "guangzhou": "广州",
    "hangzhou": "杭州", "nanjing": "南京", "shanghai": "上海", "shenzhen": "深圳",
    "suzhou": "苏州", "wuhan": "武汉",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def count_csv(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path, encoding="utf-8-sig") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def sandbox_stats() -> dict:
    rows = []
    for slug, cn in CITY_SLUGS.items():
        rows.append({
            "city": cn,
            "attraction": count_csv(SANDBOX / "attractions" / slug / "attractions.csv"),
            "restaurant": count_csv(SANDBOX / "restaurants" / slug / f"restaurants_{slug}.csv"),
            "accommodation": count_csv(SANDBOX / "accommodations" / slug / "accommodations.csv"),
        })
    n = len(rows)
    stats = {}
    for key in ("attraction", "restaurant", "accommodation"):
        values = [row[key] for row in rows]
        stats[key] = {
            "mean": round(sum(values) / n),
            "min": min(values),
            "max": max(values),
            "cities": n,
        }
    return {"per_city": stats, "rows": rows}


def sandbox_transport_stats() -> dict:
    """Per-city transport scale. Train uses the Chengdu benchmark from the task book."""
    subways = json.loads((SANDBOX / "transportation/subways.json").read_text(encoding="utf-8"))
    items = {}
    for slug, cn in CITY_SLUGS.items():
        lines = subways.get(slug) or []
        items[cn] = sum(len(line.get("stations") or []) for line in lines)
    poi = {}
    for slug, cn in CITY_SLUGS.items():
        path = SANDBOX / "poi" / slug / "poi.json"
        poi[cn] = len(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else 0

    def train_rows(city: str) -> int:
        total = 0
        for path in (SANDBOX / "intercity_transport/train").glob("*.json"):
            left, _, right = path.stem[5:].partition("_to_")
            if city in (left, right):
                total += len(json.loads(path.read_text(encoding="utf-8")))
        return total

    def flight_rows(city: str) -> int:
        path = SANDBOX / "intercity_transport/airplane.jsonl"
        if not path.exists():
            return 0
        total = 0
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if city in str(record.get("From") or "") or city in str(record.get("To") or ""):
                    total += 1
        return total

    n = len(CITY_SLUGS)
    return {
        "poi": {"mean": round(sum(poi.values()) / n), "min": min(poi.values()),
                "max": max(poi.values())},
        "metro_station": {"mean": round(sum(items.values()) / n), "min": min(items.values()),
                          "max": max(items.values())},
        "train": {"benchmark_chengdu": train_rows("成都"), "mean": None,
                  "note": "90 city-pair files double-count endpoints; Chengdu is the task-book benchmark (9 pairs x 2 directions)"},
        "flight": {"benchmark_chengdu": flight_rows("成都")},
    }


def build_targets() -> dict:
    stats = sandbox_stats()
    transport = sandbox_transport_stats()
    return {
        "city": CITY,
        "derived_from": "ChinaTravel/chinatravel/environment/database (10-city sandbox)",
        "generated_at": now_iso(),
        "milestone_task_book": {key: 300 for key in CLASSES},
        "parity_min": {key: stats["per_city"][key]["min"] for key in CLASSES},
        "parity_mean": {key: stats["per_city"][key]["mean"] for key in CLASSES},
        "parity_max": {key: stats["per_city"][key]["max"] for key in CLASSES},
        "completion_rule": "discovery counts >= parity_mean for attraction, restaurant and accommodation",
        "completion_target": {key: stats["per_city"][key]["mean"] for key in CLASSES},
        "transport": transport,
        "transport_target": {
            "poi": transport["poi"]["mean"],
            "metro_station": transport["metro_station"]["mean"],
            "train": transport["train"]["benchmark_chengdu"],
            "flight": transport["flight"]["benchmark_chengdu"],
        },
        "transport_note": "POI/metro use the 10-city mean; train/flight use the Chengdu task-book benchmark (9 city pairs x 2 directions).",
        "planning_ready_is_not_a_goal": (
            "price/opening-hours TTLs are 86400s, so a frozen static snapshot cannot be "
            "planning_ready by design; tier3 stays 0 and is reported, not gated"
        ),
        "sandbox_rows": stats["rows"],
    }


def load_targets() -> dict:
    if TARGETS.exists():
        return json.loads(TARGETS.read_text(encoding="utf-8"))
    return build_targets()


def latest_snapshot() -> Path | None:
    candidates = list((ROOT / "results").glob("xian_claude_*/snapshot_v*/catalog.sqlite3"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def open_catalog(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def native_complete(payload: dict) -> bool:
    data = payload.get("data") or {}
    required = [k for k in FIELDS.get(payload.get("kind"), ()) if k not in OPTIONAL_VALUES]
    return all(data.get(key) not in (None, "") for key in required)


def transport_status(conn: sqlite3.Connection) -> dict:
    counts = dict(conn.execute(
        f"select kind, count(*) from records where city='{CITY}' group by kind").fetchall())
    pairs = set()
    for kind in ("train", "flight"):
        for payload, in conn.execute(
                f"select payload from records where city='{CITY}' and kind=?", (kind,)):
            data = json.loads(payload).get("data") or {}
            frm, to = data.get("From"), data.get("To")
            if frm and to:
                pairs.add((kind, frm, to))
    both = sum(
        1 for kind, frm, to in pairs
        if frm == CITY and (kind, to, CITY) in pairs
    )
    return {
        "counts": counts,
        "bidirectional_city_pairs": both,
        "one_way_pairs": len([p for p in pairs if p[1] == CITY]) - both,
    }


def compute_status(snapshot: Path | None = None) -> dict:
    targets = load_targets()
    target = targets["completion_target"]
    snap = snapshot or latest_snapshot()
    if snap is None:
        return {"error": "no xian snapshot found", "checked_at": now_iso()}
    conn = open_catalog(snap)
    try:
        classes = {}
        for kind in CLASSES:
            rows = [json.loads(p) for p, in conn.execute(
                f"select payload from records where city='{CITY}' and kind=?", (kind,))]
            discovery = len(rows)
            native = sum(1 for p in rows if native_complete(p))
            goal = target[kind]
            classes[kind] = {
                "discovery": discovery,
                "native_complete": native,
                "target": goal,
                "delta": max(0, goal - discovery),
                "progress_pct": round(100 * discovery / goal, 1) if goal else None,
                "milestone_300_reached": discovery >= 300,
            }
        transport = transport_status(conn)
    finally:
        conn.close()
    manifest = snap.parent / "manifest.json"
    return {
        "run_id": snap.parents[1].name,
        "snapshot": snap.parent.name,
        "snapshot_path": str(snap.relative_to(ROOT)).replace("\\", "/"),
        "catalog_sha256": sha256_file(snap),
        "record_count": json.loads(manifest.read_text(encoding="utf-8")).get("record_count")
        if manifest.exists() else None,
        "classes": classes,
        "transport": transport,
        "transport_gap": {
            key: max(0, targets.get("transport_target", {}).get(key, 0) - transport["counts"].get(key, 0))
            for key in ("poi", "metro_station", "train", "flight")
        },
        "complete_classes": all(classes[k]["discovery"] >= classes[k]["target"] for k in CLASSES),
        "complete_transport": all(
            transport["counts"].get(key, 0) >= targets.get("transport_target", {}).get(key, 0)
            for key in ("poi", "metro_station", "train", "flight")),
        "complete": all(classes[k]["discovery"] >= classes[k]["target"] for k in CLASSES)
        and all(transport["counts"].get(key, 0) >= targets.get("transport_target", {}).get(key, 0)
                for key in ("poi", "metro_station", "train", "flight")),
        "next_gap": {k: classes[k]["delta"] for k in CLASSES},
        "checked_at": now_iso(),
    }


def print_status(status: dict) -> None:
    if "error" in status:
        print("status error:", status["error"])
        return
    print(f"run      {status['run_id']} / {status['snapshot']}")
    print(f"snapshot {status['snapshot_path']}  sha256={status['catalog_sha256'][:12]}…")
    print(f"{'类别':<6}{'discovery':>10}{'原生齐备':>10}{'目标':>8}{'差额':>8}{'进度':>9}")
    for kind, label in CLASSES.items():
        row = status["classes"][kind]
        print(f"{label:<6}{row['discovery']:>10}{row['native_complete']:>10}"
              f"{row['target']:>8}{row['delta']:>8}{str(row['progress_pct']) + '%':>9}")
    tr = status["transport"]
    targets = load_targets().get("transport_target", {})
    print("交通     " + "  ".join(
        f"{k}={tr['counts'].get(k, 0)}/{targets.get(k, '-')}" for k in ("poi", "metro_station", "train", "flight")))
    print(f"双向城际 {tr['bidirectional_city_pairs']}  单向 {tr['one_way_pairs']}")
    print("complete:", status["complete"], "  checked_at:", status["checked_at"])


def open_run(run_id: str | None, note: str | None) -> dict:
    run_id = run_id or "xian_claude_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ROOT / "results" / run_id
    if (out / "launch.json").exists():
        raise SystemExit(f"run already exists: {out}")
    out.mkdir(parents=True, exist_ok=True)
    parent = latest_snapshot()
    launch = {
        "run_id": run_id,
        "mode": "workbuddy-scheduled-agent",
        "parent_snapshot": str(parent.relative_to(ROOT)).replace("\\", "/") if parent else None,
        "parent_sha256": sha256_file(parent) if parent else None,
        "started_at": now_iso(),
        "note": note,
    }
    (out / "launch.json").write_text(
        json.dumps(launch, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"run_dir": str(out), **launch}, ensure_ascii=False, indent=1))
    return launch


def close_run(run_dir: str, state: str, reason: str, artifact: str | None) -> None:
    out = Path(run_dir)
    if not out.is_absolute():
        out = ROOT / run_dir
    record = {
        "run_id": out.name,
        "state": state,
        "reason": reason,
        "progress_artifact": artifact,
        "finished_at": now_iso(),
    }
    (out / "terminal_exit.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("targets")
    p.add_argument("--write", action="store_true")

    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p.add_argument("--snapshot")

    p = sub.add_parser("open")
    p.add_argument("--run-id")
    p.add_argument("--note")

    p = sub.add_parser("close")
    p.add_argument("--run", required=True)
    p.add_argument("--state", required=True,
                   choices=["checkpoint", "completed", "blocked", "user_stop_requested"])
    p.add_argument("--reason", required=True)
    p.add_argument("--artifact")

    args = parser.parse_args()
    if args.command == "targets":
        data = build_targets()
        if args.write:
            TARGETS.parent.mkdir(parents=True, exist_ok=True)
            TARGETS.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                               encoding="utf-8")
        print(json.dumps(data, ensure_ascii=False, indent=1))
    elif args.command == "status":
        status = compute_status(Path(args.snapshot) if args.snapshot else None)
        if args.json:
            print(json.dumps(status, ensure_ascii=False, indent=1))
        else:
            print_status(status)
    elif args.command == "open":
        open_run(args.run_id, args.note)
    else:
        close_run(args.run, args.state, args.reason, args.artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
