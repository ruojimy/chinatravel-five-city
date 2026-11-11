"""Mine already-saved Amap responses for fields the discovery pass ignored.

`xian_api_collect.py` requests ``show_fields=business`` but only persists name +
coordinates, so every ``opentime_today`` / ``cost`` / ``keytag`` / ``type`` it
already paid for sits unused in ``raw_api/``. This pass re-reads those bytes and
turns them into an ``--enrich`` jsonl for ``xian_ingest.py`` — zero network,
zero quota, same evidence rules as the live lanes.

Rules (mirrors FIELD_PHASE_PROMPT §1–2):
  * single opening interval only; multi-interval or 24:00 crossing is left null
  * restaurant price = Amap ``business.cost`` (per-capita, same definition)
  * attraction/accommodation never get a price from Amap (it has none)
  * every value is quoted verbatim from the saved response
  * only null fields are proposed; ingest still refuses to overwrite

Streams one response file at a time; peak memory is the name index, not the corpus.

Usage:
  XT_CITY=厦门 python scripts/mine_amap_cache.py \
      --snapshot results/<run>/snapshot_v1/catalog.sqlite3 \
      --raw-glob 'results/<run>/raw_api/amap_*.json' \
      --out results/<run>/staging/mine/mine.jsonl
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from xt_city import city as _city  # noqa: E402

CITY = _city()
TIME_RE = re.compile(r"(\d{2}:\d{2})-(\d{2}:\d{2})")
GENERIC_TAGS = {"风景名胜", "其他", "景区", "旅游景点", "餐饮相关", "餐饮服务", "美食", "餐厅",
                "中餐厅", "综合酒楼", "住宿服务", "宾馆酒店", "星级酒店", "经济型连锁酒店"}

# Amap typecode family -> catalog kind
FAMILY = (("11", "attraction"), ("14", "attraction"), ("08", "attraction"),
          ("05", "restaurant"), ("10", "accommodation"))


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def norm(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").replace("（", "(").replace("）", ")")).lower()


def family_of(typecode: str) -> str | None:
    for prefix, kind in FAMILY:
        if (typecode or "").startswith(prefix):
            return kind
    return None


def single_interval(raw: str) -> tuple[str, str] | None:
    """Return (start, end) only when the string is one unambiguous same-day interval."""
    text = (raw or "").strip()
    if not text or "24:00" in text:
        return None
    found = TIME_RE.findall(text)
    if len(found) != 1:
        return None
    start, end = found[0]
    if int(start[:2]) >= 24 or int(end[:2]) >= 24:
        return None
    if start == end:
        return None
    return start, end


def tag_of(poi: dict) -> str | None:
    biz = poi.get("business") or {}
    tag = (biz.get("keytag") or "").strip()
    if not tag:
        return None
    candidate = next((s.strip() for s in re.split(r"[,，;；]", tag)
                      if s.strip() and s.strip() not in GENERIC_TAGS), None)
    if not candidate or len(candidate) > 20:
        return None
    return candidate


def type_of(poi: dict) -> str | None:
    parts = [p.strip() for p in str(poi.get("type") or "").split(";") if p.strip()]
    if not parts:
        return None
    candidate = parts[1] if len(parts) > 1 else parts[0]
    if candidate in GENERIC_TAGS or len(candidate) > 20:
        candidate = parts[-1]
    if candidate in GENERIC_TAGS or len(candidate) > 20:
        return None
    return candidate


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--raw-glob", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    snap = Path(args.snapshot)
    if not snap.is_absolute():
        snap = ROOT / snap
    conn = sqlite3.connect(snap.resolve().as_uri() + "?mode=ro", uri=True)

    wanted: dict[tuple[str, str], str] = {}
    for rid, kind, name, payload in conn.execute(
            "select id, kind, name, payload from records where city=?", (CITY,)):
        data = (json.loads(payload).get("data") or {})
        wanted[(kind, norm(name))] = rid
    conn.close()

    files = sorted(glob.glob(str(ROOT / args.raw_glob) if not Path(args.raw_glob).is_absolute()
                             else args.raw_glob))
    stats = {"files": 0, "pois": 0, "matched": 0, "fields": {}, "skipped": {}}
    items: dict[tuple[str, str], dict] = {}

    def bump(bucket: str, key: str) -> None:
        stats[bucket][key] = stats[bucket].get(key, 0) + 1

    for path in files:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            bump("skipped", "unreadable_raw")
            continue
        if str(data.get("status")) != "1":
            bump("skipped", "provider_not_ok")
            continue
        stats["files"] += 1
        rel = str(Path(path).relative_to(ROOT)).replace("\\", "/")
        for poi in data.get("pois") or []:
            stats["pois"] += 1
            name = str(poi.get("name") or "").strip()
            kind = family_of(str(poi.get("typecode") or ""))
            if not name or not kind:
                continue
            key = (kind, norm(name))
            if key not in wanted:
                continue
            stats["matched"] += 1
            biz = poi.get("business") or {}
            fields: dict[str, object] = {}
            quote = name

            hours = single_interval(str(biz.get("opentime_today") or ""))
            if hours:
                fields["opentime"], fields["endtime"] = hours
                quote = f"{hours[0]}-{hours[1]}"

            if kind == "restaurant":
                cost = str(biz.get("cost") or "").strip()
                if cost and cost not in ("0", "0.00"):
                    try:
                        value = float(cost)
                    except ValueError:
                        value = None
                    if value and 1 <= value <= 3000:
                        fields["price"] = int(value) if value == int(value) else value
                        if quote == name:
                            quote = cost
                tag = tag_of(poi)
                if tag:
                    fields["cuisine"] = tag
            elif kind == "attraction":
                theme = type_of(poi)
                if theme:
                    fields["type"] = theme
            else:  # accommodation
                tag = tag_of(poi)
                if tag:
                    fields["featurehoteltype"] = tag

            if not fields:
                continue
            existing = items.get(key)
            if existing is None or len(fields) > len(existing["data"]):
                items[key] = {
                    "kind": kind, "name": name, "aliases": [], "data": fields,
                    "source": {
                        "url": "https://restapi.amap.com/v5/place/text",
                        "publisher": "高德开放平台", "authority": "amap_place_api",
                        "licence_status": "provider_terms_pending_review",
                        "trust_status": "provider_listing",
                        "published_at": None, "observed_at": None,
                    },
                    "evidence": {"raw_path": rel, "quote": quote,
                                 "locator": f"business/{','.join(fields)}（缓存回采，无新请求）",
                                 "identity_basis": "name"},
                    "notes": "零网络回采已保存的高德响应；仅单一营业区间，24:00 与多区间留空",
                }

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for item in items.values():
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    for item in items.values():
        for field in item["data"]:
            stats["fields"][field] = stats["fields"].get(field, 0) + 1
    summary = {
        "city": CITY, "snapshot": str(snap), "raw_files": stats["files"],
        "pois": stats["pois"], "matched": stats["matched"], "items": len(items),
        "fields": stats["fields"], "skipped": stats["skipped"],
        "out": str(out.relative_to(ROOT)).replace("\\", "/"), "checked_at": now_iso(),
    }
    if args.report:
        Path(args.report).write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n",
                                     encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
