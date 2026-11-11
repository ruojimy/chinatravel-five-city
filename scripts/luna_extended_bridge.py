"""Read-only B-arm tools and lossless Luna response intake.

This bridge never selects, orders, schedules, repairs, or synthesizes an
itinerary. Luna must return the native ChinaTravel plan as JSON. Candidate
catalog facts are benchmark/reference data only; this module makes no network
calls and does not promote them to current real-world facts.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "ChinaTravel")]
CATALOG = ROOT / "data" / "catalog_v1_1_20261022" / "catalog.sqlite3"
TAGSTORE = ROOT / "data" / "tag_store_v2.sqlite"
OUT = ROOT / "results" / "luna_tencity_20261106" / "implementation_b"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

KINDS = {"attraction", "restaurant", "accommodation", "poi", "metro_station", "train", "flight"}
PLAN_PROMPT = """You are the Luna planner for arm B (extended ten-city data architecture).
Produce a complete native ChinaTravel plan JSON for the supplied public query.
You must personally choose every entity, activity order, start/end time, local
transport mode and departure time, outbound/return intercity service, hotel,
meal, and cost-bearing choice. Use only entities and tool results you actually
inspected. Tool results are frozen benchmark/reference data, not current real
world confirmations. Do not claim feasibility when facts/routes are unavailable.

Return exactly one JSON object matching the official native plan shape. Do not
delegate choices to a planner, scheduler or helper. Do not emit suggested repair
steps. Do not use hidden labels, oracle fields, or checker feedback. This is a
first-draft submission; preserve it verbatim. Unknown/unavailable evidence must
be represented honestly in the plan or the accompanying error/limitations
field, never guessed. The orchestration layer will run the official three gates
only after your response is saved.

