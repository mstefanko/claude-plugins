#!/usr/bin/env bash
# E6 — `subagent_type: swarmdaddy:agent-writer` resolution.
# PASS = the spawned writer prints SWARM_WRITER_RESOLVED and exits;
# FAIL = subagent unresolved or general-purpose fallback used.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/lib.sh"

PROMPT='Use the Agent tool with subagent_type "swarmdaddy:agent-writer" and prompt "Print exactly the literal string SWARM_WRITER_RESOLVED on its own line, then exit.". Do not paraphrase. Do not call any other tools.'

run_claude e6 "$PROMPT"
RC=$?

stream="$EXPERIMENT_ROOT/e6/stream.jsonl"
cost=$(extract_total_cost "$stream")
turns=$(extract_num_turns "$stream")
hits=$(count_response_text_hits "$stream" "SWARM_WRITER_RESOLVED")
tool_uses=$(extract_tool_uses "$stream")

verdict="UNKNOWN"
agent_used=$(printf '%s\n' "$tool_uses" | grep -c '"tool"' || true)
if [ "$hits" -ge 1 ] && [ "$agent_used" -ge 1 ]; then
  verdict="PASS"
elif [ "$agent_used" -ge 1 ]; then
  verdict="PARTIAL: agent invoked, marker not echoed"
else
  verdict="FAIL: dispatcher did not call Agent tool"
fi

write_summary e6 \
  "# E6 — swarmdaddy:agent-writer resolution" \
  "" \
  "- exit: $RC" \
  "- total_cost_usd: $cost" \
  "- num_turns: $turns" \
  "- SWARM_WRITER_RESOLVED hits: $hits" \
  "- Agent/Task tool_use blocks: $agent_used" \
  "- verdict: **$verdict**" \
  "" \
  '## tool_uses' \
  '```json' \
  "$tool_uses" \
  '```'

echo "[e6] $verdict"
