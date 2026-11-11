"""Ctrip public sight pages (no login): enrich opentime/endtime from verbatim HTML.

Flow: fetch the Xi'an sight list page -> parse sight detail URLs -> fetch each
detail page -> take the single HH:MM-HH:MM interval attached to 开放 -> emit an
--enrich jsonl for xian_ingest.py. Only exact-name matches with the record name
verbatim in the raw HTML are emitted. No login, no private API, low rate.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CITY = "西安"
LIST_URL = "https://you.ctrip.com/sight/lushan7.html"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36"
LINK_RE = re.compile(r'href="([^"]*/sight/[^"]*?\.html[^"]*)"')
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
HOURS_RE = re.compile(r"(\d{2}:\d{2})-(\d{2}:\d{2})")
NAME_RE = re.compile(r"[^|｜\-—_【】\[\]（）()\s]{2,30}")


def now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").replace("（", "(").replace("）", ")")).lower()


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read(4 * 1024 * 1024)


def plain(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", text)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args()

    run_dir = Path(args.run)
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    raw_dir = run_dir / "raw_ctrip"
    out_dir = run_dir / "staging" / "ctrip"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    snapshot = Path(args.snapshot)
    if not snapshot.is_absolute():
        snapshot = ROOT / snapshot
    conn = sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True)
    records = {}
    for name, payload in conn.execute(
            f"select name, payload from records where city='{CITY}' and kind='attraction'"):
        data = (json.loads(payload).get("data") or {})
        if any(data.get(k) in (None, "") for k in ("opentime", "endtime")):
            records[norm(name)] = (name, data)
    conn.close()

    list_html = get(LIST_URL).decode("utf-8", errors="replace")
    (raw_dir / "list_xian.html").write_text(list_html, encoding="utf-8")
    def collect_urls(page_html):
        out = []
        for u in LINK_RE.findall(page_html):
            u = html.unescape(u).split("?")[0]
            if u.startswith("/"):
                u = "https://you.ctrip.com" + u
            if re.search(r"s0-p\d+\.html", u) or u.endswith("/0.html"):
                continue  # 分页壳与无效 ID
            if "/sight/" in u and re.search(r"/\d+\.html$", u):
                out.append(u)
        return out

    urls = collect_urls(list_html)
    # 多抓几页列表，拿到更多景点详情链接
    for page_no in (1, 2, 3):
        try:
            more = get(f"https://you.ctrip.com/sight/lushan7/s0-p{page_no}.html")
            urls += collect_urls(more.decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            pass
        time.sleep(max(args.sleep, 0.8))
    urls = list(dict.fromkeys(urls))
    print("list_links", len(urls), "pending_records", len(records))

    items, log = [], []
    for index, url in enumerate(urls[:args.max_pages]):
        try:
            raw = get(url)
        except Exception as exc:  # noqa: BLE001
            log.append({"url": url, "ok": False, "reason": "fetch_failed:" + type(exc).__name__})
            continue
        text = raw.decode("utf-8", errors="replace")
        title_match = TITLE_RE.search(text)
        title = plain(title_match.group(1)) if title_match else ""
        # 页面标题通常形如「西安城墙(5A景区)攻略...」；取第一个干净片段做候选名
        # 标题形如「西安<景点名>游玩攻略简介,...」，城市名前缀后即为景点名
        title_name = re.search(r"西安(.+?)游玩攻略简介", title)
        candidates = [title_name.group(1).strip()] if title_name else []
        if not candidates:
            # gs.ctrip.com 等页面标题形如「大雁塔 携程攻略」
            short = re.split(r"游玩攻略|携程攻略|【|\||,|，", title)[0].strip()
            short = re.sub(r"^西安", "", short).strip()
            if short:
                candidates.append(short)
        flat = plain(text)
        # 优先取「开放时间/明天…开放」附近区间，否则取全文第一个
        anchor = re.search(r"(?:开放时间|开园|明天\s*)", flat)
        window = flat[anchor.start():anchor.start() + 160] if anchor else flat[:600]
        hours_match = HOURS_RE.search(window) or HOURS_RE.search(flat)
        hit = None
        for cand in candidates + NAME_RE.findall(title)[:3]:
            key = norm(cand)
            if not key or len(key) < 2:
                continue
            if key in records:
                hit = records[key]
                break
            near = [v for k, v in records.items()
                    if (k in key or key in k) and abs(len(k) - len(key)) <= 3]
            if len(near) == 1:
                hit = near[0]
                break
        if not hit:
            log.append({"url": url, "ok": False, "reason": "no_exact_name_match",
                        "title": title[:60]})
        elif not hours_match:
            log.append({"url": url, "ok": False, "reason": "no_open_interval",
                        "title": title[:60]})
        elif hit[0] not in text:
            log.append({"url": url, "ok": False, "reason": "name_not_verbatim_in_raw",
                        "name": hit[0]})
        else:
            start, end = hours_match.group(1), hours_match.group(2)
            if int(start[:2]) >= 24 or int(end[:2]) >= 24:
                log.append({"url": url, "ok": False, "reason": "invalid_clock"})
            else:
                file = raw_dir / f"ctrip_sight_{index:03d}.html"
                file.write_bytes(raw)
                rel = str(file.relative_to(ROOT)).replace("\\", "/")
                items.append({
                    "kind": "attraction", "name": hit[0], "aliases": [],
                    "data": {"opentime": start, "endtime": end},
                    "source": {
                        "url": url, "publisher": "携程攻略（公开页）",
                        "authority": "public_travel_guide",
                        "licence_status": "public_web_page_pending_review",
                        "trust_status": "reference_only",
                        "published_at": None, "observed_at": None,
                    },
                    "evidence": {"raw_path": rel, "quote": hit[0],
                                 "locator": f"页面营业时段 {start}-{end}开放"},
                    "notes": "携程公开详情页免登录；仅取与「开放」直接相连的单一区间，未估算门票/价格",
                })
                log.append({"url": url, "ok": True, "name": hit[0],
                            "hours": f"{start}-{end}", "raw_path": rel})
        time.sleep(max(args.sleep, 0.8))

    out = out_dir / "enrich_ctrip.jsonl"
    out.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n",
                   encoding="utf-8")
    (out_dir / "api_log.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in log) + "\n", encoding="utf-8")
    print(json.dumps({"pages": min(len(urls), args.max_pages), "matches": len(items),
                      "out": str(out.relative_to(ROOT)).replace("\\", "/"),
                      "checked_at": now_iso()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
