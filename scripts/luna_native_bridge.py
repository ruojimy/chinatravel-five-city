"""Run original ChinaTravel LLMNeSy with a durable Luna response queue.

The ChinaTravel implementation remains untouched. This launcher replaces only
the in-process LLM callable. A separate Luna broker must read request JSON files
and atomically write corresponding response JSON files.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import runpy
import sys
import time
from typing import Any


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class QueueLLM:
    """Synchronous, durable file protocol implementing ChinaTravel's LLM API."""

    def __init__(self, queue_dir: Path, arm: str, uid_file: Path, timeout: float):
        self.name = "LunaSubagent"
        self.model_name = self.name
        self.input_token_count = 0
        self.output_token_count = 0
        self.input_token_maxx = 0
        self.queue_dir = queue_dir
        self.requests_dir = queue_dir / "requests"
        self.responses_dir = queue_dir / "responses"
        self.arm = arm
        self.uid_file = uid_file
        self.timeout = timeout
        self.broker_wait_time_sec = 0.0
        self.sequence = 0
        self.requests_dir.mkdir(parents=True, exist_ok=True)
        for existing in self.requests_dir.glob(f"{arm}_*_*.json"):
            match = re.search(r"_(\d{5})\.json$", existing.name)
            if match:
                self.sequence = max(self.sequence, int(match.group(1)))

    def __call__(self, messages, one_line=True, json_mode=False, **kwargs):
        uid = self.uid_file.read_text(encoding="utf-8").strip() if self.uid_file.exists() else "unknown"
        safe_uid = re.sub(r"[^A-Za-z0-9_.-]+", "_", uid) or "unknown"
        call_kwargs = {"one_line": one_line, "json_mode": json_mode, **kwargs}
        request_id = None
        # Reattach to an identical unanswered request after an interrupted run.
        for pending_path in sorted(self.requests_dir.glob(f"{self.arm}_{safe_uid}_*.json")):
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
            response = self.responses_dir / pending_path.name
            if (not response.exists() and pending.get("uid") == uid
                    and pending.get("messages") == messages
                    and pending.get("call_kwargs") == call_kwargs):
                request_id = pending["request_id"]
                break
        if request_id is None:
            self.sequence += 1
            request_id = f"{self.arm}_{safe_uid}_{self.sequence:05d}"
            request_path = self.requests_dir / f"{request_id}.json"
            response_path = self.responses_dir / f"{request_id}.json"
            request = {
                "request_id": request_id,
                "uid": uid,
                "arm": self.arm,
                "messages": messages,
                "call_kwargs": call_kwargs,
                "created_at_unix": time.time(),
            }
            if request_path.exists() or response_path.exists():
                raise RuntimeError(f"Refusing to overwrite existing queue item {request_id}")
            _atomic_json(request_path, request)

        response_path = self.responses_dir / f"{request_id}.json"

        wait_started = time.monotonic()
        deadline = None if self.timeout <= 0 else wait_started + self.timeout
        while True:
            if response_path.exists():
                response = json.loads(response_path.read_text(encoding="utf-8"))
                if response.get("request_id") != request_id:
                    raise RuntimeError(f"Response request_id mismatch: {request_id}")
                if not isinstance(response.get("text"), str):
                    raise RuntimeError(f"Response text must be a string: {request_id}")
                if not response.get("producer") or not response.get("agent_id"):
                    raise RuntimeError(f"Response must identify producer and agent_id: {request_id}")
                self.broker_wait_time_sec += time.monotonic() - wait_started
                _atomic_json(self.queue_dir / "audit" / f"{request_id}.response.json", response)
                return response["text"]
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for Luna response: {request_id}")
            time.sleep(0.25)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", required=True, choices=["easy", "medium", "human"])
    parser.add_argument("--runtime-namespace", default=None,
                        help="Separate output/cache namespace for concurrent split runs; defaults to --split")
    parser.add_argument("--index", default=None, help="Optional single UID for bridge smoke/integration runs")
    parser.add_argument("--arm", default="A")
    parser.add_argument("--timeout", type=float, default=0, help="Response wait seconds; 0 waits indefinitely")
    parser.add_argument("--skip", type=int, choices=[0, 1], default=1)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    project = repo_root / "ChinaTravel"
    experiment = repo_root / "results" / "luna_tencity_20261106" / "implementation_a"
    queue_dir = experiment / "queue"
    runtime_namespace = re.sub(r"[^A-Za-z0-9_.-]+", "_", args.runtime_namespace or args.split)
    runtime_root = experiment / "runtime" / runtime_namespace
    experiment.mkdir(parents=True, exist_ok=True)
    # Isolate imports, caches and all generated outputs under the A experiment.
    sys.path.insert(0, str(project))
    os.chdir(project)
    from chinatravel.agent import load_model
    from chinatravel.data import load_datasets

    # Use the repository's frozen local UID lists and original local records.
    # This avoids a hidden Hugging Face fetch while preserving the split and
    # loader's ordinary oracle stripping behavior.
    load_datasets.load_query = load_datasets.load_query_local

    uid_file = runtime_root / "current_uid.txt"
    llm = QueueLLM(queue_dir, f"{args.arm}_{runtime_namespace}", uid_file, args.timeout)
    load_model.init_llm = lambda _name: llm
    original_create_runtime = load_model.create_agent_runtime

    def isolated_runtime(agent_name, llm_name, *, project_root_path, **kwargs):
        runtime = original_create_runtime(
            agent_name,
            llm_name,
            project_root_path=str(runtime_root),
            **kwargs,
        )
        original_run = runtime.agent.run

        def run_with_uid(query, *run_args, **run_kwargs):
            uid_file.write_text(str(query.get("uid", "unknown")), encoding="utf-8")
            wait_before = llm.broker_wait_time_sec
            # Explicitly enforce the public input view at the agent boundary.
            public_query = {key: value for key, value in query.items()
                            if key not in {"hard_logic", "hard_logic_py", "hard_logic_nl"}}
            succeeded, plan = original_run(public_query, *run_args, **run_kwargs)
            plan["broker_wait_time_sec"] = llm.broker_wait_time_sec - wait_before
            return succeeded, plan

        runtime.agent.run = run_with_uid
        return runtime

    load_model.create_agent_runtime = isolated_runtime

    argv = ["run_exp.py", "--agent", "LLMNeSy", "--llm", "luna-subagent",
            "--splits", args.split, "--skip", str(args.skip)]
    if args.index:
        argv += ["--index", args.index]
    sys.argv = argv

    # The upstream loader strips all oracle fields unless oracle_translation is
    # explicitly enabled. We keep it disabled so prompts and agent.run only see
    # the paper's natural language input; the evaluator can retain gold data.
    runpy.run_path(str(project / "run_exp.py"), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
