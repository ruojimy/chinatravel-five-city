"""P1 task A: look inside the three "license pending" datasets with real requests.

The instruction says a repository being publicly visible is not a licence, but we
still need to know *what is inside* before asking for permission. This script reads
only:
  * the README (plain text),
  * the first ~2 KB of a representative data file (its header row),
  * GitHub file metadata (name/size),
and stores the raw snippets so the licence request can quote them.

It never bulk-downloads a dataset.

Outputs: results/p1/deep_check.json
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "p1" / "deep_check.json"
UA = "ShortTripAssistant/1.0 (course project; licence / schema audit; local use only)"

REPOS = {
    "S1_guangdong": {
        "repo": "971851309/Tourism-data-set",
        "readme_candidates": ["README.md", "readme.md", "README.txt"],
        "data_files": ["东莞pois.csv", "广州pois.csv"],
    },
    "S4_ctrip": {
        "repo": "tourismdata/ctripDataset",
        "readme_candidates": ["README.md", "readme.md"],
        "data_files": ["performanceReviews.zip"],
    },
    "S5_context": {
        "repo": "aliannejadi/contextual-appropriateness",
        "readme_candidates": ["README.md", "readme.md"],
        "data_files": ["contextual_features.csv", "contextual_training_data.csv"],
    },
}


def http(url: str, *, headers: dict | None = None, timeout: int = 30) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return {"ok": True, "status": response.status, "bytes": len(raw),
                    "text": raw.decode("utf-8", "replace"), "headers": dict(response.headers)}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": None, "error": str(exc)}


def default_branch(repo: str) -> str:
    meta = http(f"https://api.github.com/repos/{repo}", headers={"Accept": "application/vnd.github+json"})
    if meta.get("ok"):
        try:
            return json.loads(meta["text"]).get("default_branch") or "main"
        except json.JSONDecodeError:
            pass
    return "main"


def first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:600]
    return ""


def main() -> int:
    report: dict = {"generated_at": "2026-10-22", "user_agent": UA, "datasets": {}}

    for key, spec in REPOS.items():
        repo = spec["repo"]
        branch = default_branch(repo)
        entry: dict = {"repo": repo, "branch": branch, "readme": None, "files": {}}

        for name in spec["readme_candidates"]:
            url = f"https://raw.githubusercontent.com/{repo}/{branch}/{name}"
            result = http(url)
            if result.get("ok"):
                text = result["text"]
                entry["readme"] = {
                    "path": name,
                    "chars": len(text),
                    "head": " ".join(text.split())[:1200],
                    "mentions_license": any(word in text.lower() for word in
                                            ("license", "licence", "许可", "版权", "授权", "copyright")),
                    "mentions_permission": any(word in text.lower() for word in
                                               ("permission", "允许", "free to use", "cite")),
                    "first_line": first_line(text),
                }
                break

        for name in spec["data_files"]:
            # Range request: header row only, so we do not download the dataset.
            # Percent-encode the path: Chinese filenames otherwise raise
            # "'ascii' codec can't encode characters" inside urllib.
            quoted = urllib.parse.quote(name)
            url = f"https://raw.githubusercontent.com/{repo}/{branch}/{quoted}"
            result = http(url, headers={"Range": "bytes=0-4095"})
            if result.get("ok"):
                text = result["text"]
                entry["files"][name] = {
                    "bytes_requested": result["bytes"],
                    "header_line": first_line(text),
                    "n_columns": len(first_line(text).split(",")),
                    "looks_binary": "\x00" in text[:64] or text[:2] == "PK",
                }
            else:
                entry["files"][name] = {"error": result.get("error"), "status": result.get("status")}
        report["datasets"][key] = entry
        print(f"{key}: readme={bool(entry['readme'])} files={list(entry['files'])}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")

    for key, entry in report["datasets"].items():
        readme = entry.get("readme") or {}
        print(f"\n=== {key} ({entry['repo']})")
        if readme:
            print("  README:", readme.get("first_line", "")[:100])
            print("  含许可字样:", readme.get("mentions_license"), "| 含授权字样:", readme.get("mentions_permission"))
        for name, meta in entry["files"].items():
            print(f"  {name}: ", meta.get("header_line", meta.get("error"))[:150])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
