"""Grade Xi'an records by quality, score their sources, and emit refill work queues.

Quality is measured, not asserted:
  * L1 static fields must all be non-null (no lowering of the field standard)
  * every source_value field is re-checked against its local raw page
    (sha256 / verbatim quote / entity name or <=200m coordinate identity)
  * the contract gate, duplicate identity and coordinate bbox are re-derived
  * source quality is scored on authority / licence / verifiability /
    freshness / field coverage; only T2+ (>=0.60) can be grade A

Commands:
  status   --snapshot <catalog.sqlite3>  -> quality_report.json + console summary
  sources  --snapshot <...> [--evidence source_evidence.jsonl] -> source_scores.json
  queue    --snapshot <...> --out <jsonl> [--kind ...] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from shorttrip.expansion_contract import validate_record  # noqa: E402
from xian_verify import BBOX, CITY, RawCache, now_iso, norm  # noqa: E402
from xian_scope import scope_check  # noqa: E402

CONFIG_PATH = ROOT / "collector_agent" / "xian_single_city" / "quality_model.json"
HARD_ISSUES = {"raw_sha256_mismatch", "quote_not_verbatim", "name_not_in_raw",
               "evidence_not_in_table", "payload_not_json", "field_without_evidence_ref",
               "dangling_evidence"}

# Measured in the pilot reports referenced by quality_model.json. These are
# recorded facts, not estimates: exact-match / usable-item counts from each run.
PILOT_MEASUREMENTS = {
    "you.ctrip.com / gs.ctrip.com": {"pages": 89, "usable": 3, "verifiability": 1.0,
                                     "authority": 0.80, "licence": 0.60, "coverage": 0.40},
    "www.dianping.com": {"pages": 20, "usable": 0, "verifiability": 0.0,
                         "authority": 0.55, "licence": 0.20, "coverage": 0.10},
    "www.meituan.com / i.meituan.com": {"pages": 2, "usable": 0, "verifiability": 0.0,
                                        "authority": 0.55, "licence": 0.20, "coverage": 0.0},
    "flights.ch.com": {"pages": 10, "usable": 65, "verifiability": 1.0,
                       "authority": 0.92, "licence": 0.90, "coverage": 0.85},
    "www.avionio.com / www.flightaware.com / www.flightstats.com": {
        "pages": 4, "usable": 79, "verifiability": 1.0,
        "authority": 0.45, "licence": 0.55, "coverage": 0.45},
    "kyfw.12306.cn": {"pages": 18, "usable": 405, "verifiability": 1.0,
                      "authority": 0.92, "licence": 0.85, "coverage": 0.90},
    "restapi.amap.com": {"pages": 100, "usable": 2110, "verifiability": 1.0,
                         "authority": 0.78, "licence": 0.55, "coverage": 0.55},
    "api.map.baidu.com": {"pages": 360, "usable": 78, "verifiability": 1.0,
                          "authority": 0.76, "licence": 0.55, "coverage": 0.50},
}


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def source_key(payload: dict, evidence: dict) -> str:
    urls = []
    for prov in (payload.get("field_provenance") or {}).values():
        if isinstance(prov, dict) and prov.get("status") == "source_value" and prov.get("source_url"):
            urls.append(prov["source_url"])
    url = Counter(urls).most_common(1)[0][0] if urls else (payload.get("source_url") or "")
    if "//" in url:
        return url.split("//")[1].split("/")[0]
    if url.startswith("urn:"):
        return url.split(":")[1]
    return "legacy:" + str(payload.get("authority") or "unknown")


def days_since(stamp: str | None, now: datetime) -> float:
    if not stamp:
        return 1e6
    try:
        then = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return (now - then).total_seconds() / 86400.0
    except (ValueError, TypeError):
        return 1e6


def classify(snapshot: Path, config: dict) -> tuple[dict, list[dict]]:
    import sqlite3
    conn = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)
    integrity = conn.execute("pragma integrity_check").fetchone()[0]
    evidence = {}
    for eid, raw in conn.execute("select id, payload from evidence"):
        try:
            evidence[eid] = json.loads(raw)
        except json.JSONDecodeError:
            evidence[eid] = {}
    rows = conn.execute(
        f"select id, kind, name, payload, gate from records where city='{CITY}'").fetchall()
    conn.close()

    cache = RawCache()
    l1 = config["L1_static_fields"]
    now = datetime.now(timezone.utc)
    identities: dict[str, set[str]] = defaultdict(set)
    grades: list[dict] = []
    src_metrics: dict[str, dict] = defaultdict(lambda: {
        "authority": [], "licence": [], "verified": 0, "records": 0,
        "fresh": 0, "coverage": 0.0})

    for rid, kind, name, payload_raw, gate_raw in rows:
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            grades.append({"id": rid, "kind": kind, "name": name, "grade": "D",
                           "issues": ["payload_not_json"]})
            continue
        data = payload.get("data") or {}
        required = l1.get(kind, [])
        missing = [k for k in required if data.get(k) in (None, "")]
        l1_ratio = 1.0 - (len(missing) / len(required) if required else 0.0)
        gate = validate_record(payload, now=now_iso())
        contract_ok = bool(gate.get("discovery_ok"))
        scope = scope_check(kind, data)
        scope_tier = scope["tier"]

        issues = []
        checked = local_ok = 0
        for field, prov in (payload.get("field_provenance") or {}).items():
            if not isinstance(prov, dict) or prov.get("status") != "source_value":
                continue
            eid = prov.get("evidence_id")
            ev = evidence.get(eid)
            if not ev:
                issues.append("evidence_not_in_table")
                continue
            raw_path = ev.get("raw_path")
            cached = cache.get(raw_path) if raw_path else None
            if cached is None:
                issues.append("raw_missing")
                continue
            digest, text_norm, stripped = cached
            checked += 1
            expected = ev.get("raw_sha256")
            if expected and digest != expected:
                issues.append("raw_sha256_mismatch")
                continue
            quote = norm(prov.get("quote") or ev.get("quote") or "")
            if quote and quote not in text_norm:
                issues.append("quote_not_verbatim")
                continue
            if norm(name) not in text_norm:
                distance = ev.get("identity_distance_m")
                if (ev.get("identity_basis") == "coordinate_match"
                        and distance is not None and float(distance) <= 200):
                    local_ok += 1
                    continue
                issues.append("name_not_in_raw")
                continue
            local_ok += 1
        verified = checked > 0 and local_ok == checked and not any(
            i in HARD_ISSUES for i in issues)
        hard = [i for i in issues if i in HARD_ISSUES]

        # coordinate checks
        coord_problem = None
        if kind in ("poi", "metro_station", "attraction", "restaurant", "accommodation"):
            lat = lon = None
            position = data.get("position")
            if isinstance(position, list) and len(position) == 2:
                lat, lon = position
            elif isinstance(position, str) and "," in position:
                lon, lat = position.split(",")[:2]
            elif data.get("lat") is not None:
                lat, lon = data.get("lat"), data.get("lon")
            if lat is not None and lon is not None:
                try:
                    if not (BBOX["lat"][0] <= float(lat) <= BBOX["lat"][1]
                            and BBOX["lon"][0] <= float(lon) <= BBOX["lon"][1]):
                        coord_problem = "coord_outside_xian"
                except (TypeError, ValueError):
                    coord_problem = "coord_not_numeric"
                if payload.get("coordinate_system") not in ("WGS84", "GCJ02", "BD09"):
                    coord_problem = coord_problem or "coord_undeclared"

        # duplicate identity (same key derivation as xian_verify.py)
        ident = data.get("TrainID") or data.get("FlightID") or name
        if kind == "metro_station":
            import re
            ident = re.sub(r"(\(地铁站\)|[-]?地铁站)$", "", str(ident))
            ident = f"{ident}@{data.get('line') or '未知线路'}"
        if kind in ("poi", "restaurant", "accommodation", "attraction"):
            lat, lon = data.get("lat"), data.get("lon")
            position = data.get("position")
            if isinstance(position, list) and len(position) == 2:
                lat, lon = position
            elif isinstance(position, str) and "," in position:
                lon, lat = position.split(",")[:2]
            if lat is not None and lon is not None:
                try:
                    ident = f"{ident}@{round(float(lat), 3)},{round(float(lon), 3)}"
                except (TypeError, ValueError):
                    pass
        ident_norm = norm(str(ident)).lower()
        duplicate = ident_norm in identities[kind]
        identities[kind].add(ident_norm)

        key = source_key(payload, evidence)
        m = src_metrics[key]
        m["records"] += 1
        m["authority"].append(payload.get("authority") or "unknown")
        m["licence"].append(payload.get("licence_status") or "unknown")
        m["verified"] += 1 if verified else 0
        m["fresh"] += 1 if days_since(payload.get("retrieved_at"), now) <= config["source_score"]["freshness_days"] else 0
        m["coverage"] += l1_ratio

        grades.append({
            "id": rid, "kind": kind, "name": name, "grade": "?", "l1_missing": missing,
            "l1_ratio": round(l1_ratio, 3), "verified": verified, "checked": checked,
            "contract_ok": contract_ok, "duplicate": duplicate,
            "coord_problem": coord_problem, "issues": issues, "source_key": key,
            "scope_tier": scope_tier, "scope_pair": scope["pair"], "scope_note": scope["note"],
        })

    scores = compute_scores(src_metrics, config)
    for g in grades:
        score = scores.get(g.get("source_key"), {}).get("total", 0.0)
        g["source_score"] = round(score, 3)
        if (g.get("issues") and any(i in HARD_ISSUES for i in g["issues"])) or \
                not g.get("contract_ok") or g.get("duplicate") or g.get("coord_problem") or \
                g.get("grade") == "D":
            g["grade"] = "D"
        elif g["verified"] and not g["l1_missing"] and score >= 0.60:
            g["grade"] = "A"
        elif g["verified"] and score >= 0.60:
            g["grade"] = "B"
        else:
            g["grade"] = "C"

    counts = Counter(g["grade"] for g in grades)
    total = len(grades)
    by_kind = defaultdict(Counter)
    for g in grades:
        by_kind[g["kind"]][g["grade"]] += 1
    missing_fields = defaultdict(Counter)
    for g in grades:
        if g["grade"] in ("B", "C", "D"):
            for f in g.get("l1_missing", []):
                missing_fields[g["kind"]][f] += 1
    hard_failures = sum(1 for g in grades if any(i in HARD_ISSUES for i in g.get("issues", [])))
    scope_by_kind = defaultdict(Counter)
    scope_tier_grades = defaultdict(Counter)
    covered = defaultdict(set)
    for g in grades:
        if g["kind"] in ("train", "flight"):
            tier = g["scope_tier"]
            scope_by_kind[g["kind"]][tier] += 1
            scope_tier_grades[tier][g["grade"]] += 1
            if g["scope_pair"]:
                a, b = g["scope_pair"].split("->")
                other = b if a == "西安" else a
                if other not in ("OUT", "西安"):
                    covered[g["kind"]].add(other)
    covered = {k: sorted(v) for k, v in covered.items()}
    report = {
        "checked_at": now_iso(), "snapshot": str(snapshot),
        "integrity_check": integrity, "records": total,
        "grades": dict(counts), "high_quality_ratio": round(counts["A"] / total, 4) if total else 0,
        "target": config["target"]["high_quality_ratio"],
        "complete": counts["A"] / total >= config["target"]["high_quality_ratio"] if total else False,
        "hard_failures": hard_failures,
        "by_kind": {k: dict(v) for k, v in sorted(by_kind.items())},
        "missing_l1_fields": {k: dict(v.most_common()) for k, v in sorted(missing_fields.items())},
        "scope": {
            "policy": "KEEP-AND-DOCUMENT (user 2026-11-08): cross-city records to expansion-set cities are kept and NOT downgraded; each record carries a documented tier",
            "reference_sets": {
                "native10": "ChinaTravel 原生 10 城；intercity_transport 全互联，单城视角 407 列车 / 160 航班",
                "expansion30": "data/expansion_v1_20261022/collection_manifest.json city_windows 的 30 城（含西安），2026-10-22 最早扩展集",
                "other_city": "两端含西安但目标城市不在上述两个集合（聚合看板/航司页真实航线）",
                "no_xian": "两端都不含西安的混入城市对",
            },
            "by_kind": {k: dict(v) for k, v in sorted(scope_by_kind.items())},
            "grades_by_tier": {k: dict(v) for k, v in sorted(scope_tier_grades.items())},
            "covered_cities": covered,
            "kept_total": sum(1 for g in grades if g["kind"] in ("train", "flight")),
        },
        "source_scores": scores,
    }
    return report, grades


def compute_scores(metrics: dict, config: dict, evidence_rows: list[dict] | None = None) -> dict:
    ss = config["source_score"]
    w = ss["weights"]
    ab, lb = ss["authority_base"], ss["licence_base"]
    out = {}
    for key, m in metrics.items():
        n = max(1, m["records"])
        authority = ab.get(Counter(m["authority"]).most_common(1)[0][0], 0.30)
        licence = lb.get(Counter(m["licence"]).most_common(1)[0][0], 0.20)
        parts = {
            "authority": authority, "licence": licence,
            "verifiability": m["verified"] / n,
            "freshness": m["fresh"] / n,
            "field_coverage": m["coverage"] / n,
        }
        out[key] = {**{k: round(v, 3) for k, v in parts.items()},
                    "records": m["records"], "total": round(sum(w[k] * v for k, v in parts.items()), 3),
                    "tier": next((t for t, floor in ss["tiers"].items()
                                  if sum(w[k] * v for k, v in parts.items()) >= floor), "T4")}
    for site, pm in PILOT_MEASUREMENTS.items():
        parts = {"authority": pm["authority"], "licence": pm["licence"],
                 "verifiability": pm["verifiability"], "freshness": 1.0,
                 "field_coverage": pm["coverage"]}
        total = round(sum(w[k] * v for k, v in parts.items()), 3)
        out["pilot:" + site] = {**{k: round(v, 3) for k, v in parts.items()},
                                "records": pm["usable"], "pages": pm["pages"], "total": total,
                                "tier": next((t for t, floor in ss["tiers"].items() if total >= floor), "T4"),
                                "pilot": True}
    for row in evidence_rows or []:
        key = row.get("site") or row.get("source_key")
        if not key:
            continue
        target = out.get(key) or out.get("pilot:" + key)
        if not target or not row.get("raw_path"):
            continue
        evidence_path = ROOT / row["raw_path"]
        if not evidence_path.exists() or (row.get("quote") and
                                          norm(row["quote"]) not in norm(evidence_path.read_text("utf-8", errors="replace"))):
            continue
        for dim in ("authority", "licence", "verifiability", "freshness", "field_coverage"):
            if isinstance(row.get(dim), (int, float)):
                target[dim] = float(row[dim])
        total = round(sum(w[k] * target[k] for k in w), 3)
        target["total"] = total
        target["tier"] = next((t for t, floor in ss["tiers"].items() if total >= floor), "T4")
        target["evidence_reviewed"] = True
    return out


def print_status(report: dict) -> None:
    g = report["grades"]
    print(f"记录 {report['records']}  integrity={report['integrity_check']}  hard_failures={report['hard_failures']}")
    print(f"A 优质 {g.get('A', 0)}  B 合格 {g.get('B', 0)}  C 基础 {g.get('C', 0)}  D 问题 {g.get('D', 0)}")
    print(f"优质占比 {report['high_quality_ratio']:.2%} / 目标 {report['target']:.0%}   complete={report['complete']}")
    print("类别     A     B     C     D    A占比")
    for k, v in report["by_kind"].items():
        n = sum(v.values())
        print(f"{k:<14}{v.get('A',0):>5}{v.get('B',0):>6}{v.get('C',0):>6}{v.get('D',0):>6}   {v.get('A',0)/n:.1%}")
    print("缺失 L1 字段 TOP:")
    for k, v in report["missing_l1_fields"].items():
        print(f"  {k}: {list(v.items())[:6]}")
    sc = report.get("scope", {})
    if sc:
        print(f"跨城范围分层(保留并标注) {sc['by_kind']}  共 {sc['kept_total']} 条")
        print(f"分层质量 {sc['grades_by_tier']}")
        print(f"已覆盖目标城市 {sc['covered_cities']}")
    print("来源评分 TOP:")
    for k, v in sorted(report["source_scores"].items(), key=lambda x: -x[1]["total"])[:10]:
        print(f"  {v['tier']} {v['total']:.3f} {k} (n={v['records']})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("status", "sources", "queue"))
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--out")
    ap.add_argument("--evidence")
    ap.add_argument("--kind")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--grade", default="B,C,D")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    config = load_config()
    snapshot = Path(args.snapshot)
    if not snapshot.is_absolute():
        snapshot = ROOT / snapshot

    ev_rows = []
    if args.evidence and Path(args.evidence).exists():
        ev_rows = [json.loads(l) for l in Path(args.evidence).read_text(encoding="utf-8").splitlines() if l.strip()]
    report, grades = classify(snapshot, config)
    if args.command == "sources":
        report["source_scores"] = compute_scores(
            {}, config, ev_rows) if False else report["source_scores"]
        # re-apply external evidence on top of the computed scores
        merged = compute_scores({}, config, [])  # no-op placeholder to keep pure
        for row in ev_rows:
            key = row.get("site") or row.get("source_key")
            target = report["source_scores"].get(key) or report["source_scores"].get("pilot:" + key)
            if not target or not row.get("raw_path"):
                continue
            p = ROOT / row["raw_path"]
            if not p.exists() or (row.get("quote") and norm(row["quote"]) not in norm(p.read_text("utf-8", errors="replace"))):
                continue
            w = config["source_score"]["weights"]
            for dim in w:
                if isinstance(row.get(dim), (int, float)):
                    target[dim] = float(row[dim])
            total = round(sum(w[k] * target[k] for k in w), 3)
            target["total"] = total
            target["tier"] = next((t for t, floor in config["source_score"]["tiers"].items()
                                   if total >= floor), "T4")
            target["evidence_reviewed"] = True
        out = Path(args.out) if args.out else ROOT / "collector_agent/xian_single_city/source_scores.json"
        out.write_text(json.dumps({"checked_at": now_iso(), "model": "quality-v1",
                                   "newly_opened_sites": config["source_score"]["newly_opened_sites"],
                                   "scores": report["source_scores"]}, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        print(f"source_scores written: {out}")
        for k, v in sorted(report["source_scores"].items(), key=lambda x: -x[1]["total"]):
            print(f"  {v['tier']} {v['total']:.3f} {k} (n={v['records']})")
        return 0
    if args.command == "queue":
        allowed = set(args.grade.split(","))
        rows = [g for g in grades if g["grade"] in allowed and (not args.kind or g["kind"] == args.kind)]
        rows.sort(key=lambda g: (-len(g.get("l1_missing", [])), g["kind"], g["name"]))
        out = Path(args.out)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            for g in rows[:args.limit]:
                f.write(json.dumps({"id": g["id"], "kind": g["kind"], "name": g["name"],
                                    "grade": g["grade"], "missing": g["l1_missing"],
                                    "verified": g["verified"], "source_key": g["source_key"]},
                                   ensure_ascii=False) + "\n")
        print(f"queue written: {out} ({min(len(rows), args.limit)} rows of {len(rows)})")
        return 0
    out = Path(args.out) if args.out else snapshot.parent / "quality_report.json"
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    grades_path = out.parent / "quality_grades.jsonl"
    grades_path.write_text("\n".join(json.dumps(g, ensure_ascii=False) for g in grades) + "\n", encoding="utf-8")
    if not args.quiet:
        print_status(report)
        print(f"report: {out}\ngrades: {grades_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
