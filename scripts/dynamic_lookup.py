"""Single entry point for the dynamic lookups that L2/L3 records trigger on access.

Standard: docs/data_grading_standard.md — L2/L3 records must run a live lookup
before any value is shown. Each kind maps to one provider; providers that are
not wired return `not_wired` instead of inventing a value, and the caller is
expected to display "需确认/需询价".

Usage:
  python scripts/dynamic_lookup.py --kind accommodation --name "西安威斯汀大酒店" \
      --checkin 2026-11-11 --checkout 2026-11-12
  python scripts/dynamic_lookup.py --kind restaurant --name "老张涮菜"
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
LOG = ROOT / "results/xian_gapfill_20261109/dynamic_log.jsonl"

PROVIDERS = {
    "accommodation": {"tool": "hotel_dynamic_price", "wired": True, "ttl_hours": 24},
    "restaurant": {"tool": "poi_dynamic_lookup", "wired": False, "ttl_hours": 168},
    "attraction": {"tool": "poi_dynamic_lookup", "wired": False, "ttl_hours": 72},
    "metro_station": {"tool": "metro_line_lookup", "wired": False, "ttl_hours": 720},
    "train": {"tool": "train_schedule_lookup", "wired": False, "ttl_hours": 24},
    "flight": {"tool": "flight_schedule_lookup", "wired": False, "ttl_hours": 6},
    "poi": {"tool": None, "wired": False, "ttl_hours": None},
}


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def log(record: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def lookup_hotel(name: str, checkin: str | None, checkout: str | None) -> dict:
    import hotel_dynamic_price as hdp

    if checkin and checkout:
        live = hdp.live_price(name, checkin, checkout)
        if live.get("price"):
            return {
                "status": "live",
                "value": {"price": live["price"], "currency": "CNY"},
                "source": {"url": live.get("url"), "observed_at": now()},
                "display": f"¥{live['price']}",
            }
    cached = hdp.last_observation(name)
    if cached:
        return {
            "status": "cached",
            "value": {"price": cached["price"], "currency": "CNY"},
            "source": {"url": cached.get("source_url"), "observed_at": cached.get("observed_at")},
            "display": f"¥{cached['price']}（{cached.get('observed_at')} 观测）",
        }
    rooms = hdp.rooms(hdp.SNAP, name)
    return {
        "status": "unavailable",
        "value": None,
        "rooms_reference": rooms if isinstance(rooms, dict) else None,
        "display": "需实时询价",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True, choices=sorted(PROVIDERS))
    ap.add_argument("--name", required=True)
    ap.add_argument("--checkin")
    ap.add_argument("--checkout")
    args = ap.parse_args()

    meta = PROVIDERS[args.kind]
    base = {"kind": args.kind, "name": args.name, "tool": meta["tool"],
            "trigger": "on_access", "requested_at": now()}

    if args.kind == "accommodation":
        result = lookup_hotel(args.name, args.checkin, args.checkout)
    elif meta["wired"]:
        result = {"status": "unavailable", "display": "需确认"}
    else:
        result = {
            "status": "not_wired",
            "value": None,
            "display": "需确认（该来源尚未接入）",
            "next_step": f"接入 {meta['tool']} 后可自动查询",
        }

    out = {**base, **result, "ttl_hours": meta["ttl_hours"]}
    log(out)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
