"""Rule-planner control on the exact frozen 1/10 native sample.

P34 ConstraintPlannerV2 already ran every native query (easy 300 / medium 150 /
human 154), so the control group is a filter over those rows — no re-planning
and no LLM tokens. This keeps the control on the SAME 60 UIDs as G1/G2.

Usage:
  .venv/Scripts/python.exe -B -X utf8 scripts/p35_rule_baseline_1of10.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = Path(os.environ.get("SHORTTRIP_RUNS", ROOT.parent / "shorttrip-runs"))
SAMPLES = RUNS / "frozen_samples_1of10.json"
P34 = ROOT / "results/p34_v2_planner"
OUT = RUNS / "RULE_BASELINE_G1_1of10.json"
SPLITS = ("easy", "medium", "human")


def main() -> int:
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))["native_uids"]
    report = {
        "description": "P34 ConstraintPlannerV2 (pure rule, 0 LLM tokens) filtered to "
                       "the frozen 1/10 native UIDs shared by G1/G2",
        "source": "results/p34_v2_planner/<split>_ShortTripV2_<split>.json",
        "by_split": {},
        "total": {"sample": 0, "found": 0,
                  "passes": {"schema_ok": 0, "commonsense_ok": 0, "hard_ok": 0, "all_ok": 0}},
        "per_uid": {},
    }
    for split in SPLITS:
        rows = json.loads((P34 / f"{split}_ShortTripV2_{split}.json")
                          .read_text(encoding="utf-8"))["rows"]
        by_uid = {r["uid"]: r for r in rows}
        wanted = samples[split]
        found = [r for r in (by_uid.get(u) for u in wanted) if r]
        counts = {k: sum(1 for r in found if r.get(k)) for k in
                  ("schema_ok", "commonsense_ok", "hard_ok", "all_ok")}
        report["by_split"][split] = {"sample": len(wanted), "found_in_p34": len(found),
                                     "passes": counts}
        for r in found:
            report["per_uid"][r["uid"]] = {k: bool(r.get(k)) for k in
                                           ("schema_ok", "commonsense_ok", "hard_ok", "all_ok")}
        report["total"]["sample"] += len(wanted)
        report["total"]["found"] += len(found)
        for k, v in counts.items():
            report["total"]["passes"][k] += v
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for split in SPLITS:
        b = report["by_split"][split]
        print(f"{split:7s} {b['passes']['all_ok']:2d}/{b['sample']:2d} all_ok "
              f"(schema {b['passes']['schema_ok']}, commonsense {b['passes']['commonsense_ok']}, "
              f"hard {b['passes']['hard_ok']})")
    t = report["total"]
    print(f"TOTAL   {t['passes']['all_ok']}/{t['sample']} all_ok -> "
          f"{100 * t['passes']['all_ok'] / max(t['sample'], 1):.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
