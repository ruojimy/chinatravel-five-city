"""Download the ChinaTravel public releases (queries + sandbox) into reproduction/data.

Only public, unauthenticated Hugging Face files are fetched. Files are cached by
name and skipped when already present with the expected byte size.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
HF = "https://huggingface.co/datasets"

FILES = [
    # (repo, path, local name)
    ("LAMDA-NeSy/ChinaTravel", "easy.csv", "query/easy.csv"),
    ("LAMDA-NeSy/ChinaTravel", "medium.csv", "query/medium.csv"),
    ("LAMDA-NeSy/ChinaTravel", "human.csv", "query/human.csv"),
    ("LAMDA-NeSy/ChinaTravel", "human1000.csv", "query/human1000.csv"),
    ("LAMDA-NeSy/ChinaTravel", "preference_base50.csv", "query/preference_base50.csv"),
    ("LAMDA-NeSy/ChinaTravel", "preference0_base50.csv", "query/preference0_base50.csv"),
    ("LAMDA-NeSy/ChinaTravel", "preference1_base50.csv", "query/preference1_base50.csv"),
    ("LAMDA-NeSy/ChinaTravel", "preference2_base50.csv", "query/preference2_base50.csv"),
    ("LAMDA-NeSy/ChinaTravel", "preference3_base50.csv", "query/preference3_base50.csv"),
    ("LAMDA-NeSy/ChinaTravel", "preference4_base50.csv", "query/preference4_base50.csv"),
    ("LAMDA-NeSy/ChinaTravel", "preference5_base50.csv", "query/preference5_base50.csv"),
    ("LAMDA-NeSy/ChinaTravel", "phase2/competition_test.csv", "query/phase2/competition_test.csv"),
    ("LAMDA-NeSy/ChinaTravel", "README.md", "query/README.md"),
    ("LAMDA-NeSy/ChinaTravel", "DATA_QUALITY_FIXES_2026_08.md", "query/DATA_QUALITY_FIXES_2026_08.md"),
    ("LAMDA-NeSy/ChinaTravel", "PHASE2_RELEASE_NOTES.md", "query/PHASE2_RELEASE_NOTES.md"),
    ("LAMDA-NeSy/ChinaTravel-Sandbox", "README.md", "sandbox/README.md"),
    ("LAMDA-NeSy/ChinaTravel-Sandbox", "release_manifest.json", "sandbox/release_manifest.json"),
    ("LAMDA-NeSy/ChinaTravel-Sandbox", "raw/ChinaTravel_sandbox_zh.zip", "sandbox/ChinaTravel_sandbox_zh.zip"),
    ("LAMDA-NeSy/ChinaTravel-Sandbox", "raw/ChinaTravel_sandbox_en.zip", "sandbox/ChinaTravel_sandbox_en.zip"),
]

for table in ["accommodations", "attractions", "flights", "poi", "restaurants", "subway_stations", "trains"]:
    for lang in ["zh", "en"]:
        FILES.append(
            (
                "LAMDA-NeSy/ChinaTravel-Sandbox",
                f"data/{lang}/{table}.parquet",
                f"sandbox/parquet/{lang}/{table}.parquet",
            )
        )


def fetch(repo: str, remote: str, local: str) -> None:
    dst = RAW / local
    dst.parent.mkdir(parents=True, exist_ok=True)
    url = f"{HF}/{repo}/resolve/main/{remote}"
    req = urllib.request.Request(url, headers={"User-Agent": "chinatravel-repro/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = resp.read()
    dst.write_bytes(payload)
    print(f"{len(payload):>10,}  {local}")


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for repo, remote, local in FILES:
        if only and only not in local:
            continue
        dst = RAW / local
        if dst.exists() and dst.stat().st_size > 0:
            print(f"{'cached':>10}  {local}")
            continue
        try:
            fetch(repo, remote, local)
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED {local}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
