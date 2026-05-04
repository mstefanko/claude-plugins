#!/usr/bin/env bash
# E17 — Realistic-N parallelism. Extends E9 with non-trivial sub-agent work
# (file edits + Bash output ~500-1000B each).
#
# Sweep N ∈ {2, 4, 8, 16}. Same SINGLE-dispatcher pattern as E9 — measures
# whether realistic prompts elicit different concurrency/serial behaviour
# than toy `echo` prompts.
#
# Per-unit work: write a small Python file, edit it, run it via Bash.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/lib.sh"

run_n() {
  local n="$1"
  local exp_id="e17-n${n}"
  local workdir="$EXPERIMENT_ROOT/$exp_id/workdir"
  mkdir -p "$workdir"

  local prompt="Issue exactly $n parallel Agent tool_use calls in a SINGLE assistant turn. Use subagent_type \"swarmdaddy:agent-writer\" for every call. Number them 1..$n. The k-th call's prompt must be: \"Use Write to create file ${workdir}/u_<k>.py with content: 'def main():\n    return <k> * <k>\nif __name__ == \"__main__\":\n    print(main())\n' . Then use Edit to add a one-line docstring under the def. Then use Bash to run python3 ${workdir}/u_<k>.py and capture its output. Then print E17_DONE_<k> on its own line and exit.\" Replace <k> with the integer 1..$n in each call. After all $n calls return, print PARENT_DONE_N${n} on its own line and exit."

  local out_dir="$EXPERIMENT_ROOT/$exp_id"
  mkdir -p "$out_dir"
  printf '%s\n' "$prompt" > "$out_dir/prompt.txt"

  local t0 t1 rc
  t0=$(date +%s)
  ( cd "$workdir" && printf '%s\n' "$prompt" | "$CLAUDE_BIN" -p \
      --output-format stream-json \
      --verbose \
      --input-format text \
      --dangerously-skip-permissions \
      >"$out_dir/stream.jsonl" 2>"$out_dir/stderr.log" )
  rc=$?
  t1=$(date +%s)
  printf 'exit=%s\nwall_seconds=%s\n' "$rc" "$((t1 - t0))" > "$out_dir/meta.txt"

  local stream="$out_dir/stream.jsonl"
  local cost; cost=$(extract_total_cost "$stream")
  local turns; turns=$(extract_num_turns "$stream")
  local wall=$((t1 - t0))

  local parallel_count
  parallel_count=$(python3 - "$stream" <<'PY'
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
                    if f"E17_DONE_{k}" in o:
                        seen.add(k)
            elif isinstance(o, dict):
                for v in o.values(): walk(v)
            elif isinstance(o, list):
                for v in o: walk(v)
        walk(ev)
print(len(seen))
PY
)
  # Marker order: extract assistant text containing E17_DONE_<k> in stream order
  local marker_order
  marker_order=$(python3 - "$stream" "$n" <<'PY'
import json, sys, re
n = int(sys.argv[2])
order = []
with open(sys.argv[1]) as f:
    for ln in f:
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        def walk(o):
            if isinstance(o, str):
                for m in re.finditer(r'E17_DONE_(\d+)', o):
                    k = int(m.group(1))
                    if k not in order:
                        order.append(k)
            elif isinstance(o, dict):
                for v in o.values(): walk(v)
            elif isinstance(o, list):
                for v in o: walk(v)
        walk(ev)
print(','.join(str(k) for k in order))
PY
)
  # Files actually written
  local files_written
  files_written=$(ls "$workdir" 2>/dev/null | wc -l | tr -d ' ')

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$n" "$rc" "$wall" "$cost" "$turns" "$parallel_count" "$done_count" "$files_written" >> "$EXPERIMENT_ROOT/e17/results.tsv"
  echo "[e17 n=$n] rc=$rc wall=${wall}s cost=$cost peak_parallel=$parallel_count done=$done_count/$n files=$files_written order=$marker_order"
}

mkdir -p "$EXPERIMENT_ROOT/e17"
printf 'N\trc\twall_s\tcost\tparent_turns\tpeak_parallel_tool_uses\tsub_done_count\tfiles_written\n' > "$EXPERIMENT_ROOT/e17/results.tsv"

for N in 2 4 8 16; do
  run_n "$N"
done

write_summary e17 \
  "# E17 — Realistic-N parallelism" \
  "" \
  "Sweeps N=2,4,8,16 with realistic agent-writer sub-agents (Write + Edit + Bash + python3 run)." \
  "" \
  '```' \
  "$(cat "$EXPERIMENT_ROOT/e17/results.tsv")" \
  '```' \
  "" \
  "Decision feed (Decision 7 cap): peak_parallel_tool_uses tells us whether realistic prompts elicit parallel emission." \
  "Wall-clock vs N tells the actual scaling. Compare to E9's toy-prompt baseline."

echo "[e17] sweep complete — see $EXPERIMENT_ROOT/e17/results.tsv"
