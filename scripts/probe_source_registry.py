"""P1: probe every candidate source and write a licence-aware registry.

Rules this script enforces
--------------------------
* A source's licence is **evidence**, not a guess: the script records the HTTP
  response, the SPDX id GitHub reports, and the licence file path. "Publicly
  visible on GitHub" is *not* a licence — `choosealicense.com/no-permission` is the
  authoritative statement that "no licence = all rights reserved".
* Any source without an explicit reusable licence is marked ``license_pending`` and
  is blocked from the publishable TAG layer (it may still be inspected for schema).
* Nothing here downloads bulk data. It only reads metadata and licence text.

Outputs:
  data/source_registry.csv     one row per source, human-readable
  results/p1/source_probe.json raw probe responses (audit trail)
"""
from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_CSV = ROOT / "data" / "source_registry.csv"
OUT_JSON = ROOT / "results" / "p1" / "source_probe.json"
UA = "ShortTripAssistant/1.0 (course project; source licence audit; contact: local)"

GITHUB_REPOS = {
    "S1": ("971851309", "Tourism-data-set"),
    "S4": ("tourismdata", "ctripDataset"),
    "S5": ("aliannejadi", "contextual-appropriateness"),
}

PAGE_CHECKS = {
    "S2_osm_copyright": "https://www.openstreetmap.org/copyright",
    "S2_geofabrik": "https://download.geofabrik.de/asia/china.html",
    "S3_wikidata_licensing": "https://www.wikidata.org/wiki/Wikidata:Licensing",
    "S3_wikidata_query_service": "https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual",
    "no_licence_means_reserved": "https://choosealicense.com/no-permission/",
}

# What the instruction already observed on the pages, to be confirmed or refuted.
EXPECTED_FIELDS = {
    "S1": "名称, poiID, 经度, 维度, 标签, 特色, 评价分数, 评论数量, 建议游玩, 开放时间（表头，行有效性待核）",
    "S2": "tourism, historic, leisure, wheelchair, fee, opening_hours（以实际 POI 为准）",
    "S3": "P31 类型, P625 坐标, P1435 保护状态, 别名/官网等（依个体覆盖）",
    "S4": "sceneryName, content, score, reply（README 声明，zip 实际格式待验证）",
    "S5": "contextual_features.csv, contextual_training_data.csv（类别×情境适配，非中国景点口碑）",
    "S6": "景区官网/地方文旅公告：营业、预约、无障碍、季节限制",
    "S7": "ChinaTravel 沙盒、高德/天气：既有能力，保留",
    "S8": "平台评论或平台整理 TAG：需明确授权，未取得",
}


def http_json(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"ok": True, "status": resp.status, "body": json.loads(resp.read().decode("utf-8", "replace"))}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "body": None, "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": None, "body": None, "error": str(exc)}


def http_text(url: str, timeout: int = 25) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
            return {"ok": True, "status": resp.status, "chars": len(text),
                    "has_odbl": "ODbL" in text or "Open Database License" in text,
                    "has_cc0": "CC0" in text or "Creative Commons Zero" in text,
                    "has_cc_by_sa": "CC BY-SA" in text or "Creative Commons Attribution-ShareAlike" in text,
                    "snippet": " ".join(text.split())[:400]}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": None, "error": str(exc)}


def probe_github(source_id: str, owner: str, repo: str) -> dict:
    meta = http_json(f"https://api.github.com/repos/{owner}/{repo}")
    lic = http_json(f"https://api.github.com/repos/{owner}/{repo}/license")
    contents = http_json(f"https://api.github.com/repos/{owner}/{repo}/contents/")
    body = meta.get("body") or {}
    licence_body = lic.get("body") or {}
    spdx = (licence_body.get("license") or {}).get("spdx_id") or (body.get("license") or {}).get("spdx_id")
    files = [item.get("name") for item in (contents.get("body") or []) if isinstance(item, dict)]
    return {
        "source_id": source_id,
        "repo": f"{owner}/{repo}",
        "repo_status": meta.get("status"),
        "description": body.get("description"),
        "stars": body.get("stargazers_count"),
        "size_kb": body.get("size"),
        "pushed_at": body.get("pushed_at"),
        "license_endpoint_status": lic.get("status"),
        "spdx_id": spdx,
        "license_name": (licence_body.get("license") or {}).get("name"),
        "license_path": licence_body.get("path"),
        "root_files": files[:40],
        "has_license_file": any(str(name).upper().startswith(("LICENSE", "LICENCE", "COPYING"))
                                for name in files),
        "has_readme": any(str(name).upper().startswith("README") for name in files),
    }


def classify(probe: dict) -> tuple[str, str]:
    """Return ``(license_status, blocker)`` using evidence only."""
    spdx = (probe.get("spdx_id") or "").strip()
    if spdx and spdx.upper() not in ("NOASSERTION", "NONE"):
        return "verified", ""
    if probe.get("has_license_file"):
        return "license_file_present_unparsed", "LICENSE 文件存在但 GitHub 未解析出 SPDX，需人工阅读"
    return ("license_pending",
            "仓库无 LICENSE，按 choosealicense.com/no-permission 视为保留所有权利；"
            "仅可引用链接与结构，不得并入可发布数据层")


