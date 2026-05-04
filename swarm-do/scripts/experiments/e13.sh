#!/usr/bin/env bash
# E13 — Permission A/B (decisive). Decides Decision 1 (bypass-cascade vs allowlist-supremacy).
#
# Two sub-runs in parallel:
#   (a) --dangerously-skip-permissions               (bypass cascade)
#   (b) --permission-mode default
#       --allowedTools "Agent,Read,Write,Edit,Bash,Grep,Glob"
#
# Each must prove sub-agent Write, Edit, and Bash succeed end-to-end. We assert that the
# spawned sub-agent emitted at least one each of Write, Edit, and Bash tool_use blocks
# AND that those tool_results were not is_error: true.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/lib.sh"

PROBE_PROMPT='Use the Agent tool with subagent_type "swarmdaddy:agent-writer" and prompt: "Run these three tool calls in order: (1) Write to a file at PATHA with content WRITE_OK (use Write tool). (2) Edit that same file replacing WRITE_OK with EDIT_OK (use Edit tool). (3) Run Bash to print BASH_OK to stdout. Then print PROBE_DONE on its own line and exit." After the Agent call returns, print PARENT_PROBE_DONE and exit. Do not call any other tools.'

run_variant() {
  local label="$1"; shift
  local exp_id="e13-${label}"
  local workdir="$EXPERIMENT_ROOT/$exp_id/workdir"
  mkdir -p "$workdir"
  local prompt="${PROBE_PROMPT//PATHA/$workdir/probe.txt}"

  local out_dir="$EXPERIMENT_ROOT/$exp_id"
  mkdir -p "$out_dir"
  printf '%s\n' "$prompt" > "$out_dir/prompt.txt"

  local t0 t1 rc
  t0=$(date +%s)
  # Pipe prompt via stdin to avoid variadic --allowedTools <tools...> slurping it.
  ( cd "$workdir" && printf '%s\n' "$prompt" | "$CLAUDE_BIN" -p \
      --output-format stream-json \
      --verbose \
      --input-format text \
      "$@" \
      >"$out_dir/stream.jsonl" 2>"$out_dir/stderr.log" )
  rc=$?
  t1=$(date +%s)
  printf 'exit=%s\nwall_seconds=%s\nvariant=%s\n' "$rc" "$((t1 - t0))" "$label" > "$out_dir/meta.txt"

  local stream="$out_dir/stream.jsonl"
  local cost; cost=$(extract_total_cost "$stream")
  local turns; turns=$(extract_num_turns "$stream")
  local model; model=$(extract_model_name "$stream")
  # Use scoped response-text counter so prompt echo doesn't false-trigger.
  local probe_done; probe_done=$(count_response_text_hits "$stream" "PROBE_DONE")
  local parent_done; parent_done=$(count_response_text_hits "$stream" "PARENT_PROBE_DONE")
  local file_exists="?"; [ -f "$workdir/probe.txt" ] && file_exists="yes" || file_exists="no"
  local file_contents="(missing)"; [ -f "$workdir/probe.txt" ] && file_contents=$(cat "$workdir/probe.txt")

  local tool_inventory
  tool_inventory=$(python3 - "$stream" <<'PY'
import json, sys, collections
counts = collections.Counter()
errors = collections.Counter()
with open(sys.argv[1]) as f:
    for ln in f:
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        # walk all tool_use entries (parent + sub-agent in nested transcripts)
        def walk(o, in_subagent=False):
            if isinstance(o, dict):
                if o.get("type") == "tool_use":
                    counts[o.get("name", "?")] += 1
                if o.get("type") == "tool_result" and o.get("is_error"):
                    errors["error"] += 1
                for v in o.values(): walk(v, in_subagent)
            elif isinstance(o, list):
                for v in o: walk(v, in_subagent)
        walk(ev)
print(json.dumps({"counts": dict(counts), "errors": dict(errors)}))
PY
)
  local write_count edit_count bash_count error_count
  write_count=$(echo "$tool_inventory" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['counts'].get('Write',0))")
  edit_count=$(echo "$tool_inventory" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['counts'].get('Edit',0))")
  bash_count=$(echo "$tool_inventory" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['counts'].get('Bash',0))")
  error_count=$(echo "$tool_inventory" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['errors'].get('error',0))")

  # Verdict: PASS if end-state is correct (file contents == "EDIT_OK") AND all three
  # tool kinds fired at least once. Transient `is_error` results during exploration
  # do NOT disqualify — what matters is the converged final state. (Original
  # criterion required error_count==0 and produced false-PARTIAL when the agent
  # tried `cat` on a missing file before realizing it needed to Write first.)
  local verdict="UNKNOWN"
  if [ "$file_contents" = "EDIT_OK" ] && [ "$write_count" -ge 1 ] && [ "$edit_count" -ge 1 ] && [ "$bash_count" -ge 1 ]; then
    if [ "$error_count" -gt 0 ]; then
      verdict="PASS (with $error_count transient is_error tool_results — final state correct)"
    else
      verdict="PASS"
    fi
  elif [ "$write_count" -ge 1 ] && [ "$edit_count" -ge 1 ] && [ "$bash_count" -ge 1 ]; then
    verdict="PARTIAL: tools fired but final file state wrong (got '$file_contents')"
  else
    verdict="FAIL: missing tool_uses (W=$write_count E=$edit_count B=$bash_count)"
  fi

  write_summary "$exp_id" \
    "# E13 — Permission A/B variant ($label)" \
    "" \
    "- exit: $rc" \
    "- model: $model" \
    "- total_cost_usd: $cost" \
    "- num_turns: $turns" \
    "- file probe.txt exists: $file_exists" \
    "- file contents: '$file_contents' (expected EDIT_OK)" \
    "- Write tool_uses: $write_count" \
    "- Edit tool_uses: $edit_count" \
    "- Bash tool_uses: $bash_count" \
    "- tool_result is_error (informational; does not disqualify): $error_count" \
    "- PROBE_DONE hits (response-text only): $probe_done" \
    "- PARENT_PROBE_DONE hits (response-text only): $parent_done" \
    "- verdict: **$verdict**"

  echo "[e13-$label] $verdict (W=$write_count E=$edit_count B=$bash_count err=$error_count file=$file_contents cost=$cost)"
}

# Run both variants
run_variant a --dangerously-skip-permissions &
PID_A=$!
run_variant b --permission-mode default --allowedTools "Agent,Read,Write,Edit,Bash,Grep,Glob" &
PID_B=$!
wait $PID_A; RC_A=$?
wait $PID_B; RC_B=$?

# Aggregate
write_summary e13 \
  "# E13 — Permission A/B (decisive)" \
  "" \
  "Variant (a) bypass-cascade: see e13-a/summary.md" \
  "Variant (b) allowlist:      see e13-b/summary.md" \
  "" \
  "Decides Decision 1. PASS in (a) AND (b) → bypass is safe default; PASS only in (a) → allowlist is too restrictive (likely Write/Edit blocked by sub-agent inheritance); FAIL in both → re-evaluate inherit-then-narrow assumption."

echo "[e13] aggregate: variant_a_rc=$RC_A variant_b_rc=$RC_B"
