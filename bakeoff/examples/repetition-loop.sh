#!/usr/bin/env bash
set -u

# Instructional external repetition harness.
# This is not a Bakeoff scheduler contract; it is a small example of how an
# outside script can generate ordinary work orders with experiment labels.

BAKEOFF_CLI="${BAKEOFF_CLI:-bakeoff}"
# OUT_DIR defaults to runs/, which is .gitignored. A later meta-evaluation that
# uses a gemini provider to READ these run artifacts will see nothing: gemini's
# file tools honor .gitignore. claude/codex evaluators are unaffected, and the
# judge phase is unaffected (judge inputs are passed inline, not read from disk).
# If you plan to meta-evaluate this batch with a gemini worker, set OUT_DIR to a
# non-ignored dir (e.g. OUT_DIR=experiments); show/ls/history stay compatible via
# --out. See plans/experiment-metadata-hardening.md ("Gemini evaluator reads").
OUT_DIR="${OUT_DIR:-runs}"
WORKORDER_DIR="${WORKORDER_DIR:-/tmp/bakeoff-repetition-loop}"
EXPERIMENT_ID="${EXPERIMENT_ID:-review-auth}"
TASK_ID="${TASK_ID:-auth-review}"
REPETITIONS="${REPETITIONS:-2}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-1}"
RUN_PROVIDERS="${RUN_PROVIDERS:-0}"

mkdir -p "$WORKORDER_DIR"

conditions=$(
  cat <<'CONDITIONS'
pairwise.security|security|Find security-relevant auth review findings.
pairwise.tests|tests|Find test and regression coverage gaps in auth behavior.
CONDITIONS
)

write_work_order() {
  local path="$1"
  local run_id="$2"
  local condition_id="$3"
  local slot_id="$4"
  local focus="$5"
  local repetition="$6"
  local attempt="$7"

  cat >"$path" <<JSON
{
  "schema_version": 1,
  "id": "${run_id}",
  "type": "gather",
  "run_mode": "pairwise",
  "goal": "${focus}",
  "background": "Example repetition loop. Replace this with the task context, files, report paths, or benchmark fixture for your study.",
  "experiment": {
    "id": "${EXPERIMENT_ID}",
    "task_id": "${TASK_ID}",
    "condition_id": "${condition_id}",
    "run_kind": "pairwise",
    "repetition_index": ${repetition},
    "slot_id": "${slot_id}",
    "slot_attempt": ${attempt}
  },
  "providers": [
    { "id": "claude", "backend": "claude", "model": "sonnet", "scope": "codebase", "effort": "high" },
    { "id": "codex", "backend": "codex", "model": "gpt-5.5", "scope": "codebase", "effort": "high" }
  ],
  "judge": { "backend": "claude", "model": "opus", "effort": "xhigh" },
  "budgets": {
    "wall_clock_seconds": 900,
    "max_output_bytes": 60000,
    "heartbeat_seconds": 60,
    "output_cap_grace_seconds": 10,
    "max_output_overrun_bytes": 60000
  },
  "scope_policy": { "enforcement": "best_effort" }
}
JSON
}

verify_if_present() {
  local run_id="$1"
  if [ -f "$OUT_DIR/$run_id/manifest.json" ]; then
    "$BAKEOFF_CLI" runs verify "$run_id" --out "$OUT_DIR" --json
  fi
}

rep=1
while [ "$rep" -le "$REPETITIONS" ]; do
  while IFS='|' read -r condition_id slot_id focus; do
    [ -n "$condition_id" ] || continue
    attempt=1
    while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
      rep_label=$(printf "%03d" "$rep")
      run_id="${EXPERIMENT_ID}.r${rep_label}.${slot_id}.attempt-${attempt}"
      work_order="$WORKORDER_DIR/${run_id}.work-order.json"

      if [ -f "$OUT_DIR/$run_id/manifest.json" ]; then
        printf 'skip %s: manifest already present\n' "$run_id"
        verify_if_present "$run_id"
        break
      fi

      write_work_order "$work_order" "$run_id" "$condition_id" "$slot_id" "$focus" "$rep" "$attempt"
      if ! "$BAKEOFF_CLI" validate "$work_order"; then
        exit 2
      fi

      if [ "$RUN_PROVIDERS" != "1" ]; then
        printf 'dry example: %s research %s --out %s --run-id %s --no-triage\n' "$BAKEOFF_CLI" "$work_order" "$OUT_DIR" "$run_id"
        break
      fi

      "$BAKEOFF_CLI" research "$work_order" --out "$OUT_DIR" --run-id "$run_id" --no-triage
      exit_code=$?
      printf 'run %s exited %s\n' "$run_id" "$exit_code"

      if [ -f "$OUT_DIR/$run_id/manifest.json" ]; then
        verify_if_present "$run_id"
        break
      fi

      attempt=$((attempt + 1))
      if [ "$attempt" -le "$MAX_ATTEMPTS" ]; then
        printf 'retrying with a new attempt run id; not using --force\n'
      fi
    done
  done <<CONDITIONS
$conditions
CONDITIONS
  rep=$((rep + 1))
done