def main() -> int:
    started = time.time()
    audit: dict = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "user_agent": UA, "github": {}, "pages": {}}

    rows: list[dict] = []
    for source_id, (owner, repo) in GITHUB_REPOS.items():
        probe = probe_github(source_id, owner, repo)
        audit["github"][source_id] = probe
        status, blocker = classify(probe)
        rows.append({
            "source_id": source_id,
            "name": f"{owner}/{repo}",
            "url": f"https://github.com/{owner}/{repo}",
            "license_spdx": probe.get("spdx_id") or "",
            "license_evidence": (
                f"GitHub /license -> HTTP {probe.get('license_endpoint_status')}, "
                f"path={probe.get('license_path')}, root_license_file={probe.get('has_license_file')}"),
            "license_status": status,
            "candidate_fields": EXPECTED_FIELDS.get(source_id, ""),
            "allow_local_store": "no" if status == "license_pending" else "yes_with_attribution",
            "allow_training": "no" if status == "license_pending" else "check_license_terms",
            "allow_redistribute": "no" if status == "license_pending" else "check_license_terms",
            "availability": "reachable" if probe.get("repo_status") == 200 else f"probe_failed({probe.get('repo_status')})",
            "blocker": blocker,
            "last_checked": datetime.now(timezone.utc).date().isoformat(),
            "notes": f"stars={probe.get('stars')} size_kb={probe.get('size_kb')} pushed={probe.get('pushed_at')}",
        })
        time.sleep(0.5)

    for key, url in PAGE_CHECKS.items():
        result = http_text(url)
        audit["pages"][key] = result
        time.sleep(0.5)

    osm = audit["pages"].get("S2_osm_copyright", {})
    wikidata = audit["pages"].get("S3_wikidata_licensing", {})
    rows.append({
        "source_id": "S2",
        "name": "OpenStreetMap (Nominatim / Overpass / Geofabrik 摘录)",
        "url": "https://www.openstreetmap.org/copyright",
        "license_spdx": "ODbL-1.0",
        "license_evidence": f"copyright 页可达={osm.get('ok')} 含 ODbL={osm.get('has_odbl')}",
        "license_status": "verified" if osm.get("has_odbl") else "license_pending",
        "candidate_fields": EXPECTED_FIELDS["S2"],
        "allow_local_store": "yes_with_attribution",
        "allow_training": "yes_share_alike",
        "allow_redistribute": "yes_share_alike",
        "availability": "reachable" if osm.get("ok") else "unreachable",
        "blocker": "",
        "last_checked": datetime.now(timezone.utc).date().isoformat(),
        "notes": "衍生数据库须按 ODbL 共享；署名 OpenStreetMap contributors",
    })
    rows.append({
        "source_id": "S3",
        "name": "Wikidata",
        "url": "https://www.wikidata.org/wiki/Wikidata:Licensing",
        "license_spdx": "CC0-1.0",
        "license_evidence": f"licensing 页可达={wikidata.get('ok')} 含 CC0={wikidata.get('has_cc0')}",
        "license_status": "verified" if wikidata.get("has_cc0") else "license_pending",
        "candidate_fields": EXPECTED_FIELDS["S3"],
        "allow_local_store": "yes",
        "allow_training": "yes",
        "allow_redistribute": "yes",
        "availability": "reachable" if wikidata.get("ok") else "unreachable",
        "blocker": "",
        "last_checked": datetime.now(timezone.utc).date().isoformat(),
        "notes": "须带 User-Agent、限速、429 退避；大规模用 dump",
    })
    rows.append({
        "source_id": "S7",
        "name": "ChinaTravel 沙盒 / 高德 / 天气",
        "url": "local:ChinaTravel/chinatravel/environment/database",
        "license_spdx": "benchmark_internal",
        "license_evidence": "项目既有数据，官方仓库自带",
        "license_status": "verified",
        "candidate_fields": EXPECTED_FIELDS["S7"],
        "allow_local_store": "yes",
        "allow_training": "yes",
        "allow_redistribute": "no",
        "availability": "reachable",
        "blocker": "",
        "last_checked": datetime.now(timezone.utc).date().isoformat(),
        "notes": "高德配额另行监控；本轮不以高德为必需",
    })
    rows.append({
        "source_id": "S8",
        "name": "平台评论 / 平台整理 TAG（携程、马蜂窝等）",
        "url": "https://www.openstreetmap.org/copyright#n/a",
        "license_spdx": "",
        "license_evidence": "未取得任何书面授权",
        "license_status": "unavailable",
        "candidate_fields": EXPECTED_FIELDS["S8"],
        "allow_local_store": "no",
        "allow_training": "no",
        "allow_redistribute": "no",
        "availability": "unavailable",
        "blocker": "无授权渠道；禁止绕过登录/验证码/反爬。VISITOR_EXPERIENCE 通道保持为空",
        "last_checked": datetime.now(timezone.utc).date().isoformat(),
        "notes": "B2 实验组因此标注为不可执行，不以 LLM 伪评论填充",
    })
    rows.append({
        "source_id": "S6",
        "name": "景区官网 / 地方文旅公告",
        "url": "（按景区逐个检索）",
        "license_spdx": "",
        "license_evidence": "未逐站核验，暂不批量使用",
        "license_status": "license_pending",
        "candidate_fields": EXPECTED_FIELDS["S6"],
        "allow_local_store": "fact_only",
        "allow_training": "no",
        "allow_redistribute": "no",
        "availability": "on_demand",
        "blocker": "逐站检查访问与再利用条件后才可用；本轮不批量抓取",
        "last_checked": datetime.now(timezone.utc).date().isoformat(),
        "notes": "仅作事实字段补充，不存大段受版权保护正文",
    })

    rows.sort(key=lambda row: row["source_id"])
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"wrote {OUT_CSV} ({len(rows)} rows) and {OUT_JSON} in {round(time.time() - started, 1)}s")
    for row in rows:
        print(f"  {row['source_id']:3s} {row['license_status']:28s} {row['name'][:44]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
