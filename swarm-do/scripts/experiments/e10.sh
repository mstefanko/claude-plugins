#!/usr/bin/env bash
# E10 — Plugin namespacing. Confirm `swarmdaddy:` prefix resolves through the project/plugin sub-agent lookup order.
# We compare two probes:
#   (a) subagent_type "swarmdaddy:agent-writer"  (namespaced)
#   (b) subagent_type "agent-writer"             (bare; expected: not found OR project-only)
# PASS = (a) resolves and lists the role-spec body; (b) reports no such agent OR resolves to a different definition.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/lib.sh"

PROMPT='Use the Agent tool with subagent_type "swarmdaddy:agent-writer" and prompt "Print exactly NAMESPACED_OK on its own line, then exit.". Then in a SECOND Agent tool_use call, set subagent_type to "agent-writer" (no prefix) and prompt "Print exactly BARE_OK on its own line, then exit.". Do not call any other tools. Both calls in sequence.'

run_claude e10 "$PROMPT"
RC=$?

stream="$EXPERIMENT_ROOT/e10/stream.jsonl"
cost=$(extract_total_cost "$stream")
turns=$(extract_num_turns "$stream")
namespaced_hits=$(count_response_text_hits "$stream" "NAMESPACED_OK")
bare_hits=$(count_response_text_hits "$stream" "BARE_OK")
tool_uses=$(extract_tool_uses "$stream")

verdict="UNKNOWN"
if [ "$namespaced_hits" -ge 1 ] && [ "$bare_hits" -ge 1 ]; then
  verdict="BOTH_RESOLVE: namespaced and bare both work — namespacing not strictly required"
elif [ "$namespaced_hits" -ge 1 ] && [ "$bare_hits" -eq 0 ]; then
  verdict="PASS: namespaced resolves, bare does not — prefix is required"
elif [ "$namespaced_hits" -eq 0 ] && [ "$bare_hits" -ge 1 ]; then
  verdict="INVERTED: bare resolves, namespaced does not — re-evaluate plugin lookup"
else
  verdict="FAIL: neither marker observed"
fi

write_summary e10 \
  "# E10 — Plugin namespacing" \
  "" \
  "- exit: $RC" \
  "- total_cost_usd: $cost" \
  "- num_turns: $turns" \
  "- NAMESPACED_OK hits: $namespaced_hits" \
  "- BARE_OK hits: $bare_hits" \
  "- verdict: **$verdict**" \
  "" \
  '## tool_uses' \
  '```json' \
  "$tool_uses" \
  '```'

echo "[e10] $verdict"
