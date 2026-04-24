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

python3 - "$active" "$data_dir" <<'PY'
import datetime
import json
import pathlib
import sys

active = pathlib.Path(sys.argv[1])
data_dir = pathlib.Path(sys.argv[2])
try:
    state = json.loads(active.read_text(encoding="utf-8"))
except Exception:
    sys.exit(0)

run_id = state.get("run_id")
if not isinstance(run_id, str) or not run_id:
    sys.exit(0)

checkpoint = {
    "schema_version": 1,
    "written_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    "source": "precompact-hook",
    "run_id": run_id,
    "bd_epic_id": state.get("bd_epic_id"),
    "phase_id": state.get("phase_id"),
    "child_bead_ids": state.get("child_bead_ids", []),
    "work_units": state.get("work_units", []),
    "handoff_counts": state.get("handoff_counts", {}),
    "retry_counts": state.get("retry_counts", {}),
    "integration_branch_head": state.get("integration_branch_head"),
    "status": state.get("status", "incomplete"),
}

run_dir = data_dir / "runs" / run_id
run_dir.mkdir(parents=True, exist_ok=True)
(run_dir / "checkpoint.v1.json").write_text(json.dumps(checkpoint, indent=2, sort_keys=True) + "\n", encoding="utf-8")

event = {
    "run_id": run_id,
    "timestamp": checkpoint["written_at"],
    "event_type": "checkpoint_written",
    "bd_epic_id": checkpoint["bd_epic_id"],
    "phase_id": checkpoint["phase_id"],
    "work_unit_id": None,
    "child_bead_ids": checkpoint["child_bead_ids"],
    "reason": "precompact",
    "retry_count": None,
    "handoff_count": None,
    "integration_branch_head": checkpoint["integration_branch_head"],
    "details": {"checkpoint_path": str(run_dir / "checkpoint.v1.json")},
    "schema_ok": True,
}
telemetry = data_dir / "telemetry"
telemetry.mkdir(parents=True, exist_ok=True)
with (telemetry / "run_events.jsonl").open("a", encoding="utf-8") as f:
    f.write(json.dumps(event, sort_keys=True) + "\n")
PY
