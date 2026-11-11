"""Regenerate results/experiment_tables.md from the saved JSON results."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ChinaTravel"))

from shorttrip.experiments import render_markdown  # noqa: E402


def main() -> int:
    results = ROOT / "results"
    baseline = json.loads((results / "e2_baseline.json").read_text(encoding="utf-8"))
    mutations = json.loads((results / "e1_mutations.json").read_text(encoding="utf-8"))["rows"]
    repair = json.loads((results / "e3_repair.json").read_text(encoding="utf-8"))
    infeasible = json.loads((results / "e4_infeasible.json").read_text(encoding="utf-8"))
    markdown = render_markdown(baseline, mutations, repair, infeasible)
    (results / "experiment_tables.md").write_text(markdown, encoding="utf-8")
    print("wrote", results / "experiment_tables.md", len(markdown), "chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
