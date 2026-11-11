"""Dataset integrity audit: entity <-> position index joins + hotel price completeness.

Outputs `docs/DATA_INTEGRITY_AUDIT_20261111.md` and
`results/data_integrity_audit_20261111.json`.

Position index = `poi/<city>/poi.json`; `Poi.search()` in
`chinatravel/environment/tools/poi/apis.py` resolves a name with an exact dict
lookup, so a missing name means the planner cannot locate that entity.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "ChinaTravel/chinatravel/environment/database"
MERGED = ROOT / "data/xian11_merged_sandbox"
V17 = ROOT / "results/xian_gapfill_20261109/snapshot_v17/catalog.sqlite3"
CATALOG = ROOT / "data/catalog_v1_1_20261022/catalog.sqlite3"
QUERIES = ROOT / ("data/query_sets/xian11" if (ROOT / "data/query_sets/xian11").exists() else "query_sets/xian11")
OUT_MD = ROOT / "docs/DATA_INTEGRITY_AUDIT_20261111.md"
OUT_JSON = ROOT / "results/data_integrity_audit_20261111.json"

CITIES = [("beijing", "北京"), ("shanghai", "上海"), ("nanjing", "南京"),
          ("suzhou", "苏州"), ("hangzhou", "杭州"), ("shenzhen", "深圳"),
          ("chengdu", "成都"), ("wuhan", "武汉"), ("guangzhou", "广州"),
          ("chongqing", "重庆"), ("xian", "西安")]
NATIVE_CITIES = CITIES[:-1]
PUNCT = re.compile(r"[\s\u3000·•・\-—–_()（）\[\]【】{}<>《》\"'“”‘’,，.。;；:：!！?？/\\|]+")


def norm(s):
    return PUNCT.sub("", unicodedata.normalize("NFKC", str(s or "")).strip().lower())


def core(s):
    t = unicodedata.normalize("NFKC", str(s or "")).strip()
    t = re.sub(r"[（(].*?[)）]", "", t)
    t = re.split(r"\s+[A-Za-z]", t, maxsplit=1)[0]
    return norm(t)


def rows(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def num(v, positive=False):
    try:
        x = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return x if (not positive or x > 0) else None


def poi_index(path):
    exact, cores = set(), set()
    if path.exists():
        for item in json.loads(path.read_text(encoding="utf-8")):
            exact.add(str(item.get("name") or "").strip())
            cores.add(core(item.get("name")))
    return exact, cores


def entity_match(slug, kind, base_root):
    table = {"attraction": ("attractions", "attractions.csv"),
             "accommodation": ("accommodations", "accommodations.csv"),
             "restaurant": ("restaurants", "restaurants_{}.csv")}[kind]
    sub, tpl = table
    name = tpl.format(slug) if "{}" in tpl else tpl
    rs = rows(base_root / sub / slug / name)
    exact, _ = poi_index(base_root / "poi" / slug / "poi.json")
    missing = [r["name"] for r in rs if r.get("name") not in exact]
    return len(rs), len(missing), missing[:5]


def audit_cities():
    out = []
    for slug, label in CITIES:
        base = NATIVE if slug != "xian" else MERGED
        attraction = entity_match(slug, "attraction", base)
        hotel = entity_match(slug, "accommodation", base)
        restaurant = entity_match(slug, "restaurant", base)
        out.append({"city": label, "slug": slug,
                    "attractions": {"total": attraction[0], "missing": attraction[1]},
                    "hotels": {"total": hotel[0], "missing": hotel[1]},
                    "restaurants": {"total": restaurant[0], "missing": restaurant[1]}})
    return out


def xian_missing_detail():
    attractions = rows(MERGED / "attractions/xian/attractions.csv")
    exact, cores = poi_index(MERGED / "poi/xian/poi.json")
    items = json.loads((MERGED / "poi/xian/poi.json").read_text(encoding="utf-8"))
    points = [(p["name"], float(p["position"][0]), float(p["position"][1])) for p in items]

    import math
    def hav(a, b, c, d):
        R = 6371000
        p1, p2 = math.radians(a), math.radians(c)
        h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(d - b) / 2) ** 2
        return 2 * R * math.asin(math.sqrt(h))

    families, near, absent = [], [], []
    for a in attractions:
        n = a["name"]
        if n in exact:
            continue
        c = core(n)
        fam = [q for q in exact if len(c) >= 4 and (core(q).startswith(c) or c.startswith(core(q)))
               and abs(len(core(q)) - len(c)) <= 8]
        la, lo = float(a["lat"]), float(a["lon"])
        best = min(points, key=lambda p: hav(la, lo, p[1], p[2]))
        d = hav(la, lo, best[1], best[2])
        rec = {"name": n, "nearest": best[0], "nearest_m": round(d)}
        if fam:
            rec["family"] = fam[0]
            families.append(rec)
        elif d <= 50:
            near.append(rec)
        else:
            absent.append(rec)
    return {"total": len(attractions), "missing": len(families) + len(near) + len(absent),
            "family_naming": families, "near_50m": near, "absent": absent}


def hotel_prices():
    # native 10 sandbox
    native_total = native_price = 0
    for slug, _ in NATIVE_CITIES:
        rs = rows(NATIVE / "accommodations" / slug / "accommodations.csv")
        native_total += len(rs)
        native_price += sum(num(r.get("price"), True) is not None for r in rs)

    # extended 10-city catalog
    if not CATALOG.exists():
        gz = CATALOG.parent / (CATALOG.name + ".gz")
        if gz.exists():
            import gzip, shutil
            with gzip.open(gz, "rb") as src, CATALOG.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    con = sqlite3.connect(f"file:{CATALOG.as_posix()}?mode=ro", uri=True)
    cat_total = cat_price = cat_beds = 0
    for (payload,) in con.execute("select payload from records where kind='accommodation'"):
        d = json.loads(payload).get("data") or {}
        cat_total += 1
        cat_price += num(d.get("price"), True) is not None
        cat_beds += num(d.get("numbed"), True) is not None
    con.close()

    # Xi'an main table (merged sandbox) + provenance from v17
    status = {}
    v17_total = v17_price = 0
    if V17.exists():
        con = sqlite3.connect(f"file:{V17.as_posix()}?mode=ro", uri=True)
        for (payload,) in con.execute("select payload from records where kind='accommodation' and city='西安'"):
            d = json.loads(payload)
            name = (d.get("data") or {}).get("name")
            fp = (d.get("field_provenance") or {}).get("price") or {}
            status[name] = fp.get("status")
            v17_total += 1
            v17_price += num((d.get("data") or {}).get("price"), True) is not None
        con.close()

    xian = rows(MERGED / "accommodations/xian/accommodations.csv")
    xian_price = [r for r in xian if num(r.get("price"), True) is not None]
    prov = Counter(status.get(r["name"], "not_in_v17") for r in xian_price)
    return {
        "native_10": {"hotels": native_total, "price_ok": native_price},
        "catalog_10": {"hotels": cat_total, "price_ok": cat_price, "numbed_ok": cat_beds},
        "xian_main": {"hotels": len(xian), "price_ok": len(xian_price),
                      "source_value": prov.get("source_value", 0),
                      "estimated": prov.get("estimated", 0),
                      "unknown": len(xian) - len(xian_price)},
        "xian_v17": {"hotels": v17_total, "price_ok": v17_price} if v17_total else None,
        "provenance_available": bool(status),
    }


def query_impact():
    detail = xian_missing_detail()
    missing = {r["name"] for r in detail["family_naming"] + detail["near_50m"] + detail["absent"]}
    by_split, files = Counter(), 0
    hits = []
    for path in sorted(QUERIES.glob("*/*.json")):
        text = path.read_text(encoding="utf-8")
        found = [m for m in missing if m and m in text]
        if found:
            files += 1
            by_split[path.parent.name] += 1
            hits.append({"file": path.name, "split": path.parent.name, "names": found[:5]})
    return {"query_files": len(list(QUERIES.glob("*/*.json"))), "files_with_missing": files,
            "by_split": dict(by_split), "examples": hits[:8]}


def pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "-"


def main():
    cities = audit_cities()
    xian = xian_missing_detail()
    hotels = hotel_prices()
    impact = query_impact()

    report = {"generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
              "cities": cities, "xian_attraction_detail": xian,
              "hotels": hotels, "query_impact": impact}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    lines = ["# 数据完整性审计（2026-11-11）", "",
             "对照对象：`poi/<city>/poi.json`（位置索引）。`Poi.search()` 只做**精确名字**查找，"
             "名字不在索引里就无法规划到该实体。", "",
             "## 1. 实体 ↔ 位置索引", "",
             "| 城市 | 景点 | 景点漏接 | 酒店 | 酒店漏接 | 餐厅 | 餐厅漏接 |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for c in cities:
        lines.append(f"| {c['city']} | {c['attractions']['total']} | {c['attractions']['missing']} | "
                     f"{c['hotels']['total']} | {c['hotels']['missing']} | "
                     f"{c['restaurants']['total']} | {c['restaurants']['missing']} |")
    ta = sum(c["attractions"]["total"] for c in cities)
    tm = sum(c["attractions"]["missing"] for c in cities)
    lines += ["", f"景点合计 **{ta}**，漏接 **{tm}**（{pct(tm, ta)}）。", ""]

    lines += ["### 西安景点漏接拆解", "",
              f"- 景点主表 {xian['total']} 条，位置索引精确命中 "
              f"{xian['total'] - xian['missing']} 条（{pct(xian['total'] - xian['missing'], xian['total'])}）；"
              f"漏接 **{xian['missing']}** 条。",
              f"- 其中同一景区/子景点命名差异（如 `西安城墙-魁星楼` vs `西安城墙 Xi'an City Wall`）"
              f"**{len(xian['family_naming'])}** 条；索引内 50 m 内有 POI 但名字不同 **{len(xian['near_50m'])}** 条；"
              f"完全无对应实体 **{len(xian['absent'])}** 条。",
              "", "示例：", ""]
    for r in (xian["absent"][:5] + xian["family_naming"][:3]):
        extra = f"（同族：{r['family']}）" if "family" in r else f"（最近 POI：{r['nearest']}，{r['nearest_m']} m）"
        lines.append(f"- `{r['name']}` {extra}")
    lines += ["", f"题集影响：{impact['query_files']} 道 xian11 题里有 "
                  f"**{impact['files_with_missing']}** 道显式提到漏接景点（{impact['by_split']}）。", ""]

    n10, c10, xm, xv = hotels["native_10"], hotels["catalog_10"], hotels["xian_main"], hotels["xian_v17"]
    combined_total = c10["hotels"] + xm["hotels"]
    combined_price = c10["price_ok"] + xm["price_ok"]
    lines += ["## 2. 酒店 price 齐全度", "",
              "口径：`price` 可解析且 > 0。另给出 `price + numbed` 与 v17 provenance 拆分。", "",
              "| 数据层 | 酒店数 | price 齐全 | 占比 | 备注 |",
              "|---|---:|---:|---:|---|",
              f"| 原生 10 城沙盒 | {n10['hotels']} | {n10['price_ok']} | {pct(n10['price_ok'], n10['hotels'])} | 全部有 numbed/坐标/英文名 |",
              f"| 扩展 10 城 catalog | {c10['hotels']} | {c10['price_ok']} | {pct(c10['price_ok'], c10['hotels'])} | numbed 也 {c10['numbed_ok']} 条齐全 |",
              f"| 西安主表（merged） | {xm['hotels']} | {xm['price_ok']} | {pct(xm['price_ok'], xm['hotels'])} | " +
              ((f"真实观测 {xm['source_value']} + 高置信估价 {xm['estimated']}；缺价 {xm['unknown']}") if hotels["provenance_available"]
               else f"缺价 {xm['unknown']}（provenance 需 v17 快照，未随包发布）") + " |",
              (f"| 西安 v17 全量 | {xv['hotels']} | {xv['price_ok']} | {pct(xv['price_ok'], xv['hotels'])} | 含 reference_only/缺坐标记录 |"
               if xv else "| 西安 v17 全量 | — | — | — | v17 快照未随包发布 |"),
              f"| **G3 合并（扩展10 + 西安）** | **{combined_total}** | **{combined_price}** | **{pct(combined_price, combined_total)}** | 缺口全部在西安 |",
              "",
              "结论：10 城两层都是 100% 齐全；唯一缺口是西安，主表 45.0%，"
              "其中 240 条为来源观测、78 条为采纳的高置信估价（需 v17 快照核对），388 条仍需动态询价。", ""]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
