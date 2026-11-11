"""P32 validation: coverage, JSON validity, evidence coverage, gate reproducibility."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from p31_common import read_json, write_json
from p31_static import missing_fields

ROOT = Path(__file__).resolve().parents[1]
P31 = ROOT / "results/p31_five_city_96"
P32 = ROOT / "results/p32_llm_96"


def main():
    errors, warnings = [], []
    tasks = read_json(P31 / "tasks/all_96.json")
    uids = [t["uid"] for t in tasks]
    if len(tasks) != 96 or len(set(uids)) != 96:
        errors.append("task_set")

    static_files = sorted((P32 / "out").glob("*_static.json"))
    final_files = sorted((P32 / "out").glob("*_final.json"))
    if len(static_files) != 96:
        errors.append(f"static_count:{len(static_files)}")
    if len(final_files) != 96:
        errors.append(f"final_count:{len(final_files)}")

    static = {}
    for f in static_files:
        try:
            d = read_json(f)
        except Exception as exc:
            errors.append(f"static_json:{f.name}:{type(exc).__name__}")
            continue
        static[d["uid"]] = d
    final = {}
    for f in final_files:
        try:
            d = read_json(f)
        except Exception as exc:
            errors.append(f"final_json:{f.name}:{type(exc).__name__}")
            continue
        final[d["uid"]] = d
    if set(static) != set(uids):
        errors.append(f"static_uid_set:{len(set(static))}")
    if set(final) != set(uids):
        errors.append(f"final_uid_set:{len(set(final))}")

    # order / lunch schema
    bad_order, bad_lunch, bad_status = [], [], []
    statuses = Counter()
    for uid, d in final.items():
        statuses[d.get("status")] += 1
        if d.get("status") not in ("complete", "blocked", "infeasible", "partial"):
            bad_status.append(uid)
        if not isinstance(d.get("order"), list):
            bad_order.append(uid)
        if d.get("order") and any(not isinstance(x, str) for x in d["order"]):
            bad_order.append(uid)
    if bad_order:
        errors.append(f"bad_order:{bad_order}")
    if bad_status:
        errors.append(f"bad_status:{bad_status}")

    # evidence packs: every requested leg has a route
    pack_missing = []
    for uid in uids:
        pack = read_json(P32 / "packs" / f"{uid}_final.json")
        ev = pack["evidence"]
        have = {(r["from"], r["to"]) for r in ev["routes"]}
        for lg in ev.get("legs_requested") or []:
            if (lg["from"], lg["to"]) not in have:
                pack_missing.append((uid, lg["from"], lg["to"]))
    if pack_missing:
        errors.append(f"legs_without_evidence:{len(pack_missing)}")

    # supplementary retrieval
    p32_resp = list((P32 / "retrieval/responses").rglob("*.json")) if (P32 / "retrieval/responses").exists() else []
    ledger = read_json(P32 / "retrieval/ledger.json") if (P32 / "retrieval/ledger.json").exists() else {}
    bad_infocode = []
    for f in p32_resp:
        d = read_json(f)
        if str(d.get("infocode")) != "10000":
            bad_infocode.append(f.name)
    if bad_infocode:
        errors.append(f"p32_non_10000:{len(bad_infocode)}")
    if ledger.get("stopped"):
        warnings.append(f"ledger_stopped:{ledger.get('stop_reason')}")

    # gate reproducibility: rerun the scorer's gate on the saved orders
    from p32_score import load_details, load_responses, synth_plan, split_order
    from p31_finalize import build_final
    responses = load_responses()
    for f in (P32 / "retrieval/responses").rglob("*.json"):
        d = read_json(f)
        responses[(d["uid"], d["req_id"])] = d
    details = load_details()
    tmap = {t["uid"]: t for t in tasks}
    gates = {}
    for uid, d in final.items():
        t = tmap[uid]
        order, _, ok = split_order(t, d.get("order"))
        if not ok:
            gates[uid] = "invalid_order"
            continue
        gates[uid] = build_final(t, synth_plan(t, order, d.get("lunch_after")), responses, details)["status"]
    scored = {p.stem: read_json(p) for p in (P32 / "scored").glob("*.json")}
    mism = [u for u in uids if scored.get(u, {}).get("final", {}).get("gate_status") != gates.get(u)]
    if mism:
        errors.append(f"gate_recompute_mismatch:{mism}")

    summary = {
        "tasks": len(tasks),
        "static_outputs": len(static),
        "final_outputs": len(final),
        "final_status": dict(statuses),
        "packs": {"static": len(list((P32 / 'packs').glob('*_static.json'))),
                  "final": len(list((P32 / 'packs').glob('*_final.json')))},
        "supplementary_route_calls": len(p32_resp),
        "supplementary_ledger_spent": ledger.get("spent"),
        "supplementary_stopped": ledger.get("stopped"),
        "legs_without_evidence": len(pack_missing),
        "gate_recompute_mismatch": mism,
        "rule_status": dict(Counter(f["status"] for f in read_json(P31 / "final/plans_all_96.json"))),
        "required_gaps": sum(len(missing_fields(t)) for t in tasks),
        "errors": errors, "warnings": warnings,
    }
    write_json(P32 / "validation.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
