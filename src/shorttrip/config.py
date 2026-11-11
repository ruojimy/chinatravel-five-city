"""Central configuration for the TAG / provider layer.

One place to answer "may this process talk to that provider, and with what budget".
The old behaviour was hard-coded per adapter, which is exactly how a spent Baidu
quota brought the whole pipeline to a halt: every POI still triggered a request,
none of them could succeed, and nothing degraded to the open-data sources.

Environment variables (all optional):

| variable | default | meaning |
| --- | --- | --- |
| ``BAIDU_REQUEST_BUDGET`` | ``0`` | max live Baidu calls for this process; **0 = never call** |
| ``BAIDU_OFFLINE`` | unset | when truthy, forces replay-only regardless of budget |
| ``SOURCE_FALLBACK_ORDER`` | ``local,osm,wikidata,authorized_dataset,official_site,baidu`` | who may answer a gap, in order |
| ``EVIDENCE_TTL_HOURS`` | ``168`` | evidence cache lifetime |
| ``PROVIDER_STATE_PATH`` | ``data/provider_state.json`` | circuit-breaker state |
| ``TAG_HTTP_TIMEOUT`` | ``25`` | per-request timeout for open-data adapters |
| ``TAG_HTTP_MIN_INTERVAL`` | ``1.1`` | politeness delay between calls to one provider |

The default of 0 for Baidu is deliberate and is the P0 fix: the project must run
end-to-end with zero Baidu requests. A human who wants to spend quota has to say so
explicitly, in one place.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FALLBACK = ("local", "osm", "wikidata", "authorized_dataset", "official_site", "baidu")
TRUTHY = ("1", "true", "yes", "on")


def _int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in TRUTHY


@dataclass(frozen=True)
class Settings:
    baidu_request_budget: int = 0
    baidu_offline: bool = False
    source_fallback_order: tuple[str, ...] = DEFAULT_FALLBACK
    evidence_ttl_hours: int = 168
    provider_state_path: Path = ROOT / "data" / "provider_state.json"
    http_timeout: int = 25
    http_min_interval: float = 1.1

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, root: Path | None = None) -> "Settings":
        base = Path(root) if root else ROOT
        order_raw = os.environ.get("SOURCE_FALLBACK_ORDER", "")
        order = tuple(item.strip() for item in order_raw.split(",") if item.strip()) or DEFAULT_FALLBACK
        state_path = os.environ.get("PROVIDER_STATE_PATH")
        interval = os.environ.get("TAG_HTTP_MIN_INTERVAL")
        try:
            min_interval = float(interval) if interval else 1.1
        except ValueError:
            min_interval = 1.1
        return cls(
            baidu_request_budget=max(0, _int(os.environ.get("BAIDU_REQUEST_BUDGET"), 0)),
            baidu_offline=_bool(os.environ.get("BAIDU_OFFLINE")),
            source_fallback_order=order,
            evidence_ttl_hours=max(1, _int(os.environ.get("EVIDENCE_TTL_HOURS"), 168)),
            provider_state_path=Path(state_path) if state_path else base / "data" / "provider_state.json",
            http_timeout=max(5, _int(os.environ.get("TAG_HTTP_TIMEOUT"), 25)),
            http_min_interval=max(0.0, min_interval),
        )

    # ------------------------------------------------------------------ views
    def provider_budget(self, name: str) -> int:
        """Per-provider live-call budget. Only Baidu is capped today."""
        if name == "baidu":
            if self.baidu_offline:
                return 0
            return self.baidu_request_budget
        return int(os.environ.get(f"{name.upper()}_REQUEST_BUDGET", "1000"))

    def allows(self, name: str) -> bool:
        return self.provider_budget(name) > 0

    def order_index(self, name: str) -> int:
        try:
            return self.source_fallback_order.index(name)
        except ValueError:
            return len(self.source_fallback_order)

    def to_dict(self) -> dict:
        return {
            "baidu_request_budget": self.baidu_request_budget,
            "baidu_offline": self.baidu_offline,
            "source_fallback_order": list(self.source_fallback_order),
            "evidence_ttl_hours": self.evidence_ttl_hours,
            "provider_state_path": str(self.provider_state_path),
            "http_timeout": self.http_timeout,
            "http_min_interval": self.http_min_interval,
        }


_SETTINGS: Settings | None = None


def settings(refresh: bool = False) -> Settings:
    """Process-wide settings; ``refresh=True`` re-reads the environment."""
    global _SETTINGS
    if _SETTINGS is None or refresh:
        _SETTINGS = Settings.load()
    return _SETTINGS
