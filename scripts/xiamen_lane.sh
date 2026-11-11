#!/usr/bin/env bash
# Run N sequential L1-enrich batches for one kind against the Xiamen snapshot.
#
# Usage: scripts/xiamen_lane.sh <kind> <offset_start> <batches> [limit] [worker_suffix] [snapshot]
#   kind   attraction | restaurant | accommodation
#   offset start index inside that kind's pending list
#   snapshot optional path to the catalog.sqlite3 (default snapshot_v1)
#
# Each batch is a separate process, so RSS returns to baseline between batches
# instead of growing with the run. Nothing here writes to a snapshot: the lane
# only produces staging/enrich_*.jsonl; ingest is the main agent's job.
set -u

KIND=${1:?kind required}
OFF=${2:-0}
BATCHES=${3:-1}
LIMIT=${4:-60}
SUFFIX=${5:-w1}
SNAP_ARG=${6:-}

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 1
export XT_CITY=厦门
RUN=results/xiamen_claude_20261111_2350
SNAP=${SNAP_ARG:-$RUN/snapshot_v1/catalog.sqlite3}

for i in $(seq 1 "$BATCHES"); do
  echo "--- ${KIND} offset=${OFF} batch=${i}/${BATCHES}"
  ./.venv/Scripts/python.exe scripts/xian_field_campaign.py enrich \
    --snapshot "$SNAP" --run "$RUN" --worker "enrich_${KIND}_${SUFFIX}" \
    --kind "$KIND" --offset "$OFF" --limit "$LIMIT" --max-calls "$LIMIT" --sleep 0.45 \
    || { echo "batch failed, stopping lane"; exit 1; }
  OFF=$((OFF + LIMIT))
done
