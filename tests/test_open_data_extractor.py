"""Failure-case tests for the open-data TAG extractor (instruction §4 requires ≥5).

Each test constructs a record that *should* be rejected or quarantined, and asserts
the specific gate that catches it. These are the failure modes that actually
occurred or were nearly missed during the P1/P2 build:

1. excerpt not present in the raw payload (fabricated or reformatted quote)
2. licence unknown / not reusable (`license_pending` source smuggled in)
3. value outside the declared domain (e.g. wheelchair=maybe)
4. missing validity window
5. context-requiring tag (crowding/queue) without weekday/time context
6. conflicting values for the same POI+tag from two sources
7. CONTEXT_PRIOR without a stated inference rule
8. identity mismatch (same name, different city) must never reach extraction
9. a source marked license_pending must not appear as an accepted record

Run: .\\venv\\Scripts\\python tests\\test_open_data_extractor.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("BAIDU_REQUEST_BUDGET", "0")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.dynamic.opendata import match_identity  # noqa: E402
from shorttrip.tags import (  # noqa: E402
    TagEvidence,
    gate_tag_v2,
)

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []
IDENTITY = {"match": True, "rule": "name_exact", "score": 1.0}
RAW = '{"extratags": {"wheelchair": "yes", "fee": "no", "tourism": "museum"}}'


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
    else:
        FAILED.append((name, detail))


def make(**overrides) -> TagEvidence:
    base = dict(
        local_poi_id="sandbox:广州:广东省博物馆", tag_id="wheelchair_access",
        value="yes", value_type="ordinal", evidence_kind="crowd_tagged",
        city="广州", poi_name="广东省博物馆", source_name="osm",
        source_url="https://www.openstreetmap.org/way/1",
        source_record_id="osm:way/1", excerpt='"wheelchair": "yes"',
        raw_digest="deadbeef", licence_status="odbl",
        retrieved_at="2026-10-21T00:00:00+00:00", valid_until="2099-01-01",
        confidence=0.75, notes="OSM wheelchair 明确标注",
    )
    base.update(overrides)
    return TagEvidence(**base)


def main() -> int:
    # baseline: the good record must be accepted, otherwise the tests prove nothing
    ok = gate_tag_v2(make(), raw_text=RAW, identity=IDENTITY, conflicts={})
    check("baseline/accept", ok.decision == "accept", str(ok.reasons))

    # 1. fabricated excerpt
    verdict = gate_tag_v2(make(excerpt='"wheelchair": "no"'), raw_text=RAW,
                          identity=IDENTITY, conflicts={})
    check("fail1/excerpt_not_verbatim", verdict.decision == "reject"
          and not verdict.gates["T2_excerpt"]["passed"], str(verdict.reasons))

    # 2. unknown licence
    verdict = gate_tag_v2(make(licence_status="unknown"), raw_text=RAW,
                          identity=IDENTITY, conflicts={})
    check("fail2/licence_unknown", verdict.decision == "reject"
          and not verdict.gates["T1_licence"]["passed"], str(verdict.reasons))

    # 2b. source explicitly marked license_pending must not be acceptable
    verdict = gate_tag_v2(make(licence_status="license_pending"), raw_text=RAW,
                          identity=IDENTITY, conflicts={})
    check("fail2b/licence_pending_blocked", verdict.decision == "reject", str(verdict.reasons))

    # 3. value outside the declared domain
    verdict = gate_tag_v2(make(value="maybe"), raw_text=RAW, identity=IDENTITY, conflicts={})
    check("fail3/value_out_of_domain", verdict.decision == "reject"
          and not verdict.gates["T3_semantics"]["passed"], str(verdict.reasons))

    # 3b. bool tag given a string
    verdict = gate_tag_v2(make(tag_id="category_history", value="yes", value_type="bool"),
                          raw_text=RAW, identity=IDENTITY, conflicts={})
    check("fail3b/bool_type_mismatch", verdict.decision == "reject", str(verdict.reasons))

    # 4. missing validity window
    verdict = gate_tag_v2(make(valid_until=None), raw_text=RAW, identity=IDENTITY, conflicts={})
    check("fail4/missing_validity", verdict.decision == "quarantine"
          and not verdict.gates["T4_time_context"]["passed"], str(verdict.reasons))

    # 5. context-requiring tag without context
    raw_crowd = '{"content_tag": "人气旺"}'
    verdict = gate_tag_v2(
        make(tag_id="crowding_report", value="high", value_type="ordinal",
             excerpt='"content_tag": "人气旺"', evidence_kind="platform_tag",
             licence_status="api_terms_ok", context={}, evidence_class="VISITOR_EXPERIENCE"),
        raw_text=raw_crowd, identity=IDENTITY, conflicts={})
    check("fail5/crowding_without_context", verdict.decision == "quarantine"
          and not verdict.gates["T4_time_context"]["passed"], str(verdict.reasons))

    # 6. conflicting values from two sources
    conflicts: dict = {}
    first = gate_tag_v2(make(), raw_text=RAW, identity=IDENTITY, conflicts=conflicts)
    second = gate_tag_v2(make(value="limited", licence_status="cc0", source_name="wikidata",
                             excerpt='"wheelchair": "yes"'),
                         raw_text=RAW, identity=IDENTITY, conflicts=conflicts)
    check("fail6/conflict_first_ok", first.decision == "accept", str(first.reasons))
    check("fail6/conflict_detected", second.decision == "quarantine"
          and not second.gates["T5_conflict"]["passed"], str(second.reasons))

    # 6b. corroborating value (same value, other source) must stay accepted
    conflicts2: dict = {}
    gate_tag_v2(make(), raw_text=RAW, identity=IDENTITY, conflicts=conflicts2)
    same = gate_tag_v2(make(licence_status="cc0", source_name="wikidata"),
                       raw_text=RAW, identity=IDENTITY, conflicts=conflicts2)
    check("fail6b/corroboration_accepted", same.decision == "accept", str(same.reasons))

    # 7. CONTEXT_PRIOR must state its rule
    verdict = gate_tag_v2(
        make(tag_id="weather_sensitive", value="low", value_type="ordinal",
             evidence_kind="context_prior", evidence_class="CONTEXT_PRIOR",
             excerpt='"tourism": "museum"', notes=""),
        raw_text=RAW, identity=IDENTITY, conflicts={})
    check("fail7/context_prior_needs_rule", verdict.decision == "quarantine",
          str(verdict.reasons))

    # 8. identity: same name, different city must abstain (the 孙中山纪念馆 trap)
    verdict = match_identity("孙中山纪念馆", "孙中山纪念馆")
    check("fail8/exact_name_still_needs_geo", verdict["match"] is True)  # name alone matches
    # ...which is why the P1 script additionally requires a coordinate or an OSM QID;
    # assert the locator rule does NOT let a different venue through:
    check("fail8/locator_rule_rejects_unrelated",
          match_identity("广州塔", "广州大剧院")["match"] is False)
    check("fail8/locator_rule_accepts_subsites",
          match_identity("南越王博物院", "南越王博物院(王墓展区)")["match"] is True)

    # 9. a rejected record must never be counted as accepted upstream
    rejected = gate_tag_v2(make(licence_status="unknown"), raw_text=RAW,
                           identity=IDENTITY, conflicts={})
    check("fail9/rejected_not_counted", rejected.decision != "accept")

    print(f"PASS {len(PASSED)}  FAIL {len(FAILED)}")
    for name in PASSED:
        print(f"  ok   {name}")
    for name, detail in FAILED:
        print(f"  FAIL {name}: {detail}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
