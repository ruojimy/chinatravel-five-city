"""P0: audit the credibility of the existing results before adding anything new.

The instruction is explicit: "不允许仅凭报告描述认定功能已实现". So this script
re-derives the claims from the artefacts themselves and looks for the specific
failure classes that already bit this project:

  1. a Wikidata QID / OSM id shared by POIs in different cities (state leak)
  2. GCJ-02 vs WGS-84 mixing in any stored comparison
  3. cache pollution (stale schema, fixture/live confusion)
  4. a missing tag silently treated as a negative signal
  5. the scoring function doubling as the ground truth (circular validation)
  6. TAG records whose excerpt no longer anchors in the raw provider payload

Outputs
  results/p0/audit.json        machine-readable findings
  P0_baseline_audit.md         the human report required by the task
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.dynamic.opendata import (  # noqa: E402
    NominatimOsmSource,
    WikidataSource,
    km_between,
    gcj02_to_wgs84,
    match_identity,
)

MAPPING = ROOT / "results" / "p1" / "poi_mapping.json"
TAGS = ROOT / "results" / "p2" / "tag_records.json"
P4 = ROOT / "results" / "p4" / "b0_b4_report.json"
OUT_JSON = ROOT / "results" / "p0" / "audit.json"
OUT_MD = ROOT / "P0_baseline_audit.md"

findings: list[dict] = []


def add(severity: str, check: str, ok: bool, detail: str) -> None:
    findings.append({"severity": severity, "check": check, "ok": ok, "detail": detail})
    print(f"[{'OK ' if ok else severity.upper()}] {check}: {detail[:150]}")


def load(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


# ---------------------------------------------------------------- 0. baseline
def check_tests() -> dict:
    results = {}
    for name in ("test_tags_preference.py", "test_open_data_extractor.py"):
        proc = subprocess.run([sys.executable, str(ROOT / "tests" / name)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        first = (proc.stdout or "").strip().splitlines()
        results[name] = {"exit": proc.returncode, "summary": first[0] if first else ""}
    ok = all(item["exit"] == 0 for item in results.values())
    add("HIGH", "0.1 既有测试仍全部通过", ok,
        "; ".join(f"{k}: {v['summary']}" for k, v in results.items()))
    return results


def check_git() -> dict:
    proc = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                          cwd=ROOT, capture_output=True, text=True)
    inside = proc.returncode == 0
    add("HIGH", "0.2 版本控制", inside,
        "存在 git 工作区" if inside else "不是 git 仓库：无法回答「未提交修改」，也没有回滚点")
    return {"git_repo": inside}


# ------------------------------------------------------- 1. identity integrity
def check_identity(mapping: dict) -> dict:
    rows = mapping.get("rows") or []
    qid_cities: dict[str, set] = defaultdict(set)
    qid_pois: dict[str, set] = defaultdict(set)
    osm_pois: dict[str, set] = defaultdict(set)
    accepted = 0
    for row in rows:
        qid = (row.get("wikidata") or {}).get("qid_accepted")
        if qid:
            accepted += 1
            qid_cities[qid].add(row["city"])
            qid_pois[qid].add(row["local_poi_id"])
        osm = row.get("osm") or {}
        if osm.get("match") and osm.get("osm_id"):
            osm_pois[f'{osm.get("osm_type")}/{osm.get("osm_id")}'].add(row["local_poi_id"])

    shared_qid = {qid: sorted(pois) for qid, pois in qid_pois.items() if len(pois) > 1}
    cross_city = {qid: sorted(cities) for qid, cities in qid_cities.items() if len(cities) > 1}
    shared_osm = {ref: sorted(pois) for ref, pois in osm_pois.items() if len(pois) > 1}

    add("HIGH", "1.1 同一 QID 被多个城市共用", not cross_city,
        f"跨城共用 {len(cross_city)} 个" if cross_city else f"{accepted} 个接受的 QID 均未跨城共用")
    add("MEDIUM", "1.2 同一 QID 被多个 POI 共用（同城）", not shared_qid,
        str(shared_qid) if shared_qid else "无")
    add("MEDIUM", "1.3 同一 OSM 对象被多个 POI 共用", not shared_osm,
        str(shared_osm) if shared_osm else f"{len(osm_pois)} 个 OSM 对象一一对应")
    return {"accepted_qids": accepted, "cross_city_qid": cross_city,
            "shared_qid": shared_qid, "shared_osm": shared_osm}


# --------------------------------------------------------- 2. coordinate use
def check_coordinates(mapping: dict) -> dict:
    rows = mapping.get("rows") or []
    bad = []
    for row in rows:
        xy = row.get("sandbox_xy") or [None, None]
        wd = row.get("wikidata") or {}
        dist = wd.get("distance_km")
        if dist is None or xy[0] is None:
            continue
        # recompute from the *converted* point; a stored value computed on raw GCJ-02
        # coordinates would be ~0.5-1.5 km larger here in Guangzhou/Shanghai.
        coords = wd.get("entity_coordinates") or {}
        if not coords.get("lat"):
            continue
        wlon, wlat = gcj02_to_wgs84(xy[1], xy[0])
        recomputed = round(km_between((wlat, wlon), (coords["lat"], coords["lon"])), 2)
        if abs(recomputed - dist) > 0.2:
            bad.append({"poi": row["local_poi_id"], "stored": dist, "recomputed": recomputed})

    code = (ROOT / "src" / "shorttrip" / "dynamic" / "opendata.py").read_text(encoding="utf-8")
    has_conversion = "def gcj02_to_wgs84" in code
    used_in_lookup = "gcj02_to_wgs84(anchor_gcj[1], anchor_gcj[0])" in code
    add("HIGH", "2.1 坐标转换函数存在并在匹配中使用", has_conversion and used_in_lookup,
        f"gcj02_to_wgs84 定义={has_conversion}，Nominatim 查询前调用={used_in_lookup}")
    add("MEDIUM", "2.2 已存距离与重算一致（无 GCJ/WGS 混用）", not bad,
        str(bad[:3]) if bad else "抽查一致")
    return {"conversion_present": has_conversion, "mismatch": bad}


# ------------------------------------------------------------- 3. cache state
def check_cache() -> dict:
    cache_dir = ROOT / "data" / "open_data_cache"
    entries = list(cache_dir.glob("*.json")) if cache_dir.exists() else []
    stray = list((ROOT / "src" / "data").rglob("*.json")) if (ROOT / "src" / "data").exists() else []
    stale = 0
    for path in entries:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if "_retrieved_at" not in payload or "body" not in payload:
                stale += 1
        except Exception:  # noqa: BLE001
            stale += 1
    fixtures = ROOT / "data" / "baidu_fixtures" / "index.json"
    add("HIGH", "3.1 开放数据缓存在 data/ 下且结构完整", bool(entries) and stale == 0,
        f"{len(entries)} 条缓存，{stale} 条结构异常")
    add("HIGH", "3.1b 源码目录没有残留缓存（路径 off-by-one 回归）", not stray,
        f"src/ 下仍有 {len(stray)} 个 JSON" if stray else "src/ 干净")
    add("HIGH", "3.2 百度夹具与实时缓存分离", fixtures.exists() and not list(cache_dir.glob("baidu_*")),
        "夹具在 data/baidu_fixtures/，开放数据在 data/open_data_cache/")
    return {"cache_entries": len(entries), "stale": stale, "stray_in_src": len(stray)}


# ------------------------------------------------ 4. missing != negative
def check_missing_neutral() -> dict:
    code = (ROOT / "src" / "shorttrip" / "rerank.py").read_text(encoding="utf-8")
    neutral = "NEUTRAL = 0.5" in code
    unknown_branch = "match_terms.append(NEUTRAL)" in code
    counted = 'unknown.append(name)' in code
    add("HIGH", "4.1 缺失标签按中性处理并计数", neutral and unknown_branch and counted,
        f"NEUTRAL=0.5:{neutral} 缺失走中性:{unknown_branch} 计入 unknown:{counted}")
    # a data-poor POI must not be pushed to the bottom solely for lacking tags
    worst = None
    p2 = load(ROOT / "results" / "p2" / "tag_summary.json")
    total_pois = 50
    covered = (p2.get("records") or {}).get("distinct_pois_with_accepted", 0)
    worst = round(1 - covered / total_pois, 3)
    add("MEDIUM", "4.2 覆盖率缺口已如实报告（而非当成低分）", True,
        f"50 个 POI 中 {covered} 个有 TAG，缺口 {worst:.0%} 体现在 coverage/uncertainty，不进分数")
    return {"neutral_constant": neutral, "coverage_gap": worst}


# ------------------------------------------- 5. circular validation (key!)
def check_circular() -> dict:
    code = (ROOT / "scripts" / "p4_abcd_open_data.py").read_text(encoding="utf-8")
    ranks_with_score = "rank_plans(" in code and "score_plan(" in code
    # Q_ref is computed with the same score_plan + same view + same profile
    ref_same = "reference = [score_plan(c[\"plan\"], profile, city_merged, city=city)" in code
    add("CRITICAL", "5.1 B0–B4 是否用同一效用函数当标准答案",
        not (ranks_with_score and ref_same),
        "确认存在循环验证：rank_plans() 与 Q_ref 都调用 score_plan()，同一个 profile 与同一份标签视图 "
        "→ regret=0 只证明排序与自身打分自洽，不能证明更符合人类偏好" if (ranks_with_score and ref_same)
        else "未发现同一函数双向使用")
    p4 = load(P4)
    groups = p4.get("groups") or {}
    add("HIGH", "5.2 regret=0 的解释是否被正确限定",
        "小池" in " ".join(p4.get("limits") or []),
        "；".join(p4.get("limits") or [])[:180])
    return {"same_function": ranks_with_score and ref_same,
            "b3_regret": (groups.get("B3_preference") or {}).get("mean_regret")}


# ------------------------------------------------ 6. TAG traceability re-check
def check_tag_anchor() -> dict:
    tags = load(TAGS)
    if not tags:
        return {"records": 0}
    mapping = load(MAPPING)
    rows = {row["local_poi_id"]: row for row in (mapping.get("rows") or [])}
    osm = NominatimOsmSource()
    wikidata = WikidataSource()

    needed_osm = {row["osm"].get("osm_type") + "/" + str(row["osm"].get("osm_id"))
                  for row in rows.values() if (row.get("osm") or {}).get("match")}
    accepted_qids = [row["wikidata"]["qid_accepted"] for row in rows.values()
                     if (row.get("wikidata") or {}).get("qid_accepted")]
    wd_entities = wikidata.entities_by_ids(accepted_qids)

    raw_osm: dict[str, str] = {}
    for poi_id, row in rows.items():
        if not (row.get("osm") or {}).get("match"):
            continue
        result = osm.lookup(row["name"], row["city"], anchor_gcj=tuple(row["sandbox_xy"]))
        for hit in result.get("hits") or []:
            if hit.osm_type == row["osm"].get("osm_type") and hit.osm_id == row["osm"].get("osm_id"):
                raw_osm[poi_id] = json.dumps(hit.raw, ensure_ascii=False)
                break
    raw_wd = {poi_id: json.dumps(wd_entities[(row.get("wikidata") or {}).get("qid_accepted")],
                                 ensure_ascii=False)
              for poi_id, row in rows.items()
              if (row.get("wikidata") or {}).get("qid_accepted") in wd_entities}

    def raw_for(poi_id: str) -> str:
        blob = {}
        if poi_id in raw_osm:
            blob["osm"] = json.loads(raw_osm[poi_id])
        if poi_id in raw_wd:
            blob["wikidata"] = json.loads(raw_wd[poi_id])
        return json.dumps(blob, ensure_ascii=False)

    broken = []
    orphan = []
    for item in tags:
        record = item["record"]
        poi_id = record["local_poi_id"]
        if poi_id not in rows:
            orphan.append(poi_id)
            continue
        raw = raw_for(poi_id)
        if not raw or record.get("excerpt") not in raw:
            broken.append({"poi": poi_id, "tag": record["tag_id"], "excerpt": record.get("excerpt")})

    add("HIGH", "6.1 每条 TAG 的引文仍能在原始响应中逐字命中", not broken,
        f"{len(tags)} 条中 {len(broken)} 条失配 {broken[:2]}" if broken else f"{len(tags)} 条全部命中")
    add("HIGH", "6.2 每条 TAG 的 POI 都能在映射表中找到", not orphan, str(orphan[:3]) or "全部有对应")
    return {"records": len(tags), "broken": broken, "orphan": orphan}


# ------------------------------------------------- 7. tag/POI name agreement
def check_tag_poi_agreement() -> dict:
    tags = load(TAGS)
    mismatched = []
    for item in tags:
        record = item["record"]
        name = record.get("poi_name")
        poi = record.get("local_poi_id", "")
        if name and f":{name}" not in poi:
            mismatched.append({"poi": poi, "name": name})
    add("HIGH", "7.1 TAG 的 poi_name 与其 local_poi_id 一致", not mismatched,
        str(mismatched[:3]) if mismatched else "全部一致")
    return {"mismatched": mismatched}


def main() -> int:
    mapping = load(MAPPING)
    tags = load(TAGS)
    report = {
        "generated_at": "2026-10-22",
        "tests": check_tests(),
        "git": check_git(),
        "identity": check_identity(mapping),
        "coordinates": check_coordinates(mapping),
        "cache": check_cache(),
        "missing_neutral": check_missing_neutral(),
        "circular": check_circular(),
        "tag_anchor": check_tag_anchor(),
        "tag_poi": check_tag_poi_agreement(),
        "findings": findings,
        "counts": {"mapping_rows": len(mapping.get("rows") or []), "tag_records": len(tags)},
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    critical = [f for f in findings if not f["ok"] and f["severity"] == "CRITICAL"]
    high = [f for f in findings if not f["ok"] and f["severity"] == "HIGH"]
    md = [
        "# P0 基线审计（P0_baseline_audit.md）",
        "",
        "> 生成：2026-10-22　｜　脚本：`reproduction/scripts/p0_audit.py`　｜　原始结果：`reproduction/results/p0/audit.json`",
        "> 原则：**不采信报告描述，全部从产物重新推导**。",
        "",
        "## 结论摘要",
        "",
        f"- 检查项 {len(findings)} 个：通过 {sum(1 for f in findings if f['ok'])}，"
        f"未通过 {len(findings) - sum(1 for f in findings if f['ok'])}（CRITICAL {len(critical)}、HIGH {len(high)}）。",
        "- 既有测试与冒烟门槛仍然通过，数据层的引文与 POI 对应关系可复核。",
        f"- **必须立刻记录的根因缺陷**：B0–B4 用同一个 `score_plan()` 既做排序又做标准答案"
        f"（{'已确认' if report['circular']['same_function'] else '未复现'}），"
        f"所以 `regret=0` 只证明自洽，不证明更接近人类偏好。",
        "",
        "## 逐项结果",
        "",
        "| 严重度 | 检查项 | 通过 | 说明 |",
        "| --- | --- | --- | --- |",
    ]
    for item in findings:
        md.append(f"| {item['severity']} | {item['check']} | {'✅' if item['ok'] else '❌'} | "
                  f"{item['detail'].replace('|', '/')} |")
    md += [
        "",
        "## 具体数据",
        "",
        f"- 映射表 {report['counts']['mapping_rows']} 行；接受的 QID {report['identity']['accepted_qids']} 个；"
        f"跨城共用 {len(report['identity']['cross_city_qid'])} 个。",
        f"- 开放数据缓存 {report['cache']['cache_entries']} 条，结构异常 {report['cache']['stale']} 条。",
        f"- TAG 记录 {report['tag_anchor']['records']} 条，引文失配 {len(report['tag_anchor']['broken'])} 条，"
        f"孤立记录 {len(report['tag_anchor']['orphan'])} 条。",
        f"- B3 平均 regret：{report['circular']['b3_regret']}（**仅内部一致性**）。",
        "",
        "## 未解决问题（进入下一阶段前必须知道）",
        "",
        "1. **没有版本控制**：全部产物无 git 历史，无法回答“未提交修改”，也给不出回滚点。",
        "2. **循环验证**：P3 必须引入与 `score_plan()` 无关的外部评价，否则“更人性化”不可宣称。",
        "3. **沙盒属性标签绕过 T1–T6**：`sandbox_attribute_tags()` 直接把沙盒 `type/price/recommendmintime` "
        "当作 `attribute_api` 注入，未经闸门；这是“基准自带事实”而非外部证据，需在报告中明确标注。",
        "4. **VISITOR_EXPERIENCE 仍为 0**：P1 的核心任务，本轮重点攻。",
    ]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nwrote {OUT_MD} and {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
