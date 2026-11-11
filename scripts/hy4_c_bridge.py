"""Arm C bridge: eleven-city test set + extended catalog, LLM-written plans.

Read-only tools only. The bridge never selects, orders, schedules, or repairs
an itinerary; the hy4std subagent must write the plan itself. It supports both
the 60 native-schema xian11 questions and the 30 shorttrip-dynamic-v1 chain
questions, which are scored separately.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "ChinaTravel"), str(ROOT / "scripts")]

# Quality-tiered access: L1-complete rows are the planner path, L2-complete
# rows are preferred. See scripts/xian11_tier.py and TIER_INDEX.json.
from xian11_tier import TIER_ORDER, tier_by_name  # noqa: E402

@lru_cache(maxsize=1)
def _tier_lookup() -> dict:
    return tier_by_name()


def _annotate_and_sort(rows: list[dict], kind: str) -> list[dict]:
    lookup = _tier_lookup().get(kind, {})
    for r in rows:
        info = lookup.get(r.get("name", ""))
        if info:
            r["quality_tier"] = info["tier"]
            r["l1_gaps"] = info["l1_gaps"]
            r["l2_gaps"] = info["l2_gaps"]
            if info["tier"] == "reference_only":
                r["planning_note"] = "L1 incomplete: queryable only, do NOT put in an itinerary"
            elif info["tier"] == "l1_only":
                r["planning_note"] = "L2 gaps: price/duration judgements are not trustworthy"
        else:
            # transport / POI / metro are not covered by quality_model.json;
            # they are structurally complete, so keep them in the preferred band.
            r["quality_tier"] = "not_classified"
    order = {**TIER_ORDER, "not_classified": 0}
    return sorted(rows, key=lambda r: order.get(r.get("quality_tier"), 9))
CATALOG = ROOT / "data" / "catalog_v1_1_20261022" / "catalog.sqlite3"
XIAN_SANDBOX = ROOT / "data" / "xian11_sandbox"
QUERIES = ROOT / "query_sets" / "xian11"
DEFAULT_RUN_DIR = "results/hy4_threearm_20261108"
DEFAULT_MODEL = "hy4std"
OUT = ROOT / DEFAULT_RUN_DIR / "implementation_c"
MODEL = DEFAULT_MODEL
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

KINDS = {"attraction", "restaurant", "accommodation", "poi", "metro_station", "train", "flight"}
PLAN_PROMPT = """You are the planner for arm C (eleven-city extended data architecture).
The eleventh city 西安 is served by a freshly exported sandbox; the original ten
cities are served by the frozen extended catalog. All tool results are frozen
benchmark/reference data, NOT current real-world confirmations.

You must personally choose every entity, activity order, start/end time, local
transport mode, intercity service, hotel, meal and cost-bearing choice. Use only
entities you actually inspected through the read-only tools. Never delegate to
a rule planner, scheduler or repair helper. Do not use hidden hard_logic_py,
oracle fields, or checker feedback. Your first complete plan is final.

For split in (easy, medium, human): return exactly one JSON object with keys
people_number, start_city, target_city, itinerary (list of {day, activities}).
Each activity has type/start_time/end_time/position/cost/price/tickets fields
as in the official ChinaTravel plan shape.

For split == chain: the query uses shorttrip-dynamic-v1 with city_sequence.
Return one JSON object with keys schema_version, uid, city_sequence, plan
(per-city itinerary), and limitations. Do not fabricate a train/flight that is
not backed by an intercity_search result. If a connection has no evidence, keep
it as an explicit pending connection in limitations instead of inventing one.

