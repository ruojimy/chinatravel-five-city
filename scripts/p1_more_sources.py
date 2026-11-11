"""P1 continued: find more CC BY review corpora, and retry 4TU through other routes.

Two things happen here:
1. Zenodo's search API is queried for datasets whose metadata says CC BY (machine
   checked, not read off a web page), then filtered to tourism/review topics. This is
   how the first breakthrough dataset was found, so it is worth doing systematically
   rather than by luck.
2. 4TU is retried through several endpoints, because `data.4tu.nl` kept failing the
   TLS handshake. If none work, the blocker is recorded as a network fact, not as a
   "no such dataset" claim.

Outputs: results/p1/more_sources.json
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "p1" / "more_sources.json"
UA = "ShortTripAssistant/1.0 (course project; licensed corpus discovery)"

QUERIES = [
    "tourist emotional experience Zhangjiajie",
    "online travel reviews destination attractions China",
    "UGC reviews LDA tourism China",
    "游客 评论 数据集",
]
ALLOWED_LICENCES = {"cc-by-4.0", "cc-by-3.0", "cc0-1.0", "cc-by-sa-4.0", "cc-by-nc-4.0"}


def http_json(url: str, timeout: int = 45) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"ok": True, "status": response.status,
                    "body": json.loads(response.read().decode("utf-8", "replace"))}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def zenodo_search(query: str, size: int = 15) -> dict:
    url = "https://zenodo.org/api/records?" + urllib.parse.urlencode(
        {"q": query, "size": size, "type": "dataset"})
    result = http_json(url)
    if not result.get("ok"):
        return {"query": query, "error": result.get("error")}
    hits = []
    for record in (result["body"].get("hits") or {}).get("hits") or []:
        metadata = record.get("metadata") or {}
        licence = metadata.get("license")
        licence_id = licence.get("id") if isinstance(licence, dict) else licence
        files = [{"key": f.get("key"), "size": f.get("size")} for f in (record.get("files") or [])]
        hits.append({
            "title": metadata.get("title"),
            "doi": metadata.get("doi") or record.get("doi"),
            "licence": licence_id,
            "licence_ok": str(licence_id).lower() in ALLOWED_LICENCES,
            "access": metadata.get("access_right"),
            "date": metadata.get("publication_date"),
            "files": files[:4],
            "n_files": len(files),
        })
    return {"query": query, "n": len(hits), "hits": hits}


def retry_4tu() -> dict:
    endpoints = [
        "https://data.4tu.nl/articles/dataset/_/22122224/1",
        "http://data.4tu.nl/articles/_/22122224/1",
        "https://data.4tu.nl/v2/datasets/22122224",
        "https://data.4tu.nl/ndownloader/articles/22122224/versions/1",
    ]
    attempts = []
    for url in endpoints:
        for attempt in range(2):
            request = urllib.request.Request(url, headers={"User-Agent": UA})
            try:
                with urllib.request.urlopen(request, timeout=25) as response:
                    body = response.read()
                attempts.append({"url": url, "status": response.status, "bytes": len(body)})
                return {"ok": True, "attempts": attempts}
            except Exception as exc:  # noqa: BLE001
                attempts.append({"url": url, "attempt": attempt + 1,
                                 "error": f"{type(exc).__name__}: {str(exc)[:110]}"})
                time.sleep(1.5)
    return {"ok": False, "attempts": attempts}


def main() -> int:
    report: dict = {"generated_at": "2026-10-22", "queries": [], "fourtu": None}

    seen: dict[str, dict] = {}
    for query in QUERIES:
        result = zenodo_search(query)
        report["queries"].append({"query": query, "n": result.get("n", 0),
                                  "error": result.get("error")})
        for hit in result.get("hits") or []:
            if not hit["licence_ok"]:
                continue
            key = hit["doi"] or hit["title"]
            if key and key not in seen:
                seen[key] = hit
    report["licensed_candidates"] = sorted(seen.values(), key=lambda item: item.get("date") or "",
                                           reverse=True)
    print(f"licensed candidates: {len(report['licensed_candidates'])}")
    for hit in report["licensed_candidates"][:12]:
        print(f"  [{hit['licence']}] {hit['date']} {str(hit['title'])[:70]}")
        print(f"      files: {[f['key'] for f in hit['files']]}")

    report["fourtu"] = retry_4tu()
    print("\n4tu:", "ok" if report["fourtu"]["ok"] else "still blocked")
    for attempt in report["fourtu"]["attempts"][-3:]:
        print("   ", attempt)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
