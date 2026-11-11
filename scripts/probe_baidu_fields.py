"""Dump the *real* Baidu Place response for a few POIs so the field inventory is
evidence, not assumption. Saves raw JSON to results/baidu_raw/.

Tries, in order: place/v3/search (documented 3.0), place/v2/search (the path that
actually answers for this AK), then detail lookups with the uid we obtained.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shorttrip.dynamic.baidu import (  # noqa: E402
    HOST,
    BaiduPlaceClient,
    canonical_query,
    load_credentials,
    normalize_poi,
    sign_query,
)
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

from shorttrip.dynamic.baidu import UA  # noqa: E402

OUT = ROOT / "results" / "baidu_raw"


def raw_get(path: str, params: dict) -> dict:
    creds = load_credentials()
    full = {**params, "ak": creds.ak}
    qs = canonical_query(full, "java")
    sn = sign_query(path, qs, creds.sk or "")
    url = f"{HOST}{path}?{qs}&sn={sn}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return {"_http_error": exc.code}
    except Exception as exc:  # noqa: BLE001
        return {"_error": str(exc)}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cases = [("广州", "广州塔"), ("广州", "南越王博物院"), ("北京", "故宫博物院"),
             ("上海", "上海博物馆东馆"), ("广州", "ShortTrip 不存在的博物馆")]
    summary = []
    for city, name in cases:
        v3 = raw_get("/place/v3/search", {"q": name, "region": city, "output": "json", "scope": "2", "page_size": "3"})
        v2 = raw_get("/place/v2/search", {"query": name, "region": city, "output": "json", "scope": "2",
                                          "page_size": "3", "ret_coordtype": "gcj02ll"})
        entry = {
            "city": city,
            "name": name,
            "v3": {"http_ok": "_http_error" not in v3, "status": v3.get("status"), "message": v3.get("message"),
                   "n": len((v3.get("results") or v3.get("result") or {}).get("pois") or [])},
            "v2": {"status": v2.get("status"), "message": v2.get("message"),
                   "n": len(v2.get("results") or [])},
        }
        pois = v2.get("results") or []
        if pois:
            flat = normalize_poi(pois[0], source_coord="gcj02ll")
            entry["v2_first_poi"] = flat
            entry["v2_raw_keys"] = sorted(pois[0].keys())
            entry["v2_detail_keys"] = sorted((pois[0].get("detail_info") or {}).keys())
            uid = flat.get("uid")
            if uid:
                d2 = raw_get("/place/v2/detail", {"uid": uid, "output": "json", "scope": "2"})
                d3 = raw_get("/place/v3/detail", {"uid": uid, "output": "json", "scope": "2"})
                entry["detail_v2"] = {
                    "status": d2.get("status"), "message": d2.get("message"),
                    "keys": sorted(((d2.get("result") or {}).get("detail_info") or {}).keys()),
                    "name": (d2.get("result") or {}).get("name"),
                }
                entry["detail_v3"] = {
                    "status": d3.get("status"), "message": d3.get("message"),
                    "keys": sorted(((d3.get("result") or {}).get("detail_info") or {}).keys()),
                    "name": (d3.get("result") or {}).get("name"),
                }
                (OUT / f"detail_v2_{uid}.json").write_text(json.dumps(d2, ensure_ascii=False, indent=2), encoding="utf-8")
                (OUT / f"detail_v3_{uid}.json").write_text(json.dumps(d3, ensure_ascii=False, indent=2), encoding="utf-8")
        (OUT / f"search_{city}_{name}.json").write_text(json.dumps({"v3": v3, "v2": v2}, ensure_ascii=False, indent=2), encoding="utf-8")
        summary.append(entry)
        top = entry.get("v2_first_poi") or {}
        print(f"[{city}] {name}: v2 n={entry['v2']['n']} name={top.get('name')!r} "
              f"rating={top.get('overall_rating')} comments={top.get('comment_num')} hours={bool(top.get('shop_hours'))}")
        print("    v2 detail_info keys:", entry.get("v2_detail_keys"))
        print("    detail_v2:", entry.get("detail_v2"))
    (ROOT / "results" / "baidu_field_inventory.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", ROOT / "results" / "baidu_field_inventory.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