Read-only tools: catalog_list(kind, city, limit, offset), catalog_search(kind,
city, text, limit, offset), catalog_entity(record_id), catalog_tags(record_id),
catalog_claims(record_id, field), intercity_search(from_city, to_city, mode),
goto(city, start, end, mode, departure). Tools return data only, never a plan.
"""


def _db():
    db = sqlite3.connect(f"file:{CATALOG.as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def _xian_files(kind: str) -> list[Path]:
    base = XIAN_SANDBOX
    table = {
        "attraction": [base / "attractions" / "xian" / "attractions.csv"],
        "restaurant": [base / "restaurants" / "xian" / "restaurants_xian.csv"],
        "accommodation": [base / "accommodations" / "xian" / "accommodations.csv"],
        "poi": [base / "poi" / "xian" / "poi.json"],
        "metro_station": [base / "subway_stations" / "xian" / "subway_stations.json"],
        "train": sorted((base / "intercity_transport" / "train").glob("from_*_to_*.json")),
        "flight": [base / "intercity_transport" / "airplane.jsonl"],
    }
    return [p for p in table.get(kind, []) if p.exists()]


def _xian_rows(kind: str) -> list[dict]:
    rows: list[dict] = []
    for path in _xian_files(kind):
        if path.suffix == ".csv":
            with path.open(encoding="utf-8") as handle:
                for i, row in enumerate(csv.DictReader(handle)):
                    rows.append({"record_id": f"xian:{kind}:{i}", "kind": kind, "city": "西安",
                                 "name": row.get("name") or row.get("Name") or "", "data": row,
                                 "source": "data/xian11_sandbox (exported from xian snapshot_v4)",
                                 "evidence_status": "locally_verifiable"})
        elif path.suffix == ".jsonl":
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
                if line.strip():
                    rows.append({"record_id": f"xian:{kind}:{i}", "kind": kind, "city": "西安",
                                 "name": json.loads(line).get("FlightID", ""), "data": json.loads(line),
                                 "source": "data/xian11_sandbox", "evidence_status": "locally_verifiable"})
        elif path.suffix == ".json":
            value = json.loads(path.read_text(encoding="utf-8"))
            items = value if isinstance(value, list) else list(value.values())
            for i, item in enumerate(items):
                if isinstance(item, dict):
                    rows.append({"record_id": f"xian:{kind}:{i}", "kind": kind, "city": "西安",
                                 "name": item.get("name") or item.get("TrainID") or "", "data": item,
                                 "source": "data/xian11_sandbox", "evidence_status": "locally_verifiable"})
    return _annotate_and_sort(rows, kind)


def _rows(kind: str, city: str) -> list[dict]:
    if city == "西安":
        return _xian_rows(kind)
    rows: list[dict] = []
    with _db() as db:
        for row in db.execute(
                "SELECT id,kind,city,name,payload FROM records WHERE lang='zh' AND kind=? AND city=? ORDER BY id",
                (kind, city)).fetchall():
            payload = json.loads(row["payload"])
            rows.append({"record_id": row["id"], "kind": kind, "city": city, "name": row["name"],
                         "data": payload.get("data") or {},
                         "source": "data/catalog_v1_1_20261022",
                         "evidence_status": payload.get("trust_status", "unknown")})
    return rows


def _tier_filter(rows: list[dict], tier: str | None) -> list[dict]:
    if not tier:
        return rows
    if tier not in TIER_ORDER:
        raise ValueError(f"tier must be one of {sorted(TIER_ORDER)}")
    return [r for r in rows if r.get("quality_tier") == tier]


def _tier_counts(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("quality_tier", "unknown")] = counts.get(r.get("quality_tier", "unknown"), 0) + 1
    return counts


def catalog_list(kind: str, city: str, limit: int = 20, offset: int = 0,
                 tier: str | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind}")
    rows = _rows(kind, city)
    counts = _tier_counts(rows)
    rows = _tier_filter(rows, tier)
    return {"kind": kind, "city": city, "total": len(rows), "returned": len(rows[offset:offset + limit]),
            "records": rows[offset:offset + limit], "tier_filter": tier, "tier_counts": counts,
            "ordering": "ready / not_classified first, then l1_only, then reference_only",
            "real_world_availability": False}


def catalog_search(kind: str, city: str, text: str, limit: int = 20, offset: int = 0,
                   tier: str | None = None) -> dict:
    rows = [r for r in _rows(kind, city) if text in str(r["name"]) or text in json.dumps(r["data"], ensure_ascii=False)]
    counts = _tier_counts(rows)
    rows = _tier_filter(rows, tier)
    return {"kind": kind, "city": city, "text": text, "total": len(rows),
            "returned": len(rows[offset:offset + limit]), "records": rows[offset:offset + limit],
            "tier_filter": tier, "tier_counts": counts, "real_world_availability": False}


def catalog_entity(record_id: str) -> dict:
    for kind in KINDS:
        for city in ("西安", "北京", "上海", "杭州", "成都", "广州", "深圳", "南京", "武汉", "苏州", "重庆"):
            for row in _rows(kind, city):
                if str(row["record_id"]) == str(record_id):
                    return {"found": True, "record": row, "real_world_availability": False}
    return {"found": False, "record_id": record_id, "real_world_availability": False}


def catalog_tags(record_id: str) -> dict:
    return {"record_id": record_id, "tags": [], "available": False,
            "reason": "TagStore v2 covers the ten original cities only; no TAG rows for 西安",
            "real_world_availability": False}


def catalog_claims(record_id: str, field: str | None = None) -> dict:
    return {"record_id": record_id, "field": field, "claims": [], "available": False,
            "reason": "claim sidecar not exported for the eleventh city",
            "real_world_availability": False}


def intercity_search(from_city: str, to_city: str, mode: str = "any") -> dict:
    modes = [mode] if mode in ("train", "airplane") else ["train", "airplane"]
    rows = []
    for m in modes:
        kind = "train" if m == "train" else "flight"
        for city in ("西安", "北京", "上海", "杭州", "成都", "广州", "深圳", "南京", "武汉", "苏州", "重庆"):
            for row in _rows(kind, city):
                d = row["data"]
                if from_city in str(d.get("From", "")) and to_city in str(d.get("To", "")):
                    rows.append({"mode": m, "record": row})
    return {"from_city": from_city, "to_city": to_city, "records": rows[:50], "returned": len(rows),
            "source": "extended catalog + xian11_sandbox", "real_world_availability": False}


def goto(city: str, start: str, end: str, mode: str, departure: str) -> dict:
    if city == "西安":
        return {"city": city, "start": start, "end": end, "mode": mode, "departure": departure,
                "available": False, "legs": [],
                "error": "no official Transportation rows for the eleventh city; do not invent a leg",
                "source": "xian11_sandbox has no inner-city transport table",
                "real_world_route_proof": False}
    from chinatravel.environment.tools.transportation.apis import Transportation
    try:
        result = Transportation(lang="zh").goto(city, start, end, departure, mode)
        error = None
    except Exception as exc:  # noqa: BLE001
        result, error = None, f"{type(exc).__name__}: {exc}"
    return {"city": city, "start": start, "end": end, "mode": mode, "departure": departure,
            "available": bool(result), "legs": result or [], "error": error,
            "source": "official ChinaTravel Transportation.goto", "real_world_route_proof": False}


TOOLS = {name: obj for name, obj in list(globals().items())
         if name in {"catalog_list", "catalog_search", "catalog_entity", "catalog_tags",
                     "catalog_claims", "intercity_search", "goto"}}


def _load_query(split: str, uid: str) -> dict:
    path = QUERIES / split / f"{uid}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    query = json.loads(path.read_text(encoding="utf-8"))
    public = {k: v for k, v in query.items() if k not in {"hard_logic_py", "hard_logic_nl"}}
    return {"path": str(path.relative_to(ROOT)), "query": public, "split": split}


def prepare(split: str, uid: str, request_id: str | None = None) -> Path:
    q = _load_query(split, uid)
    rid = request_id or f"c_{split}_{uid}"
    path = OUT / "requests" / f"{rid}.json"
    user = (f"Arm C, split={split}, uid={uid}. Public query follows.\n"
            f"{json.dumps(q['query'], ensure_ascii=False, indent=2)}\n"
            "Use the read-only tools; the eleventh city 西安 is in data/xian11_sandbox.\n"
            "Return exactly one plan JSON object as specified in the system prompt.")
    request = {"arm": "implementation_c", "uid": uid, "split": split,
               "messages": [{"role": "system", "content": PLAN_PROMPT}, {"role": "user", "content": user}],
               "call_kwargs": {"model": MODEL, "reasoning_effort": "medium",
                               "tool_names": sorted(TOOLS), "tool_loop": True,
                               "checker_feedback_before_first_output": False},
               "public_query": q["query"], "query_source": q["path"],
               "protocol": "hy4-eleven-city-c-v1",
               "official_checker_compatible": split != "chain"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(request, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return path


def prepare_shard(remainder: int = 0, modulus: int = 2,
                  splits: tuple[str, ...] = ("easy", "medium", "human", "chain")) -> dict:
    counts, errors, made_total = {}, [], 0
    for split in splits:
        ids = sorted(p.stem for p in (QUERIES / split).glob("*.json"))
        selected = [uid for i, uid in enumerate(ids) if i % modulus == remainder]
        made = 0
        for uid in selected:
            rid = f"c_{split}_{uid}"
            target = OUT / "requests" / f"{rid}.json"
            if target.exists():
                continue
            try:
                prepare(split, uid, rid)
                made += 1
            except Exception as exc:  # noqa: BLE001
                errors.append({"uid": uid, "error": f"{type(exc).__name__}: {exc}"})
        counts[split] = {"split_tasks": len(ids), "shard_tasks": len(selected), "new_requests": made}
        made_total += made
    return {"remainder": remainder, "modulus": modulus, "counts": counts, "errors": errors,
            "new_requests": made_total, "out": str(OUT / "requests")}


def _extract_plan(text: str, split: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    val = json.loads(raw)
    if not isinstance(val, dict):
        raise ValueError("response must be one JSON object")
    if split == "chain":
        if not isinstance(val.get("city_sequence"), list) or not val["city_sequence"]:
            raise ValueError("dynamic plan needs a nonempty city_sequence")
        if "plan" not in val:
            raise ValueError("dynamic plan needs a plan object")
    else:
        if not isinstance(val.get("itinerary"), list) or not val["itinerary"]:
            raise ValueError("native plan needs a nonempty itinerary")
    return val


def ingest(response_path: Path) -> dict:
    response = json.loads(response_path.read_text(encoding="utf-8"))
    uid, rid = response["uid"], response_path.stem
    request_path = OUT / "requests" / f"{rid}.json"
    if not request_path.exists():
        raise FileNotFoundError(f"matching request missing: {request_path}")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if request["uid"] != uid:
        raise ValueError("response UID does not match request")
    split = request["split"]
    raw_dir, plan_dir, eval_dir = OUT / "raw", OUT / "nativeplans", OUT / "evaluations"
    for p in (raw_dir / f"{uid}.txt", plan_dir / f"{uid}.json", eval_dir / f"{uid}.json"):
        if p.exists():
            raise FileExistsError(f"refusing to overwrite submitted evidence: {p}")
    raw = response.get("text")
    if not isinstance(raw, str):
        raise ValueError("response.text must preserve the raw answer")
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{uid}.txt").write_text(raw, encoding="utf-8")
    base = {"uid": uid, "split": split, "arm": "implementation_c",
            "request_protocol": request.get("protocol"), "producer": response.get("producer"),
            "agent_id": response.get("agent_id"), "model": response.get("model"),
            "raw_path": str((raw_dir / f"{uid}.txt").relative_to(OUT)),
            "query_source_for_independent_evaluation": request["query_source"],
            "official_checker_compatible": split != "chain",
            "official_evaluation": "pending unified evaluator", "auto_repair": False,
            "live_api_calls": 0, "tool_calls": response.get("tool_calls") or []}
    try:
        plan = _extract_plan(raw, split)
    except (ValueError, TypeError) as exc:
        result = {**base, "status": response.get("status") or "malformed",
                  "native_plan_path": None, "parse_error": f"{type(exc).__name__}: {exc}"}
    else:
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / f"{uid}.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                                              encoding="utf-8")
        result = {**base, "status": "ok",
                  "native_plan_path": str((plan_dir / f"{uid}.json").relative_to(OUT))}
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / f"{uid}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    return result


def main() -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--run-dir", default=DEFAULT_RUN_DIR)
    common.add_argument("--model", default=DEFAULT_MODEL)
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", parents=[common])
    prep.add_argument("--split", choices=["easy", "medium", "human", "chain"], required=True)
    prep.add_argument("--uid", required=True)
    shard = sub.add_parser("prepare-shard", parents=[common])
    shard.add_argument("--remainder", type=int, default=0)
    shard.add_argument("--modulus", type=int, default=2)
    shard.add_argument("--splits", nargs="+", choices=["easy", "medium", "human", "chain"],
                       default=["easy", "medium", "human", "chain"])
    ing = sub.add_parser("ingest", parents=[common])
    ing.add_argument("response", type=Path)
    tool = sub.add_parser("tool", parents=[common])
    tool.add_argument("name", choices=sorted(TOOLS))
    tool.add_argument("--args-file", type=Path)
    args = p.parse_args()
    global OUT, MODEL
    OUT = ROOT / args.run_dir / "implementation_c"
    MODEL = args.model
    if args.command == "prepare":
        print(prepare(args.split, args.uid))
    elif args.command == "prepare-shard":
        print(json.dumps(prepare_shard(args.remainder, args.modulus, tuple(args.splits)),
                         ensure_ascii=False, indent=2))
    elif args.command == "ingest":
        print(json.dumps(ingest(args.response), ensure_ascii=False, indent=2))
    else:
        call = (json.loads(args.args_file.read_text(encoding="utf-8")) if args.args_file
                else json.loads(sys.stdin.buffer.read().decode("utf-8")))
        print(json.dumps(TOOLS[args.name](**call), ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
