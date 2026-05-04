#!/usr/bin/env bash
# E9p — Parallel-forcing re-test of E9/E17 (counter-test to the SERIAL DISPATCH finding).
#
# Anthropic's tool-use docs recommend phrasing that emphasises independence and parallel emission.
# E9 and E17 both saw peak_parallel_tool_uses=1. We re-prompt with stronger parallel cues:
#   - explicit "emit all calls simultaneously"
#   - explicit "do NOT wait for any tool_result before issuing the next"
#   - calls framed as fully independent (no shared output dir, no numbering implying order)
#   - sub-prompts deliberately identical so the model can't infer dependence
#
# Sweep N=4 first (~$0.25). If peak_parallel >1, run N=8.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/lib.sh"

run_n_parallel_forcing() {
  local n="$1"
  local exp_id="e9p-n${n}"
  local out_dir="$EXPERIMENT_ROOT/$exp_id"
  mkdir -p "$out_dir"

  # The prompt explicitly tells the model these calls are independent and must be
  # emitted in the SAME assistant turn. Sub-agents share an identical prompt body,
  # disambiguated only by an opaque tag, so the model has no excuse to serialize.
  local prompt
  prompt="You will issue exactly ${n} Agent tool_use blocks in your NEXT assistant turn. All ${n} blocks MUST be emitted in the same turn — do not wait for any tool_result before issuing the rest. The calls are FULLY INDEPENDENT (no shared state, no ordering dependency). Each call uses subagent_type \"general-purpose\" and the same prompt template, distinguished only by a tag. The k-th call's prompt is exactly: \"Run Bash to print the literal string TAG_<k>_OK and exit. Do not call any other tools.\" — replace <k> with the integer 1..${n}. After ALL ${n} tool_results return, print PARENT_DONE_N${n} on its own line and exit. Important: emit the ${n} tool_use blocks SIMULTANEOUSLY in one assistant message; do not pause between them."

  printf '%s\n' "$prompt" > "$out_dir/prompt.txt"

  local t0 t1 rc
  t0=$(date +%s)
  printf '%s\n' "$prompt" | "$CLAUDE_BIN" -p \
    --output-format stream-json \
    --verbose \
    --input-format text \
    --dangerously-skip-permissions \
    >"$out_dir/stream.jsonl" 2>"$out_dir/stderr.log"
  rc=$?
  t1=$(date +%s)
  printf 'exit=%s\nwall_seconds=%s\n' "$rc" "$((t1 - t0))" > "$out_dir/meta.txt"

  local stream="$out_dir/stream.jsonl"
  local cost; cost=$(extract_total_cost "$stream")
  local turns; turns=$(extract_num_turns "$stream")
  local wall=$((t1 - t0))

  local peak_parallel
  peak_parallel=$(python3 - "$stream" <<'PY'
import json, sys
peak = 0
with open(sys.argv[1]) as f:
    for ln in f:
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        if ev.get("type") != "assistant":
            continue
        tu = sum(1 for blk in (ev.get("message", {}).get("content") or []) if blk.get("type") == "tool_use" and blk.get("name") in ("Task", "Agent"))
        if tu > peak:
            peak = tu
print(peak)
PY
)
  local done_count
  done_count=$(python3 - "$stream" "$n" <<'PY'
import json, sys
n = int(sys.argv[2])
seen = set()
with open(sys.argv[1]) as f:
    for ln in f:
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        def walk(o):
            if isinstance(o, str):
                for k in range(1, n + 1):
                    if f"TAG_{k}_OK" in o:
                        seen.add(k)
            elif isinstance(o, dict):
                for v in o.values(): walk(v)
            elif isinstance(o, list):
                for v in o: walk(v)
        walk(ev)
print(len(seen))
PY
)
  echo "[e9p n=$n] rc=$rc wall=${wall}s cost=$cost peak_parallel=$peak_parallel done=$done_count/$n"
  printf '%s\n' "$peak_parallel" > "$out_dir/peak_parallel.txt"
}

mkdir -p "$EXPERIMENT_ROOT/e9p"

run_n_parallel_forcing 4
peak4=$(cat "$EXPERIMENT_ROOT/e9p-n4/peak_parallel.txt" 2>/dev/null || echo 0)

if [ "$peak4" -gt 1 ]; then
  echo "[e9p] N=4 emitted $peak4 parallel tool_uses — laddering to N=8"
  run_n_parallel_forcing 8
fi

write_summary e9p \
  "# E9p — Parallel-forcing re-test (counter-test for E9/E17 SERIAL finding)" \
  "" \
  "Stronger parallel-emission prompt vs E9/E17. Sweeps N=4; ladders to N=8 only if peak>1." \
  "" \
  "If peak_parallel >1: SERIAL was a prompt-phrasing artifact; design must support parallel emission and the controller can lean on model concurrency for v1." \
  "If peak_parallel ==1: SERIAL is structural under -p stream-json; v1 design must accept serial dispatch and rely on per-unit isolation gains."

echo "[e9p] done — see $EXPERIMENT_ROOT/e9p-n*"
