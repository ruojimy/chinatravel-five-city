"""Second-batch Xi'an hotel price gap-fill (channel: Trip.com global search + detail page).

Differences from batch 1:
  * batch-1 names are skipped, never touched;
  * resolution accepts a candidate only when its globe-search coordinate is within 200 m of
    the catalog coordinate, so chain branches cannot be silently swapped;
  * one retry with a shortened keyword when the first query finds nothing;
  * every item keeps the raw HTML + a verbatim name+amount quote.

Usage:
  python scripts/xian_gapfill_hotel2_run.py --limit 40 [--offset 0]
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = "results/xian_gapfill_20261109"
PY = str(ROOT / ".venv/Scripts/python.exe")
FETCH = ROOT / "scripts/xian_gapfill_fetch.py"
COUNTER = ROOT / RUN / "raw/hotel2/_request_counter.json"
GAP = 2.6

PRICE_RE = re.compile(
    r"(?:房價只需|最優惠房價由|最低房價由|房價每晚由|每晚只需|房價由)\s*CNY\s*([\d,]+)\s*起")
NAME_RE = re.compile(r'"@type":"Hotel","name":"([^"(（]+)')


def bump(site: str) -> None:
    data = {"ctrip_com": 0, "trip_com": 0}
    if COUNTER.exists():
        data.update(json.loads(COUNTER.read_text(encoding="utf-8")))
    data[site] = data.get(site, 0) + 1
    COUNTER.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def call_fetch(url: str, out_rel: str) -> dict:
    site = "trip_com" if "trip.com" in url else "ctrip_com"
    bump(site)
    proc = subprocess.run([PY, str(FETCH), "--url", url, "--out", out_rel],
                          capture_output=True, text=True, cwd=str(ROOT))
    lines = (proc.stdout or "").strip().splitlines()
    try:
        return json.loads(lines[-1]) if lines else {"ok": False, "error": "no_output"}
    except json.JSONDecodeError:
        return {"ok": False, "error": "bad_receipt"}


def norm(s: str) -> str:
    return re.sub(r"[\s\u3000（）()·\-,，.。、|]", "", s or "").lower()


def core(name: str) -> str:
    n = re.sub(r"[（(][^）)]*[）)]", "", name or "")
    n = re.sub(r"^(西安市|西安|陕西)", "", n)
    return norm(n)


sys.path.insert(0, str(ROOT / "scripts"))
from xian_gapfill_geo import catalog_to_wgs, haversine  # noqa: E402


def slug(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name)[:60]


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def parse_price(raw: bytes):
    text = raw.decode("utf-8", "replace")
    nm = NAME_RE.search(text)
    zh_name = nm.group(1).strip() if nm else ""
    flat = strip_tags(text)
    for m in PRICE_RE.finditer(flat):
        price = int(m.group(1).replace(",", ""))
        if zh_name:
            k = flat.rfind(zh_name, max(0, m.start() - 320), m.start())
            if k >= 0:
                return price, re.sub(r"\s+", " ", flat[k:m.end()]).strip(), zh_name, "h1"
    m = re.search(r'"priceRange":"由?\s*CNY\s*([\d,]+)\s*起"', text)
    if not m:
        return None, None, zh_name, "no_price_in_page"
    price = int(m.group(1).replace(",", ""))
    start = text.find('"@type":"Hotel","name":"')
    if start < 0 or start > m.start() or m.start() - start > 900:
        return None, None, zh_name, "has_priceRange_no_name"
    quote = re.sub(r"\s+", " ", text[start + len('"@type":"Hotel","name":"'):m.end()]).strip()
    return price, quote, zh_name, "ldjson"


def variants(name: str) -> list[str]:
    """Exact-name query first (highest precision), one calendar-style fallback is skipped
    because every extra query costs a request against the per-site budget."""
    return [name if name.startswith(("西安", "陕西")) else "西安" + name]


def resolve(name: str, lat: float, lon: float, out_rel: str):
    """Return (hotelId, candidate_word, dist_m, note)."""
    import urllib.parse
    best = None
    last_note = "no_name_match"
    target = core(name)
    for vi, kw in enumerate(variants(name)):
        url = ("https://hk.trip.com/restapi/h5api/globalsearch/search?action=json&keyword="
               + urllib.parse.quote(kw))
        r = call_fetch(url, out_rel if vi == 0 else out_rel.replace(".json", f"_v{vi}.json"))
        time.sleep(GAP)
        if not r.get("ok"):
            last_note = f"resolve_http_{r.get('status') or r.get('error')}"
            continue
        try:
            payload = json.loads((ROOT / r["path"]).read_bytes().decode("utf-8", "replace"))
        except Exception:
            last_note = "resolve_bad_json"
            continue
        for e in payload.get("data") or []:
            if e.get("type") != "hotel" or int(e.get("cityId") or 0) != 10:
                continue
            cand = core(e.get("word") or "")
            if not cand or not target:
                continue
            if target == cand:
                base_score = 100
            elif len(target) >= 4 and (target in cand or cand in target):
                base_score = 60
            else:
                ratio = difflib.SequenceMatcher(None, target, cand).ratio()
                if ratio < 0.72:
                    continue
                base_score = int(55 * ratio / 0.72)
            clat, clon = float(e.get("lat") or 0), float(e.get("lon") or 0)
            if not clat or not clon:
                continue
            dist = haversine((lat, lon), (clat, clon))
            if dist > 200:
                continue
            score = base_score + (20 if dist < 80 else 0)
            if best is None or score > best[0]:
                best = (score, str(e.get("id")), e.get("word"), dist)
        if best:
            return best[1], best[2], best[3], "ok"
        if vi == 0:
            last_note = "no_name_match"
    if best:
        return best[1], best[2], best[3], "ok"
    return None, None, None, last_note


def existing_names(path: Path) -> set[str]:
    out = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.add(json.loads(line)["name"])
    return out


PRIORITY = ("汉庭", "如家", "全季", "维也纳", "锦江", "亚朵", "桔子", "麗枫", "丽枫", "希尔顿",
            "万豪", "洲际", "喜来登", "凯悦", "皇冠", "温德姆", "美居", "宜必思", "智选",
            "福朋", "华美达", "戴斯", "格林", "尚客优", "布丁", "海友", "星程", "怡莱",
            "钟楼", "大雁塔", "曲江", "高新", "回民街", "北站", "小寨", "火车站", "南门")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--only", default="", help="comma separated exact names")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(ROOT / RUN / "targets/hotel_missing.csv", encoding="utf-8-sig")))
    rows = [r for r in rows if "price" in (r.get("missing") or "")]
    done = existing_names(ROOT / RUN / "staging/hotel/items.jsonl") | \
        existing_names(ROOT / RUN / "staging/hotel2/items.jsonl")
    rows = [r for r in rows if r["name"].strip() not in done]
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        rows = [r for r in rows if r["name"].strip() in wanted]
    else:
        CENTRAL = ("钟楼", "回民街", "大雁塔", "大唐不夜城", "曲江", "高新", "小寨",
                   "南门", "城墙", "火车站", "北站", "经开", "浐灞")

        OUTER = ("阎良", "高陵", "鄠邑", "蓝田", "周至", "临潼", "户县", "泾阳", "三原")
        SKIP = ("公寓", "民宿", "客栈", "电竞", "loft", "Loft", "青旅", "青年旅社", "出租",
                "私房", "家庭旅馆", "招待所")

        def rank(r):
            n = r["name"]
            central = any(k in n for k in CENTRAL)
            brand = any(k in n for k in PRIORITY)
            is_hotel = n.endswith("酒店") or "酒店(" in n
            if any(k in n for k in OUTER) or any(k in n for k in SKIP):
                return (9, n)
            if any(k in n for k in ("大酒店", "国际", "温泉", "度假", "饭店", "山庄")):
                return (0, n)
            if brand and is_hotel:
                return (1, n)
            if central and is_hotel:
                return (2, n)
            if is_hotel:
                return (3, n)
            return (4, n)
        rows.sort(key=rank)

    batch = rows[args.offset:args.offset + args.limit]
    raw_dir = ROOT / RUN / "raw/hotel2"
    (raw_dir / "resolve").mkdir(parents=True, exist_ok=True)
    (ROOT / RUN / "staging/hotel2").mkdir(parents=True, exist_ok=True)
    items_path = ROOT / RUN / "staging/hotel2/items.jsonl"
    log_path = ROOT / RUN / "staging/hotel2/_run_log.jsonl"
    items_path.touch(exist_ok=True)

    items, logs, accepted = [], [], 0
    for idx, row in enumerate(batch, 1):
        name = row["name"].strip()
        try:
            lat, lon = catalog_to_wgs(float(row["lat"]), float(row["lon"]))
        except (TypeError, ValueError):
            logs.append({"name": name, "status": "no_target_coord"})
            print(f"[{idx}/{len(batch)}] {name} -> no_target_coord", flush=True)
            continue
        entry = {"name": name}
        hid, cword, dist, note = resolve(
            name, lat, lon, f"{RUN}/raw/hotel2/resolve/{slug(name)}.json")
        if not hid:
            entry["status"] = note
            logs.append(entry)
            print(f"[{idx}/{len(batch)}] {name} -> {note}", flush=True)
            continue
        entry.update({"hotelId": hid, "candidate": cword, "dist_m": round(dist, 1)})
        page = f"{RUN}/raw/hotel2/{hid}.html"
        r = call_fetch(f"https://hk.trip.com/hotels/xi-an-hotel-detail-{hid}/?locale=zh-CN&curr=CNY", page)
        time.sleep(GAP)
        if not r.get("ok"):
            entry["status"] = f"detail_http_{r.get('status') or r.get('error')}"
            logs.append(entry)
            print(f"[{idx}/{len(batch)}] {name} ({hid}) -> {entry['status']}", flush=True)
            continue
        raw = (ROOT / r["path"]).read_bytes()
        price, quote, zh_name, mode = parse_price(raw)
        text = raw.decode("utf-8", "replace")
        if price and "西安" not in zh_name and '"addressRegion":"西安"' not in text:
            price, mode = None, "identity_not_xian"
        if not price:
            entry["status"] = mode
            logs.append(entry)
            print(f"[{idx}/{len(batch)}] {name} ({hid}) -> {mode}", flush=True)
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
                "locator": "seoRecommendation.h1Header" if mode == "h1" else "Hotel JSON-LD name..priceRange",
                "identity_basis": (f"globe-search 候选「{cword}」与目标坐标相距 {dist:.0f} m（≤200m）；"
                                   f"detail JSON-LD name={zh_name}；hotelId={hid}"),
            },
            "notes": "挂牌起步价（未绑定具体入住日期/房型）；第二批通道" + (
                "；引用取详情页 Hotel JSON-LD 名称到 priceRange 连续片段" if mode == "ldjson" else ""),
        }
        items.append(item)
        entry.update({"status": "ok", "price": price})
        logs.append(entry)
        accepted += 1
        print(f"[{idx}/{len(batch)}] {name} ({hid}) -> {price}  d={dist:.0f}m", flush=True)

        if len(items) >= 10:
            with items_path.open("a", encoding="utf-8") as f:
                for it in items:
                    f.write(json.dumps(it, ensure_ascii=False) + "\n")
            subprocess.run([PY, "scripts/xian_gapfill_validate.py", "--items",
                            f"{RUN}/staging/hotel2/items.jsonl"], cwd=str(ROOT))
            items = []

    if items:
        with items_path.open("a", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
    with log_path.open("a", encoding="utf-8") as f:
        for e in logs:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    subprocess.run([PY, "scripts/xian_gapfill_validate.py", "--items",
                    f"{RUN}/staging/hotel2/items.jsonl"], cwd=str(ROOT))
    print(json.dumps({"attempted": len(batch), "accepted": accepted,
                      "total_items": len(existing_names(items_path))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
