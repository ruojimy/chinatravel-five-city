"""Probe which DeepSeek endpoints are available with the provided key.

Checks the plain chat endpoint plus candidate search surfaces. Never prints the key.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

KEY = Path(__file__).resolve().parents[1] / ".secrets" / "deepseek.key"
TOKEN = KEY.read_text(encoding="ascii").strip()
BASE = "https://api.deepseek.com"


def call(method: str, path: str, payload: dict | None = None, timeout: int = 60):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, body[:1200]
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:400]
    except Exception as exc:  # noqa: BLE001
        return -1, f"{type(exc).__name__}: {exc}"


def main() -> int:
    print("== GET /models")
    print(call("GET", "/models")[1][:300])

    print("\n== POST /search (probe)")
    print(call("POST", "/search", {"query": "广州塔 开放时间", "top_n": 3}))

    print("\n== POST /v1/search (probe)")
    print(call("POST", "/v1/search", {"query": "广州塔 开放时间"}))

    print("\n== POST /chat/completions with tools=[{type:web_search}]")
    payload = {
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": "广东省博物馆 今天的开放时间和门票价格是多少？"}],
        "tools": [{"type": "web_search"}],
        "max_tokens": 400,
    }
    status, body = call("POST", "/chat/completions", payload)
    print(status, body[:800])

    print("\n== POST /chat/completions with search_options")
    payload2 = {
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": "广东省博物馆的开放时间"}],
        "search": {"enabled": True},
        "max_tokens": 400,
    }
    status, body = call("POST", "/chat/completions", payload2)
    print(status, body[:500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
