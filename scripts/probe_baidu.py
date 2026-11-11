"""Probe Baidu Place API 3.0: prove the SN signature works, then enumerate the
exact fields this account can actually obtain.

Writes results/baidu_probe.json (UTF-8). Never prints the AK/SK — only a mask.

Usage:
    .\.venv\Scripts\python ..\scripts\probe_baidu.py            # cached + live
    .\.venv\Scripts\python ..\scripts\probe_baidu.py --no-cache # force live calls
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.dynamic.baidu import (  # noqa: E402
    BaiduCredentialsError,
    BaiduPlaceClient,
    canonical_query,
    load_credentials,
    normalize_poi,
    sign_variants,
)

OUT = ROOT / "results" / "baidu_probe.json"

# A spread that covers: a well-known landmark, a museum, a recently opened venue,
# a city-park style POI, and a name that does not exist (identity must fail).
CASES = [
    ("广州", "广州塔"),
    ("广州", "南越王博物院"),
    ("上海", "上海博物馆东馆"),
    ("北京", "故宫博物院"),
    ("广州", "ShortTrip 不存在的博物馆"),
]


def main() -> int:
    live = "--no-cache" in sys.argv
    report: dict = {"generated_by": "scripts/probe_baidu.py", "live_calls": live}
    try:
        creds = load_credentials()
    except BaiduCredentialsError as exc:
        report["ok"] = False
        report["error"] = str(exc)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("NO CREDENTIALS:", exc)
        return 2

    report["credentials"] = creds.redacted()
    # Show the theory before touching the network, so a failure is diagnosable.
    demo_params = {"q": "广州塔", "region": "广州", "output": "json", "ak": creds.ak}
    report["signature_demo"] = {
        "uri": "/place/v3/search",
        "canonical_query_pct": canonical_query(demo_params, "pct"),
        "variants": sign_variants("/place/v3/search", demo_params, creds.sk or ""),
    }

    client = BaiduPlaceClient(creds, cache=not live, max_calls=60)
    sig = client.discover_signature_style()
    report["signature"] = sig
    print("signature ok =", sig.get("ok"), "style =", sig.get("style"))
    for trial in sig.get("trials", []):
        print("   ", trial)

    report["cases"] = []
    if sig.get("ok"):
        for city, name in CASES:
            payload = client.search(name, city, page_size=3)
            entry = {"city": city, "name": name, "status": payload.get("status"), "message": payload.get("message")}
            pois = (payload.get("result") or {}).get("pois") or []
            entry["n_pois"] = len(pois)
            if pois:
                flat = normalize_poi(pois[0], source_coord="gcj02ll")
                entry["first_poi"] = flat
                entry["availability"] = {
                    key: flat.get(key) not in (None, "", [], 0)
                    for key in (
                        "uid", "address", "type_path", "tag_path", "shop_hours",
                        "price_text", "overall_rating", "comment_num", "telephone", "detail_url",
                    )
                }
                if flat.get("uid"):
                    detail = client.detail(flat["uid"])
                    dpoi = ((detail.get("result") or {}).get("pois") or [None])[0]
                    entry["detail"] = {
                        "status": detail.get("status"),
                        "message": detail.get("message"),
                        "detail_info_keys": sorted((((dpoi or {}).get("detail_info")) or {}).keys()),
                    }
                    if dpoi:
                        entry["detail_poi"] = normalize_poi(dpoi, source_coord="gcj02ll")
            report["cases"].append(entry)
            print(f"[{city}] {name}: status={entry['status']} pois={entry['n_pois']} "
                  f"rating={((entry.get('first_poi') or {}).get('overall_rating'))} "
                  f"comments={((entry.get('first_poi') or {}).get('comment_num'))}")

    report["budget"] = client.budget_report()
    report["calls"] = [call.to_dict() for call in client.calls]
    report["ok"] = bool(sig.get("ok"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT)
    print(json.dumps(report["budget"], ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
