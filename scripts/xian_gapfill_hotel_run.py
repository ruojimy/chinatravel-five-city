"""Xi'an hotel price gap-fill: resolve hotelId via Ctrip global search, then read
the CNY 'from' price off the Trip.com (same hotelId) detail page.

Writes:
  results/xian_gapfill_20261109/raw/hotel/<hotelId>_*.html   (evidence, via xian_gapfill_fetch.py)
  results/xian_gapfill_20261109/raw/hotel/resolve/<slug>.json (name -> hotelId audit trail)
  results/xian_gapfill_20261109/staging/hotel/_run_log.jsonl  (per-hotel outcome)

Usage:
  python scripts/xian_gapfill_hotel_run.py --limit 20 [--offset 0] [--dry]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = "results/xian_gapfill_20261109"
FETCH = ROOT / "scripts/xian_gapfill_fetch.py"
PY = str(ROOT / ".venv/Scripts/python.exe")
UA_GAP = 2.5  # seconds between any two requests


def call_fetch(url: str, out_rel: str) -> dict:
    proc = subprocess.run([PY, str(FETCH), "--url", url, "--out", out_rel],
                          capture_output=True, text=True, cwd=str(ROOT))
    tail = (proc.stdout or "").strip().splitlines()
    try:
        return json.loads(tail[-1]) if tail else {"ok": False, "error": "no_output"}
    except json.JSONDecodeError:
        return {"ok": False, "error": "bad_receipt", "raw": tail[-1][:200]}


def norm(s: str) -> str:
    return re.sub(r"[\s\u3000（）()·\-,，.。、]", "", s or "").lower()


def core(name: str) -> str:
    n = re.sub(r"[（(][^）)]*[）)]", "", name)
    n = n.replace("西安", "", 1)
    return norm(n)


def slug(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name)[:60]


def resolve(name: str, out_json: str) -> tuple[str | None, str | None]:
    import urllib.parse
    kw = name if name.startswith(("西安", "陕西")) else "西安" + name
    url = ("https://m.ctrip.com/restapi/h5api/globalsearch/search?action=json&keyword="
           + urllib.parse.quote(kw))
    r = call_fetch(url, out_json)
    if not r.get("ok") or not r.get("path"):
        return None, f"resolve_http_{r.get('status') or r.get('error')}"
    time.sleep(UA_GAP)
    try:
        payload = json.loads((ROOT / r["path"]).read_bytes().decode("utf-8", "replace"))
    except Exception:
        return None, "resolve_bad_json"
    best, best_score = None, -1
    target = core(name)
    for entry in payload.get("data") or []:
        if entry.get("type") != "hotel":
            continue
        word = entry.get("word") or ""
        m = re.search(r"appFilterValue=(\d+)", entry.get("url") or "")
        if not m or "西安" not in word:
            continue
        cand = core(word)
        if target == cand:
            score = 100
        elif target and (target in cand or cand in target):
            score = 60 + min(len(target), len(cand))
        else:
            continue
        if score > best_score:
            best, best_score = m.group(1), score
    if not best:
        return None, "no_name_match"
    return best, None


PRICE_RE = re.compile(r"(?:房價只需|最優惠房價由|最低房價由|房價每晚由|每晚只需|房價由)\s*CNY\s*([\d,]+)\s*起")
NAME_RE = re.compile(r'"@type":"Hotel","name":"([^"(（]+)')


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def parse_price(raw: bytes) -> tuple[int | None, str | None, str | None, str | None]:
    text = raw.decode("utf-8", "replace")
    nm = NAME_RE.search(text)
    zh_name = nm.group(1).strip() if nm else ""
    flat = strip_tags(text)
    for m in PRICE_RE.finditer(flat):
        price = int(m.group(1).replace(",", ""))
        quote = None
        if zh_name:
            k = flat.rfind(zh_name, max(0, m.start() - 320), m.start())
            if k >= 0:
                quote = re.sub(r"\s+", " ", flat[k:m.end()]).strip()
        if quote is None:
            continue
        return price, quote, zh_name, None
    m = re.search(r'"priceRange":"([^"]+)"', text)
    if not m:
        return None, None, zh_name, "no_price_in_page"
    price = int(re.sub(r"[^0-9]", "", m.group(1)) or 0) or None
    start = text.find('"@type":"Hotel","name":"')
    quote = None
    if start >= 0 and start < m.start() and m.start() - start < 700:
        quote = re.sub(r"\s+", " ", text[start + len('"@type":"Hotel","name":"'):m.end()]).strip()
    if not price or not quote:
        return None, None, zh_name, "has_priceRange_no_name"
    return price, quote, zh_name, "ldjson_fallback"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--reuse", action="store_true", help="reuse already-downloaded raw pages")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(ROOT / RUN / "targets/hotel_missing.csv", encoding="utf-8-sig")))
    rows = [r for r in rows if "price" in (r.get("missing") or "")]
    batch = rows[args.offset:args.offset + args.limit]

    raw_dir = ROOT / RUN / "raw/hotel"
    resolve_dir = raw_dir / "resolve"
    resolve_dir.mkdir(parents=True, exist_ok=True)
    (ROOT / RUN / "staging/hotel").mkdir(parents=True, exist_ok=True)

    items = []
    log = []
    for idx, row in enumerate(batch, 1):
        name = row["name"].strip()
        entry = {"name": name, "hotelId": None, "status": None}
        rj = ROOT / RUN / "raw/hotel/resolve" / (slug(name) + ".json")
        hid = None
        if args.reuse and rj.exists():
            try:
                payload = json.loads(rj.read_bytes().decode("utf-8", "replace"))
                target = core(name)
                best = None
                for e in payload.get("data") or []:
                    if e.get("type") != "hotel":
                        continue
                    m = re.search(r"appFilterValue=(\d+)", e.get("url") or "")
                    cand = core(e.get("word") or "")
                    if (m and target and "西安" in (e.get("word") or "")
                            and (target == cand or target in cand or cand in target)):
                        best = m.group(1)
                        break
                hid = best
            except Exception:
                hid = None
            err = None if hid else "no_name_match"
        else:
            hid, err = resolve(name, f"{RUN}/raw/hotel/resolve/{slug(name)}.json")
            time.sleep(UA_GAP)
        if not hid:
            entry["status"] = err
            log.append(entry)
            print(f"[{idx}/{len(batch)}] {name} -> {err}", flush=True)
            continue
        entry["hotelId"] = hid
        page = f"{RUN}/raw/hotel/{hid}.html"
        r = None
        if args.reuse and (ROOT / page).exists():
            r = {"ok": True, "path": page}
        else:
            r = call_fetch(f"https://hk.trip.com/hotels/xi-an-hotel-detail-{hid}/?locale=zh-CN&curr=CNY", page)
            time.sleep(UA_GAP)
        if not r.get("ok"):
            entry["status"] = f"detail_http_{r.get('status') or r.get('error')}"
            log.append(entry)
            print(f"[{idx}/{len(batch)}] {name} ({hid}) -> {entry['status']}", flush=True)
            continue
        raw_bytes = (ROOT / r["path"]).read_bytes()
        price, quote, zh_name, perr = parse_price(raw_bytes)
        if price and "西安" not in zh_name and '"addressRegion":"西安"' not in raw_bytes.decode("utf-8", "replace"):
            price, perr = None, "identity_not_xian"
        if not price:
            entry["status"] = perr
            log.append(entry)
            print(f"[{idx}/{len(batch)}] {name} ({hid}) -> {perr}", flush=True)
            continue
        item = {
            "kind": "accommodation",
            "name": name,
            "data": {"price": price},
            "source": {
                "url": f"https://hk.trip.com/hotels/xi-an-hotel-detail-{hid}/?locale=zh-CN&curr=CNY",
                "publisher": "Trip.com（携程集团）",
                "authority": "travel_marketplace_display",
                "licence_status": "public_page_reuse_unverified",
                "observed_at": "2026-11-09",
            },
            "evidence": {
                "raw_path": r["path"],
                "quote": quote,
                "locator": "seoRecommendation.h1Header",
                "identity_basis": f"携程 hotelId {hid} 同名解析；trip.com 同一 hotelId 详情页 JSON-LD name={zh_name}",
            },
            "notes": "挂牌起步价（未绑定具体入住日期/房型）；同页 JSON-LD priceRange 可能为另一缓存值",
        }
        items.append(item)
        entry["status"] = "ok"
        entry["price"] = price
        log.append(entry)
        print(f"[{idx}/{len(batch)}] {name} ({hid}) -> {price}", flush=True)

    if args.dry:
        print(json.dumps(items[:3], ensure_ascii=False, indent=1))
        return 0

    with open(ROOT / RUN / "staging/hotel/_run_log.jsonl", "a", encoding="utf-8") as fh:
        for e in log:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    with open(ROOT / RUN / "staging/hotel/items.jsonl", "a", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(json.dumps({"batch": len(batch), "items": len(items),
                      "blocked": len(batch) - len(items)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
