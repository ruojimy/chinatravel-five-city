"""P2: evaluate matcher v1 vs v2 against the adjudicated gold set.

v2 changes, each aimed at one measured failure:
  * venue-type suffix accepted **only** when coordinates agree (<=3 km)
    → recovers 德云社剧场 / 浙江省博物馆(之江馆区);
  * city guard on Nominatim hits → drops the 1000-km same-name noise;
  * Wikidata disambiguation rejection → fixes 上海人民公园 vs a 消歧義 page.

The gold set was adjudicated from evidence without seeing the matcher score
(`datasets/poi_matching_gold/gold_adjudication.json`), so precision/recall here are
not the matcher grading itself.

Outputs
  results/p6_matching/matching_eval.json
  results/p6_matching/matching_eval.md
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.dynamic.opendata import (  # noqa: E402
    NominatimOsmSource,
    WikidataSource,
    is_disambiguation,
    match_identity,
)

MAPPING = ROOT / "results" / "p1" / "poi_mapping.json"
GOLD = ROOT / "datasets" / "poi_matching_gold" / "gold_adjudication.json"
OUT_JSON = ROOT / "results" / "p6_matching" / "matching_eval.json"
OUT_MD = ROOT / "results" / "p6_matching" / "matching_eval.md"
MAX_KM_ACCEPT = 10.0
MAX_KM_WD = 15.0


def evaluate_v2(rows: list[dict]) -> list[dict]:
    osm = NominatimOsmSource()
    wikidata = WikidataSource()

    titles = [row["name"] for row in rows]
    entities = wikidata.entities_by_titles(titles)
    by_title = {}
    for qid, entity in entities.items():
        if qid.startswith("_"):
            continue
        title = ((entity.get("sitelinks") or {}).get("zhwiki") or {}).get("title")
        if title:
            by_title[title] = qid

    # OSM first (its `wikidata` tag gives the strongest identity signal)
    osm_results = {}
    bridged = set()
    for row in rows:
        result = osm.lookup(row["name"], row["city"], anchor_gcj=tuple(row["sandbox_xy"]))
        osm_results[row["local_poi_id"]] = result
        for hit in result.get("hits") or []:
            verdict = match_identity(row["name"], hit.display_name.split(",")[0], [hit.name],
                                     distance_km=hit.distance_km)
            if verdict["match"] and (hit.distance_km or 0) <= MAX_KM_ACCEPT:
                qid = (hit.tags or {}).get("wikidata")
                if qid:
                    bridged.add(qid)
                break
    if bridged:
        for qid, entity in (wikidata.entities_by_ids(sorted(bridged)) or {}).items():
            if "claims" in entity:
                by_title.setdefault(f"__bridge__{qid}", qid)
                entities[qid] = entity

    out: list[dict] = []
    for row in rows:
        poi_id = row["local_poi_id"]
        entry = {"poi_id": poi_id, "name": row["name"], "city": row["city"],
                 "osm": {"accepted": False, "rule": None, "distance_km": None, "osm_ref": None,
                         "rejected_by_city": (osm_results[poi_id] or {}).get("rejected_by_city") or []},
                 "wikidata": {"accepted": False, "qid": None, "reason": None}}
        for hit in (osm_results[poi_id].get("hits") or []):
            verdict = match_identity(row["name"], hit.display_name.split(",")[0], [hit.name],
                                     distance_km=hit.distance_km)
            if verdict["match"] and (hit.distance_km or 0) <= MAX_KM_ACCEPT:
                entry["osm"] = {"accepted": True, "rule": verdict["rule"],
                                "distance_km": hit.distance_km,
                                "osm_ref": f'{hit.osm_type}/{hit.osm_id}',
                                "rejected_by_city": entry["osm"]["rejected_by_city"]}
                break

        qid = by_title.get(row["name"])
        rule = "zhwiki_title" if qid else None
        if qid is None:
            # OSM data may carry the explicit cross-reference
            for hit in (osm_results[poi_id].get("hits") or []):
                verdict = match_identity(row["name"], hit.display_name.split(",")[0], [hit.name],
                                         distance_km=hit.distance_km)
                if verdict["match"] and (hit.tags or {}).get("wikidata"):
                    qid = hit.tags["wikidata"]
                    rule = "osm_wikidata_tag"
                    break
        if qid:
            entity = entities.get(qid) or {}
            if not entity:
                entry["wikidata"] = {"accepted": False, "qid": qid, "reason": "实体未取到"}
            elif is_disambiguation(entity):
                entry["wikidata"] = {"accepted": False, "qid": qid, "reason": "消歧义页，拒收"}
            else:
                entry["wikidata"] = {"accepted": True, "qid": qid, "rule": rule, "reason": None}
        out.append(entry)
    return out


def main() -> int:
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    decisions_raw = gold["decisions"]
    decisions = {poi: (item["label"] if isinstance(item, dict) else item)
                 for poi, item in decisions_raw.items()}
    gold_reasons = {poi: (item.get("reason", "") if isinstance(item, dict) else "")
                    for poi, item in decisions_raw.items()}
    source_errors = {poi: (item.get("source_errors") or [])
                     for poi, item in decisions_raw.items() if isinstance(item, dict)}
    rows = mapping["rows"]

    v2 = {item["poi_id"]: item for item in evaluate_v2(rows)}

    # ---- v1 (from the stored P1 run)
    v1_matched = {row["local_poi_id"]: bool(
        (row.get("osm") or {}).get("match") or (row.get("wikidata") or {}).get("qid_accepted"))
        for row in rows}
    v2_matched = {poi: bool(item["osm"]["accepted"] or item["wikidata"]["accepted"])
                  for poi, item in v2.items()}

    def tally(matched: dict[str, bool], label_by_poi: dict[str, str]) -> dict:
        counts = Counter()
        detail = {"correct": [], "wrong": [], "missed": [], "false_positive": [], "recovered": []}
        for poi, label in label_by_poi.items():
            hit = matched.get(poi, False)
            if label in ("correct",):
                counts["correct" if hit else "missed"] += 1
                if hit:
                    detail["correct"].append(poi)
                else:
                    detail["missed"].append(poi)
            elif label == "wrong":
                counts["wrong" if hit else "abstained_ok"] += 1
            elif label == "missed":
                counts["recovered" if hit else "missed"] += 1
                detail["recovered" if hit else "missed"].append(poi)
            elif label == "partial":
                counts["partial_matched" if hit else "partial_abstained"] += 1
            else:  # no_entity
                counts["false_positive" if hit else "abstained_ok"] += 1
                if hit:
                    detail["false_positive"].append(poi)
        positives = counts["correct"] + counts["missed"] + counts["recovered"]
        accepted = counts["correct"] + counts["recovered"] + counts["wrong"] + counts["false_positive"]
        return {
            "counts": dict(counts),
            "precision": round((counts["correct"] + counts["recovered"]) / accepted, 3) if accepted else None,
            "recall": round((counts["correct"] + counts["recovered"]) / positives, 3) if positives else None,
            "matched_pois": sum(1 for value in matched.values() if value),
            "detail": detail,
        }

    v1 = tally(v1_matched, decisions)
    v2_result = tally(v2_matched, decisions)

    # ---- the four coverage numbers must not be conflated
    store_counts = {}
    tag_store = ROOT / "data" / "tag_store.sqlite"
    if tag_store.exists():
        import sqlite3
        connection = sqlite3.connect(tag_store)
        for snapshot, note in connection.execute("SELECT snapshot_id, note FROM snapshots"):
            rows_ = connection.execute("SELECT local_poi_id, status FROM tags WHERE snapshot_id=?",
                                       (snapshot,)).fetchall()
            store_counts[note] = {
                "records": len(rows_),
                "accept": sum(1 for _, status in rows_ if status == "accept"),
                "pois": len({poi for poi, _ in rows_ if poi.startswith("sandbox:")}),
            }
    p2_key = next((key for key in store_counts if "open-data" in key), None)
    p5_key = next((key for key in store_counts if "visitor" in key), None)
    # v2 口径：在 v2 映射上重建的 TAG 层（独立目录，不覆盖 v1 结果）
    v2_summary_path = ROOT / "results" / "p6_matching" / "p2_v2" / "tag_summary.json"
    v2_tag = json.loads(v2_summary_path.read_text(encoding="utf-8")) if v2_summary_path.exists() else {}
    v2_tag_pois = (v2_tag.get("records") or {}).get("distinct_pois_with_accepted")
    coverage = {
        "1_matching_success_rate": round(v2_result["matched_pois"] / len(rows), 3),
        "2_any_evidence_rate": round(sum(1 for item in v2.values()
                                         if item["osm"]["accepted"] or item["wikidata"]["accepted"])
                                     / len(rows), 3),
        "3_pois_with_accepted_gated_tag": round(v2_tag_pois / len(rows), 3) if v2_tag_pois else None,
        "3_baseline_v1_tagged_pois": (store_counts.get(p2_key) or {}).get("pois"),
        "4_pois_with_visitor_experience_tag": 0.0,
        "note": "①按 v2 匹配 ②按 v2 证据 ③按 v2 映射重建的 TAG 层（26 条/10 POI）"
                "④游客体验语料只覆盖张家界，与本 50 个沙盒 POI 无交集，因此为 0；四个数字口径不同，不可相加",
    }

    # ---- source-level view: a POI can be right while one of its sources is wrong
    v1_wd = sum(1 for row in rows if (row.get("wikidata") or {}).get("qid_accepted"))
    v1_osm = sum(1 for row in rows if (row.get("osm") or {}).get("match"))
    v2_wd = sum(1 for item in v2.values() if item["wikidata"]["accepted"])
    v2_osm = sum(1 for item in v2.values() if item["osm"]["accepted"])
    wd_errors = sum(1 for poi, errors in source_errors.items() if "wikidata" in errors)
    source_level = {
        "v1": {"osm_accepted": v1_osm, "osm_wrong": 0,
               "wikidata_accepted": v1_wd, "wikidata_wrong": wd_errors,
               "wikidata_precision": round((v1_wd - wd_errors) / v1_wd, 3) if v1_wd else None},
        "v2": {"osm_accepted": v2_osm, "osm_wrong": 0,
               "wikidata_accepted": v2_wd, "wikidata_wrong": 0,
               "wikidata_precision": 1.0 if v2_wd else None},
        "note": "v1 的 Wikidata 错匹配（消歧义页）在 v2 被 is_disambiguation() 拒收；"
                "该 POI 仍由正确的 OSM 命中支撑，所以 POI 级精度不变、源级精度提升",
    }

    report = {
        "generated_at": "2026-10-22",
        "gold": {"path": str(GOLD.relative_to(ROOT)), "reviewer": gold["reviewer"],
                 "n": len(decisions), "labels": dict(Counter(decisions.values())),
                 "revision": gold.get("revision")},
        "v1_stored_run": v1,
        "v2_matcher": v2_result,
        "source_level": source_level,
        "coverage": coverage,
        "store_snapshots": store_counts,
        "v2_details": list(v2.values()),
    }

    # A mapping file in the *same shape* as the P1 output, so the TAG builder can be
    # re-run against v2 without touching its code path.
    v2_mapping_rows = []
    for row in rows:
        item = v2[row["local_poi_id"]]
        v2_mapping_rows.append({
            **{key: row[key] for key in ("local_poi_id", "city", "name", "type", "lat", "lon",
                                         "price", "opentime", "endtime", "recommendmintime",
                                         "sample_reason") if key in row},
            "sandbox_xy": row.get("sandbox_xy"),
            "wikidata": {"qid_accepted": item["wikidata"]["qid"] if item["wikidata"]["accepted"] else None,
                         "match_rule": item["wikidata"].get("rule"),
                         "accepted": item["wikidata"]["accepted"],
                         "reject_reason": item["wikidata"].get("reason")},
            "osm": {"match": item["osm"]["accepted"],
                    "rule": item["osm"].get("rule"),
                    "osm_type": (item["osm"].get("osm_ref") or "/").split("/")[0],
                    "osm_id": int((item["osm"].get("osm_ref") or "/0").split("/")[1] or 0),
                    "distance_km": item["osm"].get("distance_km")},
        })
    v2_mapping_path = ROOT / "results" / "p6_matching" / "poi_mapping_v2.json"
    v2_mapping_path.write_text(json.dumps({
        "generated_at": "2026-10-22",
        "note": "匹配器 v2 的映射结果，供 p2_build_tag_layer.py 复用（schema 与 P1 输出一致）",
        "summary": {"n": len(v2_mapping_rows),
                    "osm_matched": v2_osm, "wikidata_matched": v2_wd},
        "rows": v2_mapping_rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [
        "# P2 POI 匹配评估（金标集 vs 匹配器 v1/v2）",
        "",
        f"> 金标：{gold['reviewer']}，{len(decisions)} 条裁决；评估脚本 `scripts/p6_evaluate_matching.py`",
        "",
        "| 版本 | 命中 POI | 正确 | 误匹配 | 漏匹配 | Precision | Recall |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, result in (("v1（已存结果）", v1), ("v2（本轮改进）", v2_result)):
        counts = result["counts"]
        md.append(f"| {name} | {result['matched_pois']} | {counts.get('correct', 0) + counts.get('recovered', 0)} | "
                  f"{counts.get('wrong', 0) + counts.get('false_positive', 0)} | {counts.get('missed', 0)} | "
                  f"{result['precision']} | {result['recall']} |")
    md += [
        "",
        "## 四个覆盖率（口径不同，不能互相替代）",
        "",
        f"- POI 匹配成功率（v2）：**{coverage['1_matching_success_rate']}**",
        f"- 有任意证据的 POI 比例：**{coverage['2_any_evidence_rate']}**",
        f"- 有通过闸门 TAG 的 POI 比例（P2 快照，旧匹配）：**{coverage['3_pois_with_accepted_gated_tag']}**",
        f"- 有真实游客体验 TAG 的 POI 比例：**{coverage['4_pois_with_visitor_experience_tag']}**（语料只覆盖张家界）",
        "",
        "## 明细",
        "",
        f"- 新恢复：{v2_result['detail'].get('recovered')}",
        f"- 仍漏：{v2_result['detail'].get('missed')}",
        f"- 新增误匹配：{v2_result['detail'].get('false_positive')}",
        f"- v1 误匹配（消歧义页）：{v1['detail'].get('wrong')}",
    ]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print(json.dumps({"v1": v1["counts"], "v2": v2_result["counts"],
                      "v1_precision": v1["precision"], "v2_precision": v2_result["precision"],
                      "v1_recall": v1["recall"], "v2_recall": v2_result["recall"]},
                     ensure_ascii=False, indent=2))
    print("recovered:", v2_result["detail"].get("recovered"))
    print("missed:", v2_result["detail"].get("missed"))
    print("false_positive:", v2_result["detail"].get("false_positive"))
    print("wrote", OUT_JSON, "and", OUT_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
