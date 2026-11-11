"""Fetch a public page to disk for gap-fill evidence, with a hash receipt.

Usage:
  python scripts/xian_gapfill_fetch.py --url URL --out results/<run>/raw/<name>/<slug>.html [--timeout 20]

Prints one JSON object: status, bytes, sha256, path, final_url, content_type.
Refuses non-2xx (still saves the body for audit when --keep-errors is set).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--keep-errors", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        resp = requests.get(args.url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"},
                            timeout=args.timeout, allow_redirects=True)
        body = resp.content
        status = resp.status_code
        ctype = resp.headers.get("Content-Type", "")
        final = resp.url
    except Exception as exc:  # network failure is data, not a crash
        print(json.dumps({"ok": False, "error": type(exc).__name__, "detail": str(exc)[:300],
                          "url": args.url}, ensure_ascii=False))
        return 2

    if status >= 400 and not args.keep_errors:
        print(json.dumps({"ok": False, "status": status, "url": args.url,
                          "final_url": final, "content_type": ctype}, ensure_ascii=False))
        return 1

    out.write_bytes(body)
    print(json.dumps({
        "ok": 200 <= status < 300,
        "status": status,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "path": str(out.relative_to(ROOT)).replace("\\", "/"),
        "url": args.url,
        "final_url": final,
        "content_type": ctype,
    }, ensure_ascii=False))
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    sys.exit(main())
