"""Provider budget + circuit breaker.

The failure this fixes
----------------------
When the Baidu free quota ran out, every POI in the collection loop still issued a
request. Each one failed with a quota status, each one was retried by the transport
layer, and the run produced nothing while burning wall-clock time. Nothing in the
code noticed that the *provider* was down for the day, and there was no way to say
"spend zero Baidu calls and keep working from open data".

Behaviour
---------
* every live call must be allowed by :meth:`ProviderGuard.acquire`, which checks the
  configured budget and the breaker;
* a quota / auth / repeated network failure **trips the breaker for the rest of the
  UTC day** and is persisted, so the next process does not repeat the mistake;
* state is a small JSON file, human-readable, with the exact status code and message
  that caused it — evidence, not a guess;
* ``reset`` exists for tests and for a human who knows the quota returned.

Nothing here retries with another key. That would be quota evasion and is out of
scope by instruction.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings, settings

STATUSES = (
    "ok",
    "budget_zero",
    "budget_exhausted",
    "quota_exhausted",
    "auth_failed",
    "rate_limited",
    "timeout",
    "network_error",
    "breaker_open",
)

# Which provider answer deserves a day-long stop.
TRIPPING_STATUSES = {"quota_exhausted", "auth_failed"}
# Provider-specific status codes that mean "quota".
BAIDU_QUOTA_CODES = {4, 302, 402}
BAIDU_AUTH_CODES = {5, 101, 102, 200, 203, 240}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ProviderState:
    provider: str
    day: str = ""
    spent: int = 0
    budget: int = 0
    status: str = "ok"
    open: bool = False
    opened_at: str | None = None
    reason: str = ""
    last_status_code: int | None = None
    last_message: str = ""
    denied: int = 0
    history: list[dict] = field(default_factory=list)

    def reset_for_day(self, budget: int) -> None:
        self.day = _today()
        self.spent = 0
        self.budget = budget
        self.open = False
        self.opened_at = None
        self.reason = ""
        self.status = "ok"

    def to_dict(self) -> dict:
        return asdict(self)


class ProviderGuard:
    """Budget + breaker for every outbound data provider."""

    def __init__(self, path: str | Path | None = None, *, settings_obj: Settings | None = None):
        self.settings = settings_obj or settings()
        self.path = Path(path) if path else self.settings.provider_state_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._states: dict[str, ProviderState] = {}
        self._load()

    # ------------------------------------------------------------------ state
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return
        for name, raw in (payload.get("providers") or {}).items():
            try:
                self._states[name] = ProviderState(**raw)
            except TypeError:
                continue

    def _save(self) -> None:
        payload = {"updated_at": _now(),
                   "providers": {name: state.to_dict() for name, state in self._states.items()}}
        try:
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    def state(self, provider: str) -> ProviderState:
        budget = self.settings.provider_budget(provider)
        state = self._states.get(provider)
        if state is None:
            state = ProviderState(provider=provider, budget=budget)
            state.reset_for_day(budget)
            self._states[provider] = state
            self._save()
            return state
        if state.day != _today():
            # a new UTC day: quota counters and the breaker go back to zero
            state.reset_for_day(budget)
            self._save()
        elif state.budget != budget:
            state.budget = budget
            if budget == 0:
                state.status = "budget_zero"
        return state

    # ------------------------------------------------------------------ gate
    def acquire(self, provider: str, *, cost: int = 1) -> tuple[bool, str]:
        """May this call happen? Returns ``(allowed, reason)``; never raises."""
        state = self.state(provider)
        if state.budget <= 0:
            state.status = "budget_zero"
            state.denied += 1
            self._save()
            return False, f"{provider}: 预算为 0（BAIDU_REQUEST_BUDGET/配置），不发起真实请求"
        if state.open:
            state.status = "breaker_open"
            state.denied += 1
            self._save()
            return False, f"{provider}: 熔断中（{state.reason}，{state.opened_at} 起当日停止）"
        if state.spent + cost > state.budget:
            state.status = "budget_exhausted"
            state.denied += 1
            self._save()
            return False, f"{provider}: 进程预算耗尽（{state.spent}/{state.budget}）"
        return True, "ok"

    def spend(self, provider: str, *, cost: int = 1) -> None:
        state = self.state(provider)
        state.spent += cost
        state.status = "ok"
        self._save()

    # -------------------------------------------------------------- feedback
    def record(self, provider: str, *, ok: bool, status_code: int | None = None,
               message: str = "", kind: str | None = None) -> str:
        """Record one provider answer; returns the classified status."""
        state = self.state(provider)
        state.last_status_code = status_code
        state.last_message = str(message)[:200]
        classified = kind or self.classify(provider, status_code, ok)
        state.status = classified
        state.history.append({"at": _now(), "status": classified, "code": status_code,
                              "message": str(message)[:120]})
        state.history = state.history[-20:]
        if classified in TRIPPING_STATUSES:
            state.open = True
            state.opened_at = _now()
            state.reason = f"{classified}: {state.last_message}"
        self._save()
        return classified

    @staticmethod
    def classify(provider: str, status_code: int | None, ok: bool) -> str:
        if ok:
            return "ok"
        if status_code is None:
            return "network_error"
        code = int(status_code)
        if provider == "baidu":
            if code in BAIDU_QUOTA_CODES:
                return "quota_exhausted"
            if code in BAIDU_AUTH_CODES:
                return "auth_failed"
        if code == 429:
            return "rate_limited"
        if code in (401, 403):
            return "auth_failed"
        return "network_error"

    def reset(self, provider: str | None = None) -> None:
        names = [provider] if provider else list(self._states)
        for name in names:
            self._states.pop(name, None)
        self._save()

    # ------------------------------------------------------------------ view
    def snapshot(self) -> dict:
        out = {}
        for name in {*self._states, "baidu", "osm", "wikidata"}:
            state = self.state(name)
            out[name] = {"budget": state.budget, "spent": state.spent,
                         "status": state.status, "breaker_open": state.open,
                         "reason": state.reason, "denied": state.denied,
                         "last_status_code": state.last_status_code,
                         "last_message": state.last_message}
        return {"path": str(self.path), "settings": self.settings.to_dict(), "providers": out}


_GUARD: ProviderGuard | None = None


def guard(refresh: bool = False) -> ProviderGuard:
    global _GUARD
    if _GUARD is None or refresh:
        _GUARD = ProviderGuard()
    return _GUARD
