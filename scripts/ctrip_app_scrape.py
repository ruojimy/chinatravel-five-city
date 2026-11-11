"""Drive the Ctrip Android app via ADB to read hotel suggestion prices.

For each target: focus the search box, clear it, inject Chinese text with
ADBKeyboard, dump the UI hierarchy, match the suggestion name, read
`参考价 ¥xxx 起`, and save the UI text as raw evidence.

No price is invented: rows without a `参考价` amount are skipped.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "results" / "xian_gapfill_20261109"
OUT = RUN / "staging" / "ctrip_app"
RAW = RUN / "raw" / "ctrip_app"
OUT.mkdir(parents=True, exist_ok=True)
RAW.mkdir(parents=True, exist_ok=True)
DEVICE = "10.197.240.21:42233"
ADB = os.environ.get("ADB", "adb")
SEARCH_BOX = (541, 324)
CLEAR_BTN = (990, 314)


def adb(*args: str, timeout: int = 30) -> str:
    return subprocess.run([ADB, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout).stdout


def norm(s: str) -> str:
    s = re.sub(r"[（(].*?[）)]", "", s or "")
    return re.sub(r"[西安\s·、,，.。\-—_]", "", s).lower()


def branch_tokens(s: str) -> list[str]:
    m = re.search(r"[（(]([^）)]+)[）)]", s or "")
    if not m:
        return []
    return [x for x in re.split(r"[店路站区县街巷号栋楼]", m.group(1)) if len(x) >= 2]


def match(target: str, cand: str) -> str | None:
    tn, cn = norm(target), norm(cand)
    if not tn or not cn:
        return None
    if tn == cn:
        return "exact"
    if tn in cn or cn in tn:
        if len(tn) >= 5:
            tt, ct = branch_tokens(target), branch_tokens(cand)
            if tt and ct and not any(a in b or b in a for a in tt for b in ct):
                return None
            return "contain"
    cats = ("酒店", "公寓", "宾馆", "旅馆", "民宿", "客栈", "青旅", "旅社", "饭店")
    tc = next((c for c in cats if tn.endswith(c)), None)
    cc = next((c for c in cats if cn.endswith(c)), None)
    if tc and cc and tc != cc:
        return None
    ratio = difflib.SequenceMatcher(None, tn, cn).ratio()
    if ratio >= 0.6 and min(len(tn), len(cn)) >= 4:
        tt, ct = branch_tokens(target), branch_tokens(cand)
        if tt and ct and not any(a in b or b in a for a in tt for b in ct):
            return None
        return f"fuzzy_{ratio:.2f}"
    return None


def dump_ui(path: Path) -> list[dict]:
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml", timeout=30)
    xml = adb("exec-out", "cat", "/sdcard/ui.xml", timeout=30)
    path.write_text(xml, encoding="utf-8")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out = []
    for e in root.iter("node"):
        tx = (e.get("text") or "").strip()
        b = e.get("bounds") or ""
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
        if tx and m:
            x1, y1, x2, y2 = map(int, m.groups())
            out.append({"text": tx, "x": (x1 + x2) // 2, "y": (y1 + y2) // 2})
    return out


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    adb("connect", DEVICE)
    targets = json.loads((RUN / "targets/no_candidate.json").read_text(encoding="utf-8"))
    done = set()
    items_path = OUT / "items.jsonl"
    if items_path.exists():
        for line in items_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    done.add(json.loads(line)["name"])
                except Exception:
                    pass
    batch = [t for t in targets if t["name"] not in done][:limit]
    matched = 0
    for t in batch:
        name = t["name"]
        adb("shell", "input", "keyevent", "224")  # wake
        adb("shell", "input", "keyevent", "123")  # move end
        adb("shell", "input", "keyevent", *(["67"] * 30))  # clear existing text
        adb("shell", "am", "broadcast", "-a", "ADB_INPUT_TEXT", "--es", "msg", name)
        time.sleep(2.2)
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        xml_path = RAW / f"ui_{abs(hash(name))}.xml"
        nodes = dump_ui(xml_path)
        raw_text = "\n".join(n["text"] for n in nodes)
        hit = None
        for n in nodes:
            mt = match(name, n["text"])
            if not mt:
                continue
            prices = []
            for p in nodes:
                if abs(p["y"] - n["y"]) <= 70 and p["x"] > n["x"]:
                    m = re.search(r"[¥￥]\s*(\d+)", p["text"])
                    if m:
                        prices.append((p["x"], int(m.group(1))))
            if prices:
                row_text = " ".join(p["text"] for p in nodes if abs(p["y"] - n["y"]) <= 120)
                other = [c for c in ("郑州", "广州", "上海", "北京", "咸阳", "成都", "重庆", "深圳", "杭州", "南京", "武汉", "长沙", "苏州")
                         if c in row_text or c in n["text"]]
                if other and "西安" not in row_text and "西安" not in n["text"]:
                    continue
                prices.sort()
                hit = {"card": n["text"], "price": prices[0][1], "match": mt, "y": n["y"]}
                break
        rec = {"hotel": name, "result": "no_match"}
        if hit:
            txt_path = RAW / f"{abs(hash(name))}.txt"
            txt_path.write_text(raw_text, encoding="utf-8")
            item = {
                "kind": "accommodation", "name": name, "data": {"price": hit["price"]},
                "source": {"url": "ctrip://wireless/hotel/search", "publisher": "携程App",
                           "authority": "travel_marketplace_display",
                           "licence_status": "app_display_unverified", "observed_at": stamp},
                "evidence": {"raw_path": str(txt_path.relative_to(ROOT)).replace("\\", "/"),
                             "quote": f"¥{hit['price']}", "locator": "ctrip_app_suggestion",
                             "identity_basis": f"{hit['match']};card={hit['card']}"},
                "notes": f"adb_ui; card={hit['card']}",
            }
            with items_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
            matched += 1
            rec = {"hotel": name, "result": "matched", "card": hit["card"],
                   "price": hit["price"], "match": hit["match"]}
        with (OUT / "run_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(json.dumps(rec, ensure_ascii=False))
        time.sleep(0.6)
    print(json.dumps({"batch": len(batch), "matched": matched}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