Read-only tools: catalog_list(kind, city, limit, offset), catalog_search(kind,
city, text, limit, offset), catalog_entity(record_id), catalog_preflight(record_id),
catalog_tags(record_id), tag_store_search(city, poi_name, tag_id, limit, offset),
catalog_claims(record_id, field), goto(city, start, end,
mode, departure), and intercity_search(from_city, to_city, mode). Tool outputs
contain evidence/benchmark status. These tools return data only and never
generate a plan."""


def _db():
    db = sqlite3.connect(f"file:{CATALOG.as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def _tag_db():
    db = sqlite3.connect(f"file:{TAGSTORE.as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    value = json.loads(row["payload"])
    return {"record_id": row["id"], "kind": row["kind"], "city": row["city"],
            "name": row["name"], "payload": value,
            "evidence_status": value.get("trust_status", "unknown"),
            "source_updated_at": value.get("source_updated_at"),
            "needs_live_verification": value.get("needs_live_verification", True)}


def catalog_list(kind: str, city: str, limit: int = 20, offset: int = 0, lang: str = "zh") -> dict:
    if kind not in KINDS: raise ValueError("unsupported kind")
    if lang != "zh": raise ValueError("B arm is fixed to zh view")
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    with _db() as db:
        rows = db.execute("SELECT id,kind,city,name,payload FROM records WHERE lang=? AND kind=? AND city=? ORDER BY id LIMIT ? OFFSET ?",
                          (lang, kind, city, limit, offset)).fetchall()
        total = db.execute("SELECT count(*) FROM records WHERE lang=? AND kind=? AND city=?", (lang, kind, city)).fetchone()[0]
    return {"records": [_decode(r) for r in rows], "returned": len(rows), "catalog_total": total,
            "offset": offset, "next_offset": offset + len(rows) if offset + len(rows) < total else None,
            "lang": lang, "catalog_hash_scope": "catalog_v1_1_20261022", "planning_or_real_world_certification": False}


def catalog_search(kind: str, city: str, text: str, limit: int = 20, offset: int = 0, lang: str = "zh") -> dict:
    if kind not in KINDS: raise ValueError("unsupported kind")
    if lang != "zh": raise ValueError("B arm is fixed to zh view")
    limit = max(1, min(int(limit), 100)); offset = max(0, int(offset)); needle = f"%{text}%"
    with _db() as db:
        rows = db.execute("SELECT id,kind,city,name,payload FROM records WHERE lang=? AND kind=? AND city=? AND (name LIKE ? OR payload LIKE ?) ORDER BY id LIMIT ? OFFSET ?",
                          (lang, kind, city, needle, needle, limit, offset)).fetchall()
        total = db.execute("SELECT count(*) FROM records WHERE lang=? AND kind=? AND city=? AND (name LIKE ? OR payload LIKE ?)",
                           (lang, kind, city, needle, needle)).fetchone()[0]
    return {"records": [_decode(r) for r in rows], "returned": len(rows), "match_total": total,
            "offset": offset, "next_offset": offset + len(rows) if offset + len(rows) < total else None,
            "lang": lang,
            "planning_or_real_world_certification": False}


def catalog_entity(record_id: str) -> dict:
    with _db() as db:
        row = db.execute("SELECT id,kind,city,name,payload FROM records WHERE lang='zh' AND id=?", (record_id,)).fetchone()
    if row is None: raise KeyError(f"unknown record_id: {record_id}")
    return _decode(row)


def catalog_preflight(record_id: str) -> dict:
    item = catalog_entity(record_id)
    rec = item["payload"]
    expected = {"schema_version": "travel-catalog-v1", "language": "zh", "kind": item["kind"],
                "record_id": record_id, "source_id": "chinatravel_sandbox"}
    checks = {key: rec.get(key) == value for key, value in expected.items()}
    checks["data_object"] = isinstance(rec.get("data"), dict)
    checks["tags_list"] = isinstance(rec.get("tags"), list)
    return {"record_id": record_id, "schema": "travel-catalog-v1 provenance sidecar",
            "structural_checks": checks, "structural_ok": all(checks.values()),
            "source_freshness": rec.get("freshness_status"), "trust_status": rec.get("trust_status"),
            "needs_live_verification": rec.get("needs_live_verification"),
            "uncertainty_flags": rec.get("uncertainty_flags", []),
            "notice": "sidecar structure/source metadata only; not current hours, availability, route proof, or identity certification"}


def catalog_tags(record_id: str, limit: int = 40, offset: int = 0) -> dict:
    limit = max(1, min(int(limit), 100)); offset = max(0, int(offset))
    with _db() as db:
        if not db.execute("SELECT 1 FROM records WHERE lang='zh' AND id=?", (record_id,)).fetchone():
            raise KeyError(f"unknown zh record_id: {record_id}")
        rows = db.execute("SELECT tag,value FROM tags WHERE id=? ORDER BY tag,value LIMIT ? OFFSET ?",
                          (record_id, limit, offset)).fetchall()
        total = db.execute("SELECT count(*) FROM tags WHERE id=?", (record_id,)).fetchone()[0]
        entity = db.execute("SELECT city,name FROM records WHERE lang='zh' AND id=?", (record_id,)).fetchone()
    with _tag_db() as tdb:
        extra = tdb.execute("SELECT * FROM tags WHERE city=? AND poi_name=? AND status='accept' ORDER BY tag_id,source_name,tag_uid",
                            (entity[0], entity[1])).fetchall()
    return {"record_id": record_id, "tags": [{"tag": r[0], "value": json.loads(r[1])} for r in rows],
            "returned": len(rows), "total": total, "offset": offset,
            "next_offset": offset + len(rows) if offset + len(rows) < total else None,
            "status": "benchmark_attribute_or_derived_recall_hint",
            "tag_store_v2": [_tag_row(r) for r in extra],
            "tag_store_snapshot": "tag-20261022T062125",
            "tag_store_notice": "separate source evidence; accepted status is not current fact or real-world qualification"}


def _tag_row(row: sqlite3.Row) -> dict:
    item = dict(row)
    for key in ("value", "gates", "payload"):
        try: item[key] = json.loads(item[key])
        except (TypeError, json.JSONDecodeError): pass
    item["live_fact"] = False
    return item


def tag_store_search(city: str | None = None, poi_name: str | None = None,
                     tag_id: str | None = None, limit: int = 20, offset: int = 0) -> dict:
    limit = max(1, min(int(limit), 100)); offset = max(0, int(offset))
    where=[]; params=[]
    if city is not None: where.append("city=?"); params.append(city)
    if poi_name is not None: where.append("poi_name=?"); params.append(poi_name)
    if tag_id is not None: where.append("tag_id=?"); params.append(tag_id)
    clause=" WHERE "+" AND ".join(where) if where else ""
    with _tag_db() as db:
        rows=db.execute("SELECT * FROM tags"+clause+" ORDER BY city,poi_name,tag_id,source_name,tag_uid LIMIT ? OFFSET ?",
                        (*params,limit,offset)).fetchall()
        total=db.execute("SELECT count(*) FROM tags"+clause,params).fetchone()[0]
    return {"tags":[_tag_row(r) for r in rows],"returned":len(rows),"total":total,
            "offset":offset,"next_offset":offset+len(rows) if offset+len(rows)<total else None,
            "snapshot":"tag-20261022T062125","evidence_only":True}


def catalog_claims(record_id: str, field: str | None = None, limit: int = 40, offset: int = 0) -> dict:
    limit = max(1, min(int(limit), 100)); offset = max(0, int(offset))
    with _db() as db:
        if not db.execute("SELECT 1 FROM records WHERE lang='zh' AND id=?", (record_id,)).fetchone():
            raise KeyError(f"unknown zh record_id: {record_id}")
        where = "entity_id=?" + (" AND field=?" if field else "")
        params = (record_id, field) if field else (record_id,)
        rows = db.execute(f"SELECT field,payload FROM claims WHERE {where} ORDER BY field,id LIMIT ? OFFSET ?",
                          (*params, limit, offset)).fetchall()
        total = db.execute(f"SELECT count(*) FROM claims WHERE {where}", params).fetchone()[0]
    return {"record_id": record_id, "claims": [{"field": r[0], "claim": json.loads(r[1])} for r in rows],
            "returned": len(rows), "total": total, "offset": offset,
            "next_offset": offset + len(rows) if offset + len(rows) < total else None,
            "notice": "append-only claims require independent gates; no claim here means verified fact"}


def goto(city: str, start: str, end: str, mode: str, departure: str) -> dict:
    from chinatravel.environment.tools.transportation.apis import Transportation
    transport = Transportation(lang="zh")
    try: result = transport.goto(city, start, end, departure, mode)
    except Exception as exc: result = None; error = f"{type(exc).__name__}: {exc}"
    else: error = None
    return {"city": city, "start": start, "end": end, "mode": mode, "departure": departure,
            "available": bool(result), "legs": result or [], "error": error,
            "source": "official ChinaTravel Transportation.goto", "real_world_route_proof": False}


def intercity_search(from_city: str, to_city: str, mode: str = "any") -> dict:
    modes = [mode] if mode in ("train", "airplane") else ["train", "airplane"]
    rows = []
    with _db() as db:
        for m in modes:
            kind = "train" if m == "train" else "flight"
            records = db.execute("SELECT id,kind,city,name,payload FROM records WHERE lang='zh' AND kind=? ORDER BY id",
                                 (kind,)).fetchall()
            for row in records:
                item = _decode(row); data = item["payload"].get("data", {})
                if str(data.get("From", "")).startswith(from_city) and str(data.get("To", "")).startswith(to_city):
                    rows.append({"mode": m, "record": item})
    return {"records": rows, "returned": len(rows), "source": "zh travel_catalog snapshot",
            "real_world_availability": False}


TOOLS = {"catalog_list": catalog_list, "catalog_search": catalog_search,
         "catalog_entity": catalog_entity, "catalog_preflight": catalog_preflight,
         "catalog_tags": catalog_tags, "tag_store_search": tag_store_search, "catalog_claims": catalog_claims,
         "goto": goto, "intercity_search": intercity_search}


def _load_query(split: str, uid: str) -> dict:
    folder = ROOT / "ChinaTravel" / "chinatravel" / "data" / split
    matches = []
    for path in sorted(folder.glob("*.json")):
        try:
            val = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(val, dict) and val.get("uid") == uid: matches.append((path, val))
        except (OSError, json.JSONDecodeError):
            continue
    if len(matches) != 1: raise ValueError(f"expected exactly one {split}/{uid} query, found {len(matches)}")
    path, query = matches[0]
    public = {k: v for k, v in query.items() if k != "hard_logic_py"}
    return {"path": str(path.relative_to(ROOT)), "query": public}


def prepare(split: str, uid: str, request_id: str | None = None) -> Path:
    q = _load_query(split, uid); rid = request_id or f"b_{split}_{uid}"
    path = OUT / "requests" / f"{rid}.json"
    user = (f"Arm B, split={split}, uid={uid}. Public query follows.\n"
            f"{json.dumps(q['query'], ensure_ascii=False, indent=2)}\n"
            f"Catalog snapshot is {CATALOG.name} under {CATALOG.parent.name}; use the read-only tools.\n"
            "Return one native plan JSON object. Preserve all actual choices in your response.")
    request = {"arm": "implementation_b", "uid": uid,
               "messages": [{"role": "system", "content": PLAN_PROMPT}, {"role": "user", "content": user}],
               "call_kwargs": {"model": "gpt-6-luna", "reasoning_effort": "medium",
                               "tool_names": sorted(TOOLS), "tool_loop": True,
                               "checker_feedback_before_first_output": False},
               "split": split, "public_query": q["query"], "query_source": q["path"],
               "protocol": "luna-extended-b-native-v3"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(request, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return path


def prepare_all() -> dict:
    counts = {}; errors = []
    for split in ("easy", "medium", "human"):
        folder = ROOT / "ChinaTravel" / "chinatravel" / "data" / split
        ids = []
        for path in sorted(folder.glob("*.json")):
            try:
                query = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(query, dict) and isinstance(query.get("uid"), str): ids.append(query["uid"])
            except (OSError, json.JSONDecodeError) as exc:
                errors.append({"path": str(path), "error": str(exc)})
        made = 0
        for uid in ids:
            request_path = OUT / "requests" / f"b_{split}_{uid}.json"
            if request_path.exists():
                old = json.loads(request_path.read_text(encoding="utf-8"))
                if old.get("uid") != uid or old.get("split") != split:
                    errors.append({"uid": uid, "error": "existing request mismatch"})
                continue
            prepare(split, uid); made += 1
        counts[split] = {"source_tasks": len(ids), "new_requests": made, "existing_requests": len(ids)-made}
    return {"counts": counts, "errors": errors, "source_total": sum(x["source_tasks"] for x in counts.values()),
            "created_total": sum(x["new_requests"] for x in counts.values()), "out": str(OUT / "requests")}


def prepare_shard(remainder: int = 0, modulus: int = 2, splits: tuple[str, ...] = ("easy", "medium", "human")) -> dict:
    if modulus < 1 or not 0 <= remainder < modulus: raise ValueError("require 0 <= remainder < modulus")
    counts = {}; errors = []
    for split in splits:
        folder = ROOT / "ChinaTravel" / "chinatravel" / "data" / split
        paths = sorted(folder.glob("*.json")); ids = []
        for path in paths:
            try:
                val = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(val, dict) and isinstance(val.get("uid"), str): ids.append(val["uid"])
            except (OSError, json.JSONDecodeError) as exc: errors.append({"path": str(path), "error": str(exc)})
        selected = [uid for i, uid in enumerate(ids) if i % modulus == remainder]
        made = 0
        for uid in selected:
            rid = f"b_{split}_{uid}"
            target = OUT / "requests" / f"{rid}.json"
            if target.exists():
                old = json.loads(target.read_text(encoding="utf-8"))
                if old.get("uid") == uid and old.get("split") == split: continue
                errors.append({"uid": uid, "error": "existing request mismatch"}); continue
            try: prepare(split, uid, rid); made += 1
            except Exception as exc: errors.append({"uid": uid, "error": f"{type(exc).__name__}: {exc}"})
        counts[split] = {"split_tasks": len(ids), "shard_tasks": len(selected), "new_requests": made,
                         "existing_requests": len(selected) - made}
    return {"remainder": remainder, "modulus": modulus, "counts": counts, "errors": errors,
            "source_total": sum(x["split_tasks"] for x in counts.values()),
            "shard_total": sum(x["shard_tasks"] for x in counts.values()),
            "new_requests": sum(x["new_requests"] for x in counts.values()), "out": str(OUT / "requests")}


def _extract_plan(text: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    val = json.loads(raw)
    if not isinstance(val, dict): raise ValueError("response text must be one JSON object")
    if not isinstance(val.get("itinerary"), list) or not val["itinerary"]:
        raise ValueError("native plan must contain a nonempty itinerary list")
    if not any(isinstance(day, dict) and day.get("activities") for day in val["itinerary"]):
        raise ValueError("native plan has no activities")
    return val


def ingest(response_path: Path) -> dict:
    response = json.loads(response_path.read_text(encoding="utf-8"))
    uid = response["uid"]; rid = response_path.stem
    request_path = OUT / "requests" / f"{rid}.json"
    if not request_path.exists(): raise FileNotFoundError(f"matching request missing: {request_path}")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if request["uid"] != uid: raise ValueError("response UID does not match request")
    attempt = "base" if rid == f"b_{request['split']}_{uid}" else rid.rsplit("_", 1)[-1]
    artifact_key = uid if attempt == "base" else f"{uid}__{attempt}"
    raw_dir = OUT / "raw"; plan_dir = OUT / "nativeplans"; eval_dir = OUT / "evaluations"
    for p in (raw_dir / f"{artifact_key}.txt", plan_dir / f"{artifact_key}.json", eval_dir / f"{artifact_key}.json"):
        if p.exists(): raise FileExistsError(f"refusing to overwrite existing evidence: {p}")
    raw = response.get("text")
    if not isinstance(raw, str): raise ValueError("response.text must preserve Luna raw answer text")
    raw_dir.mkdir(parents=True, exist_ok=True); (raw_dir / f"{artifact_key}.txt").write_text(raw, encoding="utf-8")
    try:
        plan = _extract_plan(raw)
    except (ValueError, TypeError) as exc:
        # A submitted first draft is terminal even when malformed or blocked.
        # Preserve it; never silently retry or let an empty plan disappear.
        status = response.get("status")
        if status not in {"blocked", "error", "timeout"}:
            status = "malformed"
        result = {"uid": uid, "attempt": attempt, "arm": "implementation_b",
                  "request_protocol": request.get("protocol"),
                  "producer": response.get("producer"), "agent_id": response.get("agent_id"),
                  "status": status, "raw_path": str((raw_dir / f"{artifact_key}.txt").relative_to(OUT)),
                  "native_plan_path": None, "parse_error": f"{type(exc).__name__}: {exc}",
                  "query_source_for_independent_evaluation": request["query_source"],
                  "official_evaluation": "pending root unified evaluator", "auto_repair": False,
                  "live_api_calls": 0, "tool_calls": response.get("tool_calls") or []}
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / f"{artifact_key}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return result
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / f"{artifact_key}.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tool_args_paths = []
    event_ref = response.get("tool_calls")
    if isinstance(event_ref, str):
        event_path = OUT / event_ref
        if event_path.exists():
            events = json.loads(event_path.read_text(encoding="utf-8"))
            args_dir = OUT / "tool_args" / artifact_key
            args_dir.mkdir(parents=True, exist_ok=True)
            for i, event in enumerate(events):
                if not isinstance(event, dict) or not isinstance(event.get("arguments"), dict): continue
                name = str(event.get("tool", "tool")); arg_path = args_dir / f"{i:03d}_{name}.json"
                arg_path.write_text(json.dumps(event["arguments"], ensure_ascii=True, indent=2, allow_nan=False) + "\n", encoding="ascii")
                tool_args_paths.append(str(arg_path.relative_to(OUT)))
    result = {"uid": uid, "attempt": attempt, "arm": "implementation_b", "request_protocol": request.get("protocol"),
              "producer": response.get("producer"),
              "agent_id": response.get("agent_id"), "raw_path": str((raw_dir / f"{artifact_key}.txt").relative_to(OUT)),
              "native_plan_path": str((plan_dir / f"{artifact_key}.json").relative_to(OUT)),
              "query_source_for_independent_evaluation": request["query_source"],
              "official_evaluation": "pending root unified evaluator", "auto_repair": False,
              "live_api_calls": 0, "tool_calls": event_ref or [], "ascii_tool_args_paths": tool_args_paths}
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / f"{artifact_key}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare"); prep.add_argument("--split", choices=["easy", "medium", "human"], required=True); prep.add_argument("--uid", required=True); prep.add_argument("--request-id")
    sub.add_parser("prepare-all")
    shard = sub.add_parser("prepare-shard"); shard.add_argument("--remainder", type=int, default=0); shard.add_argument("--modulus", type=int, default=2); shard.add_argument("--splits", nargs="+", choices=["easy", "medium", "human"], default=["easy", "medium", "human"])
    ing = sub.add_parser("ingest"); ing.add_argument("response", type=Path)
    tool = sub.add_parser("tool"); tool.add_argument("name", choices=sorted(TOOLS)); tool.add_argument("--args-file", type=Path)
    args = p.parse_args()
    if args.command == "prepare": print(prepare(args.split, args.uid, args.request_id))
    elif args.command == "prepare-all": print(json.dumps(prepare_all(), ensure_ascii=False, indent=2))
    elif args.command == "prepare-shard": print(json.dumps(prepare_shard(args.remainder, args.modulus, tuple(args.splits)), ensure_ascii=False, indent=2))
    elif args.command == "ingest": print(json.dumps(ingest(args.response), ensure_ascii=False, indent=2))
    else:
        call = json.loads(args.args_file.read_text(encoding="utf-8")) if args.args_file else json.loads(sys.stdin.buffer.read().decode("utf-8"))
        print(json.dumps(TOOLS[args.name](**call), ensure_ascii=False, allow_nan=False))


if __name__ == "__main__": main()
