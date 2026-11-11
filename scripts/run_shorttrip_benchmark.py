"""One-shot controller: readiness gate -> Qwen3.5-4B Q8 server -> three arms.

Refuses to start unless scripts/shorttrip_readiness.py reports READY (price
backfill quiet, model complete, server alias correct). The experiment itself
runs the upstream ShortTrip C-only driver unchanged; only config['workers'] and
the frozen case lists differ between arms.

Usage (after the parallel gap-fill line has gone quiet):
  .venv/Scripts/python.exe scripts/run_shorttrip_benchmark.py --all
  .venv/Scripts/python.exe scripts/run_shorttrip_benchmark.py --serve-only
  .venv/Scripts/python.exe scripts/run_shorttrip_benchmark.py --arm G1_native
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv/Scripts/python.exe"
LOCAL = Path(os.environ.get("SHORTTRIP_LOCAL", ROOT.parent / "shorttrip-local"))
RUNS = Path(os.environ.get("SHORTTRIP_RUNS", ROOT.parent / "shorttrip-runs"))
SERVER = LOCAL / "llama-bin/llama-server.exe"
MODEL = LOCAL / "Qwen3.5-4B-Q8_0.gguf"
ENDPOINT = "http://127.0.0.1:18080/v1"
ALIAS = "qwen3.5-4b-q8"
NP = int(os.environ.get("SHORTTRIP_NP", "6"))          # server slots == driver workers
CTX_PER_SLOT = int(os.environ.get("SHORTTRIP_CTX", "16384"))  # tutorial: 16K context
# VRAM rule of thumb: one weight copy (~5 GB) + ~0.45 GB per 16K slot. On a
# 16 GB card 6 slots fit; 12 slots fit too but leave little headroom. Never
# start a second model server for a second arm — share this one instead.
ARMS = ("G1_native", "G2_ext10", "G3_ext11")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def server_alive() -> bool:
    try:
        with urllib.request.urlopen(ENDPOINT + "/models", timeout=3) as r:
            ids = [d.get("id") for d in json.loads(r.read().decode("utf-8")).get("data", [])]
        return ALIAS in ids
    except Exception:  # noqa: BLE001
        return False


def start_server() -> subprocess.Popen | None:
    if server_alive():
        print("[server] already up", flush=True)
        return None
    cmd = [str(SERVER), "-m", str(MODEL), "--host", "127.0.0.1", "--port", "18080",
           "--alias", ALIAS, "-np", str(NP), "--kv-unified-per-slot", str(CTX_PER_SLOT),
           "-ngl", "99", "--reasoning", "off", "--jinja"]
    log = (LOCAL / "llama_server.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(cmd, cwd=str(LOCAL / "llama-bin"), stdout=log,
                            stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    print(f"[server] started pid={proc.pid} np={NP} ctx/slot={CTX_PER_SLOT} reasoning=off",
          flush=True)
    for i in range(120):
        if server_alive():
            print(f"[server] ready after {i * 2}s", flush=True)
            return proc
        if proc.poll() is not None:
            raise RuntimeError("llama-server exited early; see llama_server.log")
        time.sleep(2)
    raise TimeoutError("llama-server did not become ready within 240s")


def smoke() -> dict:
    body = json.dumps({"model": ALIAS,
                       "messages": [{"role": "user", "content": "只回复两个字：就绪"}],
                       "max_tokens": 64}).encode("utf-8")
    req = urllib.request.Request(ENDPOINT + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode("utf-8"))
    content = d["choices"][0]["message"].get("content") or ""
    return {"model": d.get("model"), "content": content.strip()[:120],
            "has_think_tag": "<think>" in content, "usage": d.get("usage")}


def find_checkout(arm: str) -> Path:
    # The prepare step records the exact active checkout; older snapshots stay
    # on disk but must never be picked up by accident.
    active_file = RUNS / "ACTIVE_CHECKOUTS.json"
    if active_file.exists():
        chosen = read(active_file).get(arm)
        if chosen and Path(chosen).exists():
            return Path(chosen)
    cands = sorted(p for p in RUNS.glob(arm + "*")
                   if (p / "experiments/c_only/manifest.json").exists())
    if not cands:
        raise FileNotFoundError(f"no prepared checkout for {arm}")
    return cands[-1]


def run_arm(arm: str) -> dict:
    checkout = find_checkout(arm)
    out = checkout / "experiments/c_only"
    manifest = read(out / "manifest.json")
    config = read(out / "config.json")
    print(f"[{arm}] {checkout} cases={len(manifest['cases'])} workers={config['workers']}",
          flush=True)
    started = time.monotonic()
    proc = subprocess.run([str(PY), "-B", "-X", "utf8", str(out / "driver.py")],
                          cwd=str(checkout),
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                                   PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
                                   PYTHONUNBUFFERED="1"),
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    (RUNS / f"{arm}_driver_stdout.log").write_text(
        (proc.stdout or "") + "\n--- STDERR ---\n" + (proc.stderr or ""), encoding="utf-8")
    statuses = {}
    for f in sorted((out / "status").glob("*.json")):
        s = read(f)
        statuses[f.stem] = {"state": s.get("state"),
                            "candidate_count": s.get("candidate_count"),
                            "evaluation": s.get("evaluation"),
                            "new_rule_audit": s.get("new_rule_audit"),
                            "combined_pass": s.get("combined_pass"),
                            "api_calls": s.get("api_calls")}
    summary = {
        "arm": arm, "checkout": str(checkout), "started_at": datetime.now(timezone.utc).isoformat(),
        "driver_returncode": proc.returncode, "elapsed_seconds": round(time.monotonic() - started, 1),
        "cases": len(manifest["cases"]), "statuses_written": len(statuses),
        "states": {}, "statuses": statuses,
    }
    for s in statuses.values():
        k = str(s["state"])
        summary["states"][k] = summary["states"].get(k, 0) + 1
    save(RUNS / f"{arm}_summary.json", summary)
    print(f"[{arm}] done rc={proc.returncode} states={summary['states']}", flush=True)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--arm", choices=ARMS)
    ap.add_argument("--serve-only", action="store_true")
    ap.add_argument("--skip-gate", action="store_true",
                    help="DANGEROUS: only for a smoke test before the data is frozen")
    ap.add_argument("--accept-coverage", metavar="NOTE", default=None,
                    help="operator confirms the current price coverage; forwarded to the gate")
    args = ap.parse_args()

    # Start/own the server FIRST. A separately backgrounded llama-server gets
    # reaped between agent turns, which would make the gate's server_alias check
    # fail forever. Keeping it as this process's child ties its lifetime to the
    # benchmark run.
    start_server()
    test = smoke()
    save(RUNS / "SMOKE.json", test)
    print(f"[smoke] {test}", flush=True)
    if args.serve_only:
        return 0

    if not args.skip_gate:
        gate_cmd = [str(PY), str(ROOT / "scripts/shorttrip_readiness.py")]
        if args.accept_coverage:
            gate_cmd += ["--accept-coverage", args.accept_coverage]
        gate = subprocess.run(gate_cmd, cwd=str(ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        report = read(RUNS / "READINESS.json") if (RUNS / "READINESS.json").exists() else {}
        if gate.returncode != 0 or not report.get("ready"):
            print("BLOCKED: readiness gate is not READY. See shorttrip-runs/READINESS.md",
                  flush=True)
            print(gate.stdout[-1500:], flush=True)
            return 2

    arms = ARMS if args.all else (args.arm,)
    results = [run_arm(a) for a in arms]
    save(RUNS / "BENCHMARK_SUMMARY.json", {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "model": "Qwen3.5-4B Q8_0", "alias": ALIAS, "endpoint": ENDPOINT,
        "workers": NP, "wall_seconds": 1800, "candidate_target": 20,
        "arms": {r["arm"]: {"cases": r["cases"], "states": r["states"],
                            "elapsed_seconds": r["elapsed_seconds"]} for r in results},
        "note": "Scores are the upstream ShortTrip evaluation; see each arm's summary.json.",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
