#!/usr/bin/env bash
set -euo pipefail

data_dir="${CLAUDE_PLUGIN_DATA:-}"
if [[ -z "$data_dir" ]]; then
  exit 0
fi

active="$data_dir/active-run.json"
if [[ ! -f "$active" ]]; then
  exit 0
fi

plugin_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONPATH="${plugin_root}/py:${PYTHONPATH:-}" python3 - "$active" "$data_dir" <<'PY'
import sys

from swarm_do.pipeline.run_state import load_active_run, write_checkpoint_from_active

active = sys.argv[1]
data_dir = sys.argv[2]
state = load_active_run(active)
if not state:
    sys.exit(0)

write_checkpoint_from_active(
    data_dir,
    state,
    source="precompact-hook",
    reason="precompact",
)
PY

run_id="$(PYTHONPATH="${plugin_root}/py:${PYTHONPATH:-}" python3 - "$active" <<'PY' 2>/dev/null || true
import json
import sys

try:
    value = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    value = {}
run_id = value.get("run_id") if isinstance(value, dict) else None
if isinstance(run_id, str):
    print(run_id)
PY
)"

if [[ -n "$run_id" ]]; then
  PYTHONPATH="${plugin_root}/py:${PYTHONPATH:-}" python3 -m swarm_do.telemetry.cli dogfood-check \
    --format markdown \
    --output "$data_dir/dogfood/latest.md" \
    --append-run-event \
    --run-id "$run_id" \
    --source precompact-hook >/dev/null 2>&1 || true
else
  PYTHONPATH="${plugin_root}/py:${PYTHONPATH:-}" python3 -m swarm_do.telemetry.cli dogfood-check \
    --format markdown \
    --output "$data_dir/dogfood/latest.md" >/dev/null 2>&1 || true
fi
