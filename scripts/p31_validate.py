"""P31 validation: consistency checks over tasks, requests, responses and finals."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from p31_common import OUT, read_json, write_json

errors = []
warnings = []

tasks = read_json(OUT / "tasks/all_96.json")
if len(tasks) != 96:
    errors.append(f"task_count:{len(tasks)}")
if Counter(t["level"] for t in tasks) != {"easy": 32, "hard": 32, "human": 32}:
    errors.append("level_counts")
uids = [t["uid"] for t in tasks]
if len(set(uids)) != len(uids):
    errors.append("duplicate_uid")

plans = read_json(OUT / "static/plans_all_96.json")
plan_by = {p["uid"]: p for p in plans}
finals = read_json(OUT / "final/plans_all_96.json")
final_by = {f["uid"]: f for f in finals}
if set(plan_by) != set(uids) or set(final_by) != set(uids):
    errors.append("uid_set_mismatch")

requests = []
for p in plans:
    requests += [(p["uid"], r) for r in p["requests"]]
req_ids = {(u, r["req_id"]) for u, r in requests}
if len(req_ids) != len(requests):
    errors.append("duplicate_request_id")

responses = {}
for f in (OUT / "retrieval/responses").rglob("*.json"):
    d = read_json(f)
    responses[(d["uid"], d["req_id"])] = d
missing = req_ids - set(responses)
extra = set(responses) - req_ids
if missing:
    errors.append(f"missing_responses:{len(missing)}")
if extra:
    warnings.append(f"extra_responses:{len(extra)}")
bad_infocode = [k for k, d in responses.items() if str(d.get("infocode")) != "10000"]
if bad_infocode:
    errors.append(f"non_10000:{bad_infocode[:5]}")
bad_sha = [k for k, d in responses.items() if not d.get("raw_sha256")]
if bad_sha:
    errors.append(f"missing_sha:{len(bad_sha)}")

details = [read_json(f) for f in (OUT / "retrieval/details").rglob("*.json")]
if len(details) != 18:
    warnings.append(f"detail_count:{len(details)}")

# status consistency
for f in finals:
    c = f["checks"]
    if f["status"] == "complete" and (not c["opening_known"] or f["cost"]["unknown"] or not c["time_ok"]):
        errors.append(f"complete_with_gap:{f['uid']}")
    if f["status"] == "blocked" and not (c["opening_unknown"] or f["cost"]["unknown"]):
        errors.append(f"blocked_without_gap:{f['uid']}")
    if f["status"] == "infeasible" and c["time_ok"] and c["budget_ok"] and c["intercity_ok"] is not False:
        errors.append(f"infeasible_without_reason:{f['uid']}")

summary = {
    "tasks": len(tasks),
    "plans": len(plans),
    "finals": len(finals),
    "requests": len(requests),
    "responses": len(responses),
    "request_types": dict(Counter(r["type"] for _, r in requests)),
    "response_types": dict(Counter(d["type"] for d in responses.values())),
    "status": dict(Counter(f["status"] for f in finals)),
    "detail_calls": len(details),
    "detail_with_hours": sum(1 for d in details if d.get("hours_window")),
    "errors": errors,
    "warnings": warnings,
}
write_json(OUT / "validation.json", summary)
print(json.dumps(summary, ensure_ascii=False, indent=1))
