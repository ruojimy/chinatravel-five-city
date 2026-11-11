"""Queue-side helper for A-arm brokers (v2 runs).

The bridge writes one request JSON and blocks until the matching response
exists. A broker uses these subcommands to fetch the next unanswered request
and to write the answer atomically, so no two brokers touch the same file.

Subcommands
  status  --queue DIR --prefix P
  next    --queue DIR --prefix P [--wait SEC] [--plans-dir DIR --target N]
  answer  --queue DIR --request-id ID --text-file UTF8 [--agent-id A] [--model M]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _requests(queue: Path):
    return sorted((queue / "requests").glob("*.json"))


def _answered(queue: Path, request_path: Path) -> bool:
    return (queue / "responses" / request_path.name).exists()


def cmd_status(args) -> int:
    queue = Path(args.queue)
    reqs = [p for p in _requests(queue) if p.name.startswith(args.prefix)]
    pending = [p for p in reqs if not _answered(queue, p)]
    print(json.dumps({"prefix": args.prefix, "requests": len(reqs), "answered": len(reqs) - len(pending),
                      "pending": len(pending), "next": str(pending[0]) if pending else None},
                     ensure_ascii=False))
    return 0


def cmd_next(args) -> int:
    queue = Path(args.queue)
    if args.stop_plan and Path(args.stop_plan).exists():
        print("DONE")
        return 0
    if args.plans_dir and args.target:
        plans = list(Path(args.plans_dir).glob("**/results/LLMNeSy_luna-subagent/*.json"))
        if len(plans) >= args.target:
            print("DONE")
            return 0
    deadline = time.monotonic() + args.wait
    while True:
        for path in _requests(queue):
            if not path.name.startswith(args.prefix):
                continue
            if not _answered(queue, path):
                if args.content:
                    request = json.loads(path.read_text(encoding="utf-8"))
                    print(f"REQUEST_ID: {request['request_id']}")
                    print(f"JSON_MODE: {bool((request.get('call_kwargs') or {}).get('json_mode'))}")
                    print("---CONTENT---")
                    print(request["messages"][-1]["content"])
                else:
                    print(str(path.resolve()))
                return 0
        if time.monotonic() >= deadline:
            print("TIMEOUT")
            return 2
        time.sleep(2)


def cmd_answer(args) -> int:
    queue = Path(args.queue)
    request_path = queue / "requests" / f"{args.request_id}.json"
    response_path = queue / "responses" / f"{args.request_id}.json"
    if not request_path.exists():
        raise SystemExit(f"unknown request: {request_path}")
    if response_path.exists():
        raise SystemExit(f"refusing to overwrite existing response: {response_path}")
    text = Path(args.text_file).read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit("empty answer text")
    payload = {"request_id": args.request_id, "text": text,
               "producer": args.producer, "agent_id": args.agent_id, "model": args.model}
    response_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = response_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, response_path)
    print(f"OK {response_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status")
    status.add_argument("--queue", required=True)
    status.add_argument("--prefix", required=True)
    status.set_defaults(func=cmd_status)

    nxt = sub.add_parser("next")
    nxt.add_argument("--queue", required=True)
    nxt.add_argument("--prefix", required=True)
    nxt.add_argument("--wait", type=float, default=600)
    nxt.add_argument("--plans-dir", default=None)
    nxt.add_argument("--target", type=int, default=0)
    nxt.add_argument("--stop-plan", default=None)
    nxt.add_argument("--content", action="store_true")
    nxt.set_defaults(func=cmd_next)

    answer = sub.add_parser("answer")
    answer.add_argument("--queue", required=True)
    answer.add_argument("--request-id", required=True)
    answer.add_argument("--text-file", required=True)
    answer.add_argument("--agent-id", required=True)
    answer.add_argument("--model", required=True)
    answer.add_argument("--producer", default=None)
    answer.set_defaults(func=cmd_answer)

    args = parser.parse_args()
    if args.command == "answer" and not args.producer:
        args.producer = f"workbuddy-subagent:{args.model}"
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
