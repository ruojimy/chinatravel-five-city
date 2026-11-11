"""Which channel actually fills each field? (v17 Xi'an provenance + this round)

Reads per-field `field_provenance` from the v17 snapshot and maps source URLs
to channels; prints coverage and channel shares for attraction / restaurant /
accommodation. Also summarizes this round's probe success rates.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "results/xian_gapfill_20261109/snapshot_v17/catalog.sqlite3"
OUT = ROOT / "results/field_source_efficiency_20261111.json"


def channel(source_url: str, source_id: str = "") -> str:
    text = f"{source_url or ''} {source_id or ''}".lower()
    if "amap.com" in text:
        return "高德"
    if "baidu.com" in text:
        return "百度"
    if "trip.com" in text or "ctrip.com" in text:
        return "Trip.com"
    if "meituan.com" in text or "dianping.com" in text:
        return "美团/点评"
    if "openstreetmap" in text or "nominatim" in text:
        return "OSM"
    if "wikidata" in text:
        return "Wikidata"
    if "visitxian" in text or ".gov.cn" in text:
        return "官方/文旅"
    if "12306" in text:
        return "12306"
    if "qunar" in text:
        return "去哪儿"
    if text.startswith("chinatravel_sandbox") or "chinatravel" in text:
        return "官方沙盒"
    if "p30-local" in text or "urn:shorttrip" in text:
        return "本地代理/派生"
    return "其他"


def main() -> int:
    con = sqlite3.connect(f"file:{SNAP.as_posix()}?mode=ro", uri=True)
    report = {}
    for kind in ("attraction", "restaurant", "accommodation"):
        rows = [json.loads(pl) for (pl,) in con.execute(
            "select payload from records where kind=? and city='西安'", (kind,))]
        fields = Counter()
        chan = defaultdict(Counter)
        status = defaultdict(Counter)
        for d in rows:
            fp = d.get("field_provenance") or {}
            for f, v in (d.get("data") or {}).items():
                if v in (None, "", "UNKNOWN", "-1", [], {}):
                    continue
                fields[f] += 1
                p = fp.get(f) or {}
                if isinstance(p, list):
                    p = next((x for x in p if isinstance(x, dict)), {})
                if not isinstance(p, dict):
                    p = {}
                chan[f][channel(str(p.get("source_url") or ""), str(p.get("source_id") or ""))] += 1
                status[f][p.get("status") or "unknown"] += 1
        print(f"\n== {kind} ({len(rows)} records) ==")
        print(f"{'field':<18}{'present':>8}  top channels")
        for f, n in fields.most_common():
            top = ", ".join(f"{c}:{v}" for c, v in chan[f].most_common(3))
            st = ", ".join(f"{s}:{v}" for s, v in status[f].most_common(2))
            print(f"  {f:<16}{n:>6}  {top} | {st}")
        report[kind] = {
            "records": len(rows),
            "fields": {f: {"present": n, "channels": dict(chan[f]), "status": dict(status[f])}
                       for f, n in fields.items()},
        }
    con.close()
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
