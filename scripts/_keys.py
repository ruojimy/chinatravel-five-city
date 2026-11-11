"""Credential loader for the public suite.

Never commit real keys. Resolution order:
  1. environment variable (AMAP_KEY / AMAP_KEYS / BAIDU_AK / BAIDU_SK / DEEPSEEK_API_KEY)
  2. a file under ``.secrets/`` at the repo root (git-ignored)

The scripts that need a key fail loudly with the exact setup instruction instead
of silently using a burned-in key.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / ".secrets"

ENV_FOR = {
    "amap.key": "AMAP_KEY",
    "amap.keys": "AMAP_KEYS",
    "baidu.key": "BAIDU_KEY",
    "deepseek.key": "DEEPSEEK_API_KEY",
}


def _read(name: str) -> str | None:
    env = ENV_FOR.get(name, name.upper())
    value = os.environ.get(env, "").strip()
    if value:
        return value
    path = SECRETS / name
    if path.exists():
        return path.read_text(encoding="ascii").strip()
    return None


def amap_key() -> str:
    key = _read("amap.key")
    if not key:
        raise SystemExit(
            "missing Amap key: set AMAP_KEY or create .secrets/amap.key "
            "(see .env.example)")
    return key


def amap_keys() -> list[str]:
    raw = _read("amap.keys") or _read("amap.key")
    if not raw:
        raise SystemExit(
            "missing Amap keys: set AMAP_KEYS (comma separated) or create "
            ".secrets/amap.keys")
    return [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]
