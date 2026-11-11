"""P1 task A (continued): check candidate *licensed* visitor-review datasets.

Two DOI-registered datasets look relevant:
  * 4TU.ResearchData 10.4121/22122224.v1 — "Research data of online travel reviews
    of destination attractions in China"
  * Zenodo records on tourist emotional experience in Zhangjiajie

DataCite/Zenodo metadata carries a machine-readable `rights` / `license` field, so
the licence question can be answered from the API rather than from prose.

Writes results/p1/new_sources.json
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "p1" / "new_sources.json"
UA = "ShortTripAssistant/1.0 (course project; dataset licence audit)"

TARGETS = {
    "4tu_reviews_cn": "https://api.datacite.org/dois/10.4121/22122224.v1",
    "zenodo_zhangjiajie_21633654": "https://zenodo.org/api/records/21633654",
    "zenodo_zhangjiajie_18795396": "https://zenodo.org/api/records/18795396",
}


def http_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return {"ok": True, "status": response.status,
                    "body": json.loads(response.read().decode("utf-8", "replace"))}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": None, "error": str(exc)}


def summarize_datacite(body: dict) -> dict:
    attributes = body.get("data", {}).get("attributes", {}) or {}
    rights = attributes.get("rightsList") or []
    return {
        "source": "datacite",
        "doi": attributes.get("doi"),
        "title": (attributes.get("titles") or [{}])[0].get("title"),
        "publisher": attributes.get("publisher"),
        "publication_year": attributes.get("publicationYear"),
        "types": (attributes.get("types") or {}).get("resourceTypeGeneral"),
        "licenses": [{"rights": item.get("rights"), "uri": item.get("rightsUri"),
                      "scheme": item.get("schemeUri")} for item in rights],
        "license_clear": bool(rights),
        "descriptions": [d.get("description", "")[:400] for d in (attributes.get("descriptions") or [])][:2],
        "url": attributes.get("url"),
        "subjects": [s.get("subject") for s in (attributes.get("subjects") or [])][:10],
        "sizes": attributes.get("sizes"),
        "formats": attributes.get("formats"),
    }


def summarize_zenodo(body: dict) -> dict:
    metadata = body.get("metadata", {}) or {}
    license_info = metadata.get("license") or {}
    return {
        "source": "zenodo",
        "doi": metadata.get("doi") or body.get("doi"),
        "title": metadata.get("title"),
        "publication_date": metadata.get("publication_date"),
        "resource_type": (metadata.get("resource_type") or {}).get("title"),
        "license": license_info if isinstance(license_info, dict) else {"id": license_info},
        "license_clear": bool(license_info),
        "access_right": metadata.get("access_right"),
        "creators": [c.get("name") for c in (metadata.get("creators") or [])][:5],
        "description": (metadata.get("description") or "")[:500],
        "files": [{"key": f.get("key"), "size": f.get("size")} for f in (body.get("files") or [])][:8],
        "links": {"html": body.get("links", {}).get("self_html") or body.get("links", {}).get("html")},
    }


def main() -> int:
    report: dict = {"generated_at": "2026-10-22", "sources": {}}
    for key, url in TARGETS.items():
        result = http_json(url)
        if not result.get("ok"):
            report["sources"][key] = {"error": result.get("error"), "http": result.get("status"), "url": url}
            print(f"{key}: ERROR {result.get('error')}")
            continue
        body = result["body"]
        summary = summarize_datacite(body) if "datacite" in url else summarize_zenodo(body)
        summary["api"] = url
        report["sources"][key] = summary
        print(f"{key}: license_clear={summary['license_clear']} | {summary.get('title')}")
        print(f"    license={summary.get('licenses') or summary.get('license')}")
        print(f"    access={summary.get('access_right')} keys={list(summary)[:6]}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
