#!/usr/bin/env bash
# E9 — Parallel fanout cap.
# Measure dispatcher context usage / wall time at N ∈ {2, 4, 8, 16} on toy `echo` prompts.
# (Superseded by E17 for realistic prompts.)
#
# Each N spawns N parallel Agent calls in the SAME assistant turn. Per E3 we expect them to run concurrently.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/lib.sh"

run_n() {
  local n="$1"
  local exp_id="e9-n${n}"
  local prompt
  prompt="Issue exactly $n parallel Agent tool_use calls in a SINGLE assistant turn. Use subagent_type \"general-purpose\" for every call. Number them 1..$n. The k-th call's prompt must be: \"Run Bash to echo the literal string TOY_DONE_<k>\" with <k> replaced by the integer 1..$n. After all $n calls return, print PARENT_DONE_N${n} on its own line and exit."
  run_claude "$exp_id" "$prompt"
  local rc=$?
  local stream="$EXPERIMENT_ROOT/$exp_id/stream.jsonl"
  local cost turns wall parallel_count parent_done done_count
  cost=$(extract_total_cost "$stream")
  turns=$(extract_num_turns "$stream")
  wall=$(awk -F= '/wall_seconds/{print $2}' "$EXPERIMENT_ROOT/$exp_id/meta.txt")
  parent_done=$(count_response_text_hits "$stream" "PARENT_DONE_N${n}")
  done_count=$(python3 - "$stream" "$n" <<'PY'
import json, sys
hits = 0
import re
n = int(sys.argv[2])
seen = set()
with open(sys.argv[1]) as f:
    for ln in f:
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        def walk(o):
            global hits
            if isinstance(o, str):
                for k in range(1, n + 1):
                    needle = f"TOY_DONE_{k}"
                    if needle in o and k not in seen:
                        seen.add(k); hits += 1
            elif isinstance(o, dict):
                for v in o.values(): walk(v)
            elif isinstance(o, list):
                for v in o: walk(v)
        walk(ev)
print(hits)
PY
)
  # Count Agent tool_uses inside a single assistant turn
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
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$n" "$rc" "$wall" "$cost" "$turns" "$parallel_count" "$done_count" >> "$EXPERIMENT_ROOT/e9/results.tsv"
  echo "[e9 n=$n] rc=$rc wall=${wall}s cost=$cost peak_parallel=$parallel_count done=$done_count/$n parent_done=$parent_done"
}

mkdir -p "$EXPERIMENT_ROOT/e9"
printf 'N\trc\twall_s\tcost\tparent_turns\tpeak_parallel_tool_uses\tsub_done_count\n' > "$EXPERIMENT_ROOT/e9/results.tsv"

for N in 2 4 8 16; do
  run_n "$N"
done

write_summary e9 \
  "# E9 — Parallel fanout cap (toy echo)" \
  "" \
  "Sweeps N=2,4,8,16 with general-purpose sub-agents. Each sub-agent does one Bash echo." \
  "" \
  '```' \
  "$(cat "$EXPERIMENT_ROOT/e9/results.tsv")" \
  '```' \
  "" \
  "Decision feed: peak_parallel_tool_uses tells us whether the model emits truly parallel Agent calls in one turn." \
  "Wall-clock vs N tells us the speed-up ceiling. Feeds Decision 7 cap (superseded by E17)."

echo "[e9] sweep complete — see $EXPERIMENT_ROOT/e9/results.tsv"
