#!/usr/bin/env bash
# E12 — `--max-turns` accounting.
# Question: does the parent --max-turns counter only count top-level Agent tool_use blocks, or also include
# sub-agent internal turns?
#
# Method: launch the parent dispatcher with --max-turns=4 and ask it to spawn a sub-agent that itself runs
# 6 internal turns (counting Bash echoes 1..6). If the parent terminates with reason 'max_turns_exceeded',
# nested turns count. If it completes normally, only top-level turns count.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/lib.sh"

PROMPT='Use the Agent tool with subagent_type "swarmdaddy:agent-writer" and prompt "Run the Bash tool six times in sequence: echo TURN_1 ; then echo TURN_2 ; then echo TURN_3 ; then echo TURN_4 ; then echo TURN_5 ; then echo TURN_6. Use a separate Bash tool_use for each. Then print E12_DONE on a final line and exit.". Then print PARENT_E12_DONE and exit.'

run_claude e12 "$PROMPT" --max-turns 4
RC=$?

stream="$EXPERIMENT_ROOT/e12/stream.jsonl"
cost=$(extract_total_cost "$stream")
turns=$(extract_num_turns "$stream")
parent_done=$(count_response_text_hits "$stream" "PARENT_E12_DONE")
sub_done=$(count_response_text_hits "$stream" "E12_DONE")
turn6_hit=$(count_response_text_hits "$stream" "TURN_6")
result_subtype=$(python3 - "$stream" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    for ln in f:
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        if ev.get("type") == "result":
            print(ev.get("subtype", "?"))
            sys.exit(0)
print("?")
PY
)

verdict="UNKNOWN"
if [ "$result_subtype" = "error_max_turns" ]; then
  verdict="NESTED_COUNTS: parent hit max_turns ($result_subtype) — sub-agent turns appear to count toward parent budget"
elif [ "$parent_done" -ge 1 ]; then
  verdict="TOP_LEVEL_ONLY: parent completed normally with sub-agent doing 6 nested turns under parent --max-turns=4"
else
  verdict="INCONCLUSIVE: subtype=$result_subtype parent_done=$parent_done sub_done=$sub_done turn6=$turn6_hit"
fi

write_summary e12 \
  "# E12 — --max-turns accounting" \
  "" \
  "- exit: $RC" \
  "- total_cost_usd: $cost" \
  "- num_turns (parent): $turns" \
  "- result.subtype: $result_subtype" \
  "- PARENT_E12_DONE hits: $parent_done" \
  "- sub-agent E12_DONE hits: $sub_done" \
  "- TURN_6 reached: $turn6_hit" \
  "- verdict: **$verdict**"

echo "[e12] $verdict"
