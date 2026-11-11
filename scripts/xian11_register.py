"""Register Xi'an as an 11th city at RUNTIME, without editing ChinaTravel/.

The official loaders iterate `chinatravel.environment.language.CITY_SLUGS` and
`CITY_NAMES`, and read files from `environment/database/<kind>/<slug>/`.
Adding a city permanently would change the frozen 10-city baseline, so this
module provides an opt-in, reversible registration:

    from xian11_register import register_xian
    register_xian()                 # patches CITY_SLUGS/CITY_NAMES in memory
    env = World(...)                # now sees the 11th city

It also symlinks/copies nothing into ChinaTravel/: callers that need the
sandbox can pass `base_path` explicitly (see `sandbox_base_path()`), or use
the exported `data/xian11_sandbox` directory with a loader that accepts a
custom path. A `--check` mode verifies the exported sandbox layout only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / "data/xian11_sandbox"
SLUG = "xian"
CITY_ZH = "西安"
CITY_EN = "Xi'an"

REQUIRED_FILES = [
    "attractions/xian/attractions.csv",
    "restaurants/xian/restaurants_xian.csv",
    "accommodations/xian/accommodations.csv",
    "poi/xian/poi.json",
    "subway_stations/xian/subway_stations.json",
    "intercity_transport/airplane.jsonl",
]


def sandbox_layout_ok() -> tuple[bool, list[str]]:
    missing = [p for p in REQUIRED_FILES if not (SANDBOX / p).exists()]
    train = list((SANDBOX / "intercity_transport" / "train").glob("from_*_to_*.json"))
    if not train:
        missing.append("intercity_transport/train/from_*_to_*.json")
    return not missing, missing


def register_xian() -> dict:
    """Patch the official city registries in memory. Idempotent."""
    sys.path.insert(0, str(ROOT / "ChinaTravel"))
    from chinatravel.environment import language  # noqa: E402

    before = list(language.CITY_SLUGS)
    if SLUG not in language.CITY_SLUGS:
        language.CITY_SLUGS.append(SLUG)
    for lang, name in (("zh", CITY_ZH), ("en", CITY_EN)):
        if name not in language.CITY_NAMES[lang]:
            language.CITY_NAMES[lang].append(name)
    ok, missing = sandbox_layout_ok()
    return {"registered": True, "slug": SLUG,
            "cities_before": len(before), "cities_after": len(language.CITY_SLUGS),
            "sandbox_layout_ok": ok, "sandbox_missing": missing,
            "note": "in-memory patch only; ChinaTravel/ files are untouched"}


def sandbox_base_path() -> str:
    return str(SANDBOX)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="verify sandbox layout only")
    ap.add_argument("--register", action="store_true", help="apply in-memory registration and report")
    args = ap.parse_args()
    ok, missing = sandbox_layout_ok()
    print(json.dumps({"sandbox": str(SANDBOX.relative_to(ROOT)).replace("\\", "/"),
                      "layout_ok": ok, "missing": missing}, ensure_ascii=False, indent=1))
    if args.register:
        print(json.dumps(register_xian(), ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
