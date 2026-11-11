"""Normalise airport and railway-station naming in the transport layer.

Flights in this dataset mix three naming conventions for the same airport
("西安咸阳国际机场" / "Xianyang Airport (Xi'an, Shaanxi) XIY" / "XIY"), which
splits one node into several and breaks route matching.

This script maps every endpoint to its IATA code, keeps the original string for
audit, and writes a display name. Train stations are only audited, not rewritten
unless --fix-stations is passed (they are already consistent except for the
optional 站 suffix).
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLIGHTS = ROOT / "data/xian11_sandbox/intercity_transport/airplane.jsonl"
ALIASES = ROOT / "data/airport_aliases.json"
TRAINS = ROOT / "data/xian11_sandbox/intercity_transport/train"

CN_TO_CODE = {
    "西安咸阳国际机场": "XIY", "上海浦东国际机场": "PVG", "上海虹桥国际机场": "SHA",
    "北京大兴国际机场": "PKX", "北京首都国际机场": "PEK", "深圳宝安国际机场": "SZX",
    "广州白云国际机场": "CAN", "重庆江北国际机场": "CKG", "武汉天河国际机场": "WUH",
    "成都天府国际机场": "TFU", "成都双流国际机场": "CTU", "青岛胶东国际机场": "TAO",
    "揭阳潮汕机场": "SWA", "南京禄口国际机场": "NKG", "杭州萧山国际机场": "HGH",
    "厦门高崎国际机场": "XMN",
    # city-only names: single-airport cities resolve to that airport
    "深圳": "SZX", "沈阳": "SHE", "清迈": "CNX", "宁波": "NGB", "南昌": "KHN",
    "喀什": "KHG", "乌鲁木齐": "URC", "伊宁": "YIN", "曼谷": "BKK", "金边机场": "PNH",
    # 上海 has both PVG and SHA in this dataset -> keep it as a city-level node
    "上海": "SHA-CITY",
}

CODE_RE = re.compile(r"\b([A-Z]{3})\b")


def to_code(raw: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    if s in CN_TO_CODE:
        return CN_TO_CODE[s]
    m = CODE_RE.search(s)
    if m:
        return m.group(1)
    return None


def has_cn(s: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", s or ""))


def build_aliases(rows: list[dict]) -> dict:
    alias: dict[str, dict] = {}
    names: dict[str, str] = {}
    for row in rows:
        for field in ("From", "To"):
            raw = row.get(field)
            code = to_code(raw)
            if not code:
                continue
            alias[raw] = {"code": code}
            if has_cn(raw) and "(" not in raw:
                names.setdefault(code, raw)
    for raw, meta in alias.items():
        meta["name"] = names.get(meta["code"], raw)
    return alias


def normalise_flights(path: Path, aliases: dict) -> dict:
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    out, unmapped = [], []
    for row in rows:
        rec = dict(row)
        cf, ct = to_code(rec.get("From")), to_code(rec.get("To"))
        if not cf or not ct:
            unmapped.append({"From": rec.get("From"), "To": rec.get("To")})
            continue
        rec["FromRaw"], rec["ToRaw"] = rec.get("From"), rec.get("To")
        rec["From"], rec["To"] = cf, ct
        rec["FromName"] = aliases.get(rec["FromRaw"], {}).get("name", rec["FromRaw"])
        rec["ToName"] = aliases.get(rec["ToRaw"], {}).get("name", rec["ToRaw"])
        out.append(rec)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n", encoding="utf-8")
    return {"rows": len(rows), "written": len(out), "unmapped": unmapped}


def audit_stations(folder: Path) -> dict:
    names = Counter()
    for f in folder.glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        items = d if isinstance(d, list) else (d.get("trains") or [])
        for t in items:
            for k in ("From", "To"):
                names[t.get(k)] += 1
    groups = defaultdict(list)
    for n in names:
        base = re.sub(r"站$", "", n or "")
        groups[base].append(n)
    variants = {k: v for k, v in groups.items() if len(v) > 1}
    return {"distinct": len(names), "variant_groups": variants,
            "top": names.most_common(8)}


def canonical_station(name: str) -> str:
    return re.sub(r"站$", "", (name or "").strip())


def normalize_stations(folder: Path) -> dict:
    changed = rewritten = 0
    for f in sorted(folder.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else (data.get("trains") or [])
        touched = False
        for t in items:
            for key in ("From", "To"):
                raw = t.get(key)
                canon = canonical_station(raw)
                if not canon:
                    t[key + "Raw"] = raw
                    t[key] = "UNKNOWN"
                    t[key + "Gap"] = True
                    touched = True
                elif canon != raw:
                    t[key + "Raw"] = raw
                    t[key] = canon
                    touched = True
            for key in ("From", "To"):
                if not t.get(key + "Name"):
                    t[key + "Name"] = t.get(key + "Raw") or t.get(key)
        if touched:
            if isinstance(data, list):
                payload = items
            else:
                data["trains"] = items
                payload = data
            f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            rewritten += 1
            changed += sum(1 for t in items if t.get("FromRaw") or t.get("ToRaw"))
    return {"files_rewritten": rewritten, "rows_touched": changed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flights", default=str(FLIGHTS))
    ap.add_argument("--train-dir", default=str(TRAINS))
    ap.add_argument("--fix-stations", action="store_true")
    args = ap.parse_args()
    path = Path(args.flights)

    raw = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    aliases = build_aliases(raw)
    before_pairs = len({(r.get("From"), r.get("To")) for r in raw})
    before_nodes = len({x for r in raw for x in (r.get("From"), r.get("To"))})

    stats = normalise_flights(path, aliases)
    fixed = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    after_pairs = len({(r["From"], r["To"]) for r in fixed})
    after_nodes = len({x for r in fixed for x in (r["From"], r["To"])})
    self_loops = [r for r in fixed if r["From"] == r["To"]]

    ALIASES.write_text(json.dumps({"generated_for": "data/xian11_sandbox/intercity_transport/airplane.jsonl",
                                   "aliases": aliases}, ensure_ascii=False, indent=1), encoding="utf-8")

    station_fix = normalize_stations(Path(args.train_dir)) if args.fix_stations else None
    print(json.dumps({
        "flights": stats,
        "station_fix": station_fix,
        "nodes_before": before_nodes, "nodes_after": after_nodes,
        "pairs_before": before_pairs, "pairs_after": after_pairs,
        "self_loops": len(self_loops),
        "unmapped": stats["unmapped"][:5],
        "stations": audit_stations(Path(args.train_dir)),
        "aliases_file": str(ALIASES.relative_to(ROOT)).replace("\\", "/"),
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
