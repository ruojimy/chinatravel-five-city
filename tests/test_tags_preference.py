r"""Minimal test suite for the TAG / preference layer. No pytest needed.

Run:  .\.venv\Scripts\python tests\test_tags_preference.py
Exit code 0 = all pass. Offline only (BAIDU_OFFLINE=1 is forced).

Each test names the concrete regression it guards, because every one of them was a
real defect or a real API surprise during this phase.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("BAIDU_OFFLINE", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.dynamic import baidu as B  # noqa: E402
from shorttrip.dynamic.tagstore import TagStore  # noqa: E402
from shorttrip.preference import UserProfile  # noqa: E402
from shorttrip.rerank import RerankOptions, rank_plans, score_plan  # noqa: E402
from shorttrip.tags import (  # noqa: E402
    TAXONOMY,
    TagEvidence,
    extract_attribute_tags,
    extract_experience_tags,
    gate_tag,
    utility,
)

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
    else:
        FAILED.append((name, detail))


def test_sn_signature_matches_official_vector():
    """Regression: 9 wrong spellings all returned 211 before this was pinned."""
    result = B.self_test()
    check("sn/official_vector", result["ok"], result["got"])
    check("sn/default_algorithm", B.SIGN_ALGORITHMS[0] == "md5_urlenc")
    # signed string must be the whole `uri?query+sk`, URL-encoded once
    check("sn/whole_string_encoded", result["signed_string"].startswith("%2Fgeocoder%2Fv2%2F%3F"))


def test_sign_query_is_stable_and_order_sensitive():
    """Regression: signing a sorted query while sending insertion order -> 211."""
    params = {"query": "广州塔", "region": "广州", "output": "json"}
    first = B.canonical_query(params, "java")
    second = B.canonical_query(params, "java")
    check("query/deterministic", first == second, first)
    sorted_query = B.canonical_query(params, "java", sort=True)
    check("query/order_matters", first != sorted_query)
    check("query/utf8_percent", "%E5%B9%BF%E5%B7%9E%E5%A1%94" in first, first)


def test_coordinate_conversion_round_trip():
    """Regression: BD-09 vs GCJ-02 mixed up would put a POI ~1 km off."""
    lon, lat = 113.324533, 23.106283
    back_lon, back_lat = B.gcj02_to_bd09(*B.bd09_to_gcj02(lon, lat))
    check("coord/round_trip", abs(back_lon - lon) < 1e-6 and abs(back_lat - lat) < 1e-6,
          f"{back_lon},{back_lat}")


def test_identity_rules():
    """Regression: 上海博物馆东馆 was accepted as 上海农垦博物馆 (ratio 0.714)."""
    check("identity/avoids_wrong_museum",
          not B.identity_check("上海博物馆东馆", "上海农垦博物馆")["match"])
    check("identity/avoids_road", not B.identity_check("广州塔", "广州塔路")["match"])
    check("identity/exact", B.identity_check("广州塔", "广州塔")["rule"] == "name_exact")
    sub = B.identity_check("南越王博物院", "南越王博物院(王墓展区)")
    check("identity/sub_site", sub["match"] and sub["rule"] == "sub_site_of_exact_parent", str(sub))
    check("identity/noise", not B.identity_check("ShortTrip 不存在的博物馆", "So Sorry")["match"])
    geo = B.identity_check("某博物馆", "某博物馆东馆", anchor=(23.10, 113.32), poi_xy=(23.101, 113.321))
    check("identity/geo_confirmation", geo["match"], str(geo))


def test_comment_num_is_bucketed_not_trusted():
    """Regression: 广州塔 and 故宫 both report exactly 200 -> a capped value."""
    check("bucket/capped", "capped" in (B.comment_bucket(200) or ""))
    check("bucket/ordinal", B.comment_bucket(55) == "50-199")
    check("bucket/unknown", B.comment_bucket(None) is None)


def test_replay_client_spends_no_quota():
    client = B.get_client("auto")
    check("replay/mode", getattr(client, "mode", "live") == "replay")
    payload = client.search("广州塔", "广州")
    check("replay/search_hit", str(payload.get("status")) == "0")
    budget = client.budget_report()
    check("replay/zero_live_calls", budget["live_calls"] == 0, str(budget))
    missing = client.search("武侯祠", "成都")
    check("replay/miss_is_explicit", str(missing.get("status")) != "0")


def test_attribute_tags_are_anchored():
    """Regression: a Python list repr as `excerpt` failed T3 (4 records rejected)."""
    raw = ('{"detail_info": {"classified_poi_tag": "旅游景点;4A景区", "price": "230.0",'
           ' "overall_rating": "4.6", "shop_hours": "09:30-22:30", "comment_num": "200"}}')
    flat = {"uid": "u1", "price": 230.0, "price_text": "230.0", "overall_rating": 4.6,
            "open_time": "09:30", "close_time": "22:30", "tag_path": ["旅游景点"],
            "classified_tag_path": ["旅游景点", "4A景区"], "comment_num": 200,
            "comment_bucket": ">=200(capped)"}
    records = extract_attribute_tags(flat, city="广州", poi_name="广州塔", raw_text=raw)
    check("tags/attributes_extracted", len(records) >= 4, str(len(records)))
    unanchored = [r.tag_id for r in records if r.excerpt and r.excerpt not in raw]
    check("tags/all_excerpts_verbatim", not unanchored, str(unanchored))
    identity = {"match": True, "rule": "name_exact", "score": 1.58}
    verdicts = [gate_tag(r, raw_text=raw, identity=identity) for r in records]
    check("tags/gates_accept_attributes", all(v.decision == "accept" for v in verdicts),
          str([v.reasons for v in verdicts if v.decision != "accept"]))


def test_experience_tag_extraction_and_gate():
    raw = '{"detail_info": {"content_tag": "适合亲子;适合拍照;人气旺;完全不存在的短语"}}'
    flat = {"uid": "u1", "content_tags": ["适合亲子", "适合拍照", "人气旺", "完全不存在的短语"]}
    records, report = extract_experience_tags(flat, city="北京", poi_name="故宫博物院", raw_text=raw)
    ids = {r.tag_id for r in records}
    check("tags/experience_mapped", {"child_friendly", "photography", "crowding"} <= ids, str(ids))
    check("tags/unmapped_reported", "完全不存在的短语" in report["unmapped_phrases"])
    check("tags/coverage_fraction", 0.0 < report["coverage_rate"] < 1.0, str(report["coverage_rate"]))
    identity = {"match": True, "rule": "name_exact", "score": 1.5}
    crowding = next(r for r in records if r.tag_id == "crowding")
    verdict = gate_tag(crowding, raw_text=raw, identity=identity)
    check("tags/context_required_quarantines", verdict.decision == "quarantine", str(verdict.reasons))


def test_t6_corroboration_vs_conflict():
    """Regression: two phrases asserting the same value were quarantined as duplicates."""
    raw = '{"content_tag": "适合拍照;拍照圣地"}'
    flat = {"uid": "u1", "content_tags": ["适合拍照", "拍照圣地"]}
    records, _ = extract_experience_tags(flat, city="北京", poi_name="X", raw_text=raw)
    identity = {"match": True, "rule": "name_exact", "score": 1.0}
    seen: dict = {}
    verdicts = [gate_tag(r, raw_text=raw, identity=identity, seen=seen) for r in records]
    check("tags/corroboration_accepts", all(v.decision == "accept" for v in verdicts),
          str([v.reasons for v in verdicts]))
    conflicting = TagEvidence(local_poi_id="sandbox:北京:X", tag_id="photography", value=False,
                              value_type="bool", evidence_kind="platform_tag",
                              source_name="baidu", excerpt="适合拍照", licence_status="api_terms_ok",
                              retrieved_at="2026-10-21T00:00:00+00:00", confidence=0.5)
    verdict = gate_tag(conflicting, raw_text=raw, identity=identity, seen=seen)
    check("tags/conflict_quarantines", verdict.decision == "quarantine", str(verdict.reasons))


def test_utility_direction():
    check("utility/benefit", utility("history_culture", True) == 1.0)
    check("utility/burden_inverted", utility("crowding", "high") == round(1 - 0.8, 4))
    check("utility/unknown_is_none", utility("crowding", None) is None)
    check("utility/neutral_not_scored", utility("entry_price", 230.0) is None)


def test_preference_profile():
    profile = UserProfile.from_query({
        "uid": "u1", "people_number": 3,
        "nature_language": "带小孩和老人去北京，喜欢历史，不要太累，预算有限",
    })
    check("pref/cue_children", profile.with_children is True)
    check("pref/cue_elders", profile.with_elders is True)
    check("pref/cue_interest", profile.interests.get("history_culture") == 1.0, str(profile.interests))
    check("pref/cue_price", profile.price_sensitivity == 0.8, str(profile.price_sensitivity))
    sources = {item.key: item.source for item in profile.items}
    check("pref/provenance_recorded", sources.get("with_children") == "dialogue_inferred", str(sources))
    check("pref/neutral_priors_listed", bool(profile.neutral_priors))
    check("pref/questions_capped", len(profile.high_gain_questions()) <= 3)
    profile.correct("with_children", False, note="用户更正")
    check("pref/correction_wins", profile.with_children is False)


def test_reranker_reports_uncertainty():
    plan = {"target_city": "广州", "itinerary": [{"day": 1, "activities": [
        {"type": "attraction", "position": "广州塔", "start_time": "10:00", "end_time": "11:30",
         "price": 149.0, "transports": [{"start_time": "09:40", "end_time": "10:00", "cost": 2}]},
        {"type": "attraction", "position": "陈家祠", "start_time": "13:00", "end_time": "14:00",
         "price": 10.0, "transports": [{"start_time": "12:40", "end_time": "13:00", "cost": 2}]},
    ]}]}
    profile = UserProfile.from_spec({"uid": "p", "interests": {"history_culture": 1.0}})
    empty = score_plan(plan, profile, {}, city="广州")
    check("rerank/unknown_is_neutral", empty["components"]["match"] == 0.5, str(empty["components"]))
    check("rerank/coverage_zero", empty["coverage"]["rate"] == 0.0)
    check("rerank/uncertainty_high", empty["uncertainty"] == 1.0)
    tagged = {"sandbox:广州:广州塔": {"history_culture": {"value": True, "confidence": 0.9}},
              "sandbox:广州:陈家祠": {"history_culture": {"value": True, "confidence": 0.9}}}
    full = score_plan(plan, profile, tagged, city="广州")
    check("rerank/tagged_raises_match", full["components"]["match"] > 0.9, str(full["components"]))
    check("rerank/coverage_complete", full["coverage"]["rate"] == 1.0)
    ranked = rank_plans([plan, plan], profile, tagged, city="广州")
    check("rerank/ranks_all", len(ranked) == 2 and ranked[0]["rank"] == 1)


def test_reranker_invariants():
    """Q must never claim to be a feasibility or correctness score."""
    plan = {"target_city": "广州", "itinerary": [{"day": 1, "activities": []}]}
    profile = UserProfile.from_spec({"uid": "p"})
    scored = score_plan(plan, profile, {}, city="广州", options=RerankOptions())
    check("rerank/note_disclaims_checker", "官方 checker" in scored["note"])
    check("rerank/components_bounded",
          all(0.0 <= value <= 1.0 for value in scored["components"].values()),
          str(scored["components"]))


def test_tag_store_roundtrip(tmp_path: Path | None = None):
    path = (tmp_path or (ROOT / "data" / "__test_tag_store.sqlite"))
    if path.exists():
        path.unlink()
    store = TagStore(path)
    record = TagEvidence(local_poi_id="sandbox:北京:故宫博物院", tag_id="child_friendly",
                         value=True, value_type="bool", evidence_kind="platform_tag",
                         city="北京", poi_name="故宫博物院", source_name="baidu",
                         excerpt="适合亲子", licence_status="api_terms_ok",
                         retrieved_at="2026-10-21T00:00:00+00:00", confidence=0.55,
                         status="accept")
    snapshot = store.add_many([record], note="unit test")
    view = store.by_poi(snapshot)
    check("store/roundtrip", view["sandbox:北京:故宫博物院"]["child_friendly"]["value"] is True)
    check("store/snapshot_counts", store.counts()["accept"] == 1, str(store.counts()))
    info = store.snapshot_info(snapshot)
    check("store/snapshot_meta", info and info["n_accept"] == 1)
    store.conn.close()
    if path.name.startswith("__test"):
        path.unlink(missing_ok=True)


def test_taxonomy_integrity():
    bad = []
    for tag_id, spec in TAXONOMY.items():
        if spec["value_type"] in ("ordinal", "enum") and not spec.get("values"):
            bad.append(tag_id)
        if spec["polarity"] not in ("benefit", "burden", "neutral"):
            bad.append(tag_id)
        if not spec.get("direction"):
            bad.append(tag_id)
    check("taxonomy/complete", not bad, str(bad))
    check("taxonomy/size", len(TAXONOMY) >= 30, str(len(TAXONOMY)))


def main() -> int:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                FAILED.append((name, f"raised {type(exc).__name__}: {exc}"))
    print(f"PASS {len(PASSED)}  FAIL {len(FAILED)}")
    for name in PASSED:
        print(f"  ok   {name}")
    for name, detail in FAILED:
        print(f"  FAIL {name}: {detail}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
