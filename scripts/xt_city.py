"""City context for the xian_* collector toolchain.

The scripts were written for 西安 with a module-level ``CITY`` constant. Rather
than fork every script per city, they now read the city from ``XT_CITY``
(default 西安, so existing Xi'an runs keep byte-identical behaviour) and take
the sanity bbox from the table below.

Usage:
    XT_CITY=厦门 python scripts/xian_field_campaign.py status --snapshot ...
"""
from __future__ import annotations

import os

DEFAULT_CITY = "西安"

# Rough city-level bbox used only as a coordinate sanity gate in xian_verify.py.
BBOX_BY_CITY = {
    "西安": {"lon": (107.3, 109.9), "lat": (33.5, 34.9)},
    "厦门": {"lon": (117.6, 118.6), "lat": (24.2, 25.0)},
}

# Whole-country fallback: still catches swapped lat/lon, no false rejects.
FALLBACK_BBOX = {"lon": (73.0, 136.0), "lat": (3.0, 54.0)}


def city() -> str:
    return (os.environ.get("XT_CITY") or DEFAULT_CITY).strip()


def bbox(name: str | None = None) -> dict:
    return BBOX_BY_CITY.get(name or city(), FALLBACK_BBOX)
