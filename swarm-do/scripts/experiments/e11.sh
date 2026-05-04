#!/usr/bin/env bash
# E11 — Typo fallback. Feed an unknown subagent_type and confirm Anthropic's general-purpose fallback behaviour.
# Outcomes (mutually exclusive):
#   SILENT_FALLBACK     — marker emitted; no is_error tool_result; no error mention in assistant text
#   WARN_AND_FALLBACK   — marker emitted; assistant text or tool_result mentions agent-not-found / falling back
#   HARD_ERROR          — Agent tool_use returned is_error=true; marker not reached
#   OTHER               — neither fallback nor error string visible

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/lib.sh"

PROMPT='Use the Agent tool with subagent_type "swarmdaddy:totally-not-a-real-agent" and prompt "Print exactly TYPO_FALLBACK_REACHED and exit.". Do not call any other tools. If the Agent tool errors, report the exact error in your assistant text and stop.'

run_claude e11 "$PROMPT"
RC=$?

stream="$EXPERIMENT_ROOT/e11/stream.jsonl"
cost=$(extract_total_cost "$stream")
turns=$(extract_num_turns "$stream")
model=$(extract_model_name "$stream")

# Marker reached? (response-text only — excludes the prompt echo of the marker.)
hits=$(count_response_text_hits "$stream" "TYPO_FALLBACK_REACHED")

# Semantic fallback / error detection — restricted to assistant text and tool_result content.
# We look for any of: "agent not found", "no such agent", "fallback", "general-purpose"
# AND check Agent tool_results for is_error=true. (The original substring grep walked
# all events including the prompt itself, producing false "not found" hits.)
analysis=$(python3 - "$stream" <<'PY'
import json, re, sys

agent_tool_use_ids = set()
agent_is_error = False
fallback_text_hits = 0
explicit_not_found = 0
fallback_re = re.compile(r"\b(agent not found|no such agent|fall(?:ing)? ?back|general[- ]purpose)\b", re.I)
not_found_re = re.compile(r"\b(no such agent|agent not found)\b", re.I)

with open(sys.argv[1]) as f:
    for ln in f:
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        t = ev.get("type")
        if t == "assistant":
            for blk in (ev.get("message", {}).get("content") or []):
                bt = blk.get("type")
                if bt == "tool_use" and blk.get("name") in ("Agent", "Task"):
                    agent_tool_use_ids.add(blk.get("id"))
                if bt == "text":
                    s = blk.get("text", "")
                    if isinstance(s, str):
                        fallback_text_hits += len(fallback_re.findall(s))
                        explicit_not_found += len(not_found_re.findall(s))
        elif t == "user":
            for blk in (ev.get("message", {}).get("content") or []):
                if blk.get("type") != "tool_result":
                    continue
                tu_id = blk.get("tool_use_id")
                if tu_id in agent_tool_use_ids and blk.get("is_error"):
                    agent_is_error = True
                content = blk.get("content")
                if isinstance(content, list):
                    for sub in content:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            s = sub.get("text", "")
                            if isinstance(s, str):
                                fallback_text_hits += len(fallback_re.findall(s))
                                explicit_not_found += len(not_found_re.findall(s))
                elif isinstance(content, str):
                    fallback_text_hits += len(fallback_re.findall(content))
                    explicit_not_found += len(not_found_re.findall(content))

print(json.dumps({
    "agent_tool_use_count": len(agent_tool_use_ids),
    "agent_is_error": agent_is_error,
    "fallback_text_hits": fallback_text_hits,
    "explicit_not_found": explicit_not_found,
}))
PY
)

agent_count=$(echo "$analysis" | python3 -c "import json,sys; print(json.load(sys.stdin)['agent_tool_use_count'])")
agent_error=$(echo "$analysis" | python3 -c "import json,sys; print(json.load(sys.stdin)['agent_is_error'])")
fb_hits=$(echo "$analysis" | python3 -c "import json,sys; print(json.load(sys.stdin)['fallback_text_hits'])")
not_found_hits=$(echo "$analysis" | python3 -c "import json,sys; print(json.load(sys.stdin)['explicit_not_found'])")
tool_uses=$(extract_tool_uses "$stream")

verdict="UNKNOWN"
if [ "$agent_error" = "True" ] && [ "$hits" -eq 0 ]; then
  verdict="HARD_ERROR: Agent tool_result.is_error=true; fallback marker not reached"
elif [ "$hits" -ge 1 ] && [ "$fb_hits" -ge 1 ]; then
  verdict="WARN_AND_FALLBACK: marker reached; assistant/tool_result mentions agent-not-found or general-purpose fallback ($fb_hits mention(s))"
elif [ "$hits" -ge 1 ]; then
  verdict="SILENT_FALLBACK: marker reached; no agent-not-found mention in assistant or tool_result text"
else
  verdict="OTHER: marker not reached and no fallback string visible"
fi

write_summary e11 \
  "# E11 — Typo fallback" \
  "" \
  "- exit: $RC" \
  "- model: $model" \
  "- total_cost_usd: $cost" \
  "- num_turns: $turns" \
  "- TYPO_FALLBACK_REACHED hits (response-text only): $hits" \
  "- Agent tool_use blocks issued: $agent_count" \
  "- Agent tool_result.is_error: $agent_error" \
  "- fallback / general-purpose mentions in assistant + tool_result text: $fb_hits" \
  "- explicit 'no such agent' / 'agent not found' mentions: $not_found_hits" \
  "- verdict: **$verdict**" \
  "" \
  '## tool_uses' \
  '```json' \
  "$tool_uses" \
  '```'

echo "[e11] $verdict"
