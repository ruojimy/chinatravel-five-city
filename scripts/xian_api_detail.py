"""Fill missing native fields on existing Xi'an records from Amap business data.

One exact-name lookup per record; only unambiguous values are emitted:
  * a single HH:MM-HH:MM interval -> opentime / endtime
  * numeric business.cost -> price
  * business.keytag / rectag -> cuisine (restaurant only)
  * business.tag -> recommendedfood (restaurant only)

Every response is stored as raw bytes under <run>/raw_api/ so the ingest gate
can re-check the quote and hash. Output is an --enrich jsonl for xian_ingest.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CITY = "西安"
URL = "https://restapi.amap.com/v5/place/text"
TIME_RE = re.compile(r"(\d{2}:\d{2})-(\d{2}:\d{2})")
RATE_CODES = {"10021", "10019", "10020", "10004"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def norm(name: str) -> str:
    name = (name or "").replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", "", name).lower()


def fetch(params: dict) -> bytes | None:
    url = URL + "?" + urllib.parse.urlencode(params)
    for attempt in (1, 2, 3):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers={"User-Agent": "ShortTripDetail/1.0"}),
                    timeout=25) as response:
                raw = response.read(4 * 1024 * 1024)
            data = json.loads(raw.decode("utf-8", errors="replace"))
            if str(data.get("infocode")) in RATE_CODES:
                time.sleep(1.5 * attempt)
                continue
            return raw
        except Exception:  # noqa: BLE001
            time.sleep(1.0 * attempt)
    return None


def parse_business(business: dict, kind: str) -> dict:
    out = {}
    hours = TIME_RE.findall(str(business.get("opentime_today") or ""))
    if len(hours) == 1:
        start, end = hours[0]
        if int(start[:2]) < 24 and int(end[:2]) < 24:
            out["opentime"], out["endtime"] = start, end
    cost = business.get("cost")
    try:
        if cost not in (None, "", "0", "0.00"):
            out["price"] = float(cost)
    except (TypeError, ValueError):
        pass
    if kind == "restaurant":
        tag = (business.get("keytag") or business.get("rectag") or "").strip()
        if tag and len(tag) <= 24:
            out["cuisine"] = tag.split(";")[0].split(",")[0].strip()
        food = (business.get("tag") or "").strip()
        if food:
            out["recommendedfood"] = food[:120]
    for key, value in list(out.items()):
        if value in (None, ""):
            out.pop(key)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--worker", default="api_detail")
    parser.add_argument("--kind", required=True,
                        choices=["attraction", "restaurant", "accommodation"])
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--max-calls", type=int, default=80)
    parser.add_argument("--sleep", type=float, default=0.8)
    args = parser.parse_args()

    run_dir = Path(args.run)
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    raw_dir = run_dir / "raw_api"
    out_dir = run_dir / "staging" / args.worker
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    snapshot = Path(args.snapshot)
    if not snapshot.is_absolute():
        snapshot = ROOT / snapshot
    import sqlite3
    conn = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)
    rows = conn.execute(
        f"select name, payload from records where city='{CITY}' and kind=? order by id",
        (args.kind,)).fetchall()
    conn.close()

    candidates = []
    for name, payload_raw in rows:
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            continue
        data = payload.get("data") or {}
        wanted = ["price", "opentime", "endtime"]
        if args.kind == "restaurant":
            wanted += ["cuisine", "recommendedfood"]
        if any(data.get(key) in (None, "") for key in wanted):
            candidates.append((name, data))
        if len(candidates) >= args.limit:
            break

    key = (ROOT / ".secrets/amap.key").read_text(encoding="ascii").strip()
    items, log = [], []
    for index, (name, data) in enumerate(candidates[:args.max_calls]):
        raw = fetch({"keywords": name, "region": CITY, "city_limit": "true",
                     "page_size": "3", "show_fields": "business", "key": key})
        if raw is None:
            log.append({"name": name, "ok": False, "reason": "request_failed"})
            break
        file = raw_dir / f"detail_{args.kind}_{index:04d}.json"
        file.write_bytes(raw)
        rel = str(file.relative_to(ROOT)).replace("\\", "/")
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        pois = payload.get("pois") or []
        exact = [p for p in pois if norm(p.get("name")) == norm(name)]
        if not exact:
            log.append({"name": name, "ok": False, "reason": "no_exact_name_match",
                        "returned": [p.get("name") for p in pois][:3]})
        else:
            poi = exact[0]
            fields = parse_business(poi.get("business") or {}, args.kind)
            fields = {k: v for k, v in fields.items() if data.get(k) in (None, "")}
            if fields:
                items.append({
                    "kind": args.kind,
                    "name": name,
                    "aliases": [],
                    "data": fields,
                    "source": {
                        "url": URL, "publisher": "高德开放平台",
                        "authority": "amap_place_api",
                        "licence_status": "provider_terms_pending_review",
                        "trust_status": "provider_listing",
                        "published_at": None, "observed_at": None,
                    },
                    "evidence": {
                        "raw_path": rel,
                        "quote": str(poi.get("name") or name),
                        "locator": f"id={poi.get('id')} business 字段",
                    },
                    "notes": "detail 补全：仅取单一营业区间与数值型 cost；多段营业时间不猜",
                })
            log.append({"name": name, "ok": True, "fields": list(fields),
                        "raw_path": rel, "raw_sha256": hashlib.sha256(raw).hexdigest()})
        time.sleep(max(args.sleep, 0.6))

    out_path = out_dir / f"enrich_{args.kind}.jsonl"
    with open(out_path, "w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    (out_dir / f"api_log_{args.kind}.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in log) + "\n", encoding="utf-8")
    print(json.dumps({"kind": args.kind, "candidates": len(candidates),
                      "calls": len(log), "enrich_items": len(items),
                      "out": str(out_path.relative_to(ROOT)).replace("\\", "/"),
                      "checked_at": now_iso()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
