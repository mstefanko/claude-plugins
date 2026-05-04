#!/usr/bin/env bash
# Shared experiment harness for phase-session-dispatcher-fanout-plan E6-E17.
# Captures stream-json transcripts from `claude -p` runs and extracts decision-grade signals.

set -u

CLAUDE_BIN="${CLAUDE_BIN:-/Applications/cmux.app/Contents/Resources/bin/claude}"
EXPERIMENT_ROOT="${EXPERIMENT_ROOT:-/tmp/swarmdaddy-experiments}"

# run_claude <experiment_id> <prompt> [extra_args...]
# Captures stream.jsonl, exit code, wall time, prompt, and resolved model.
run_claude() {
  local exp_id="$1"; shift
  local prompt="$1"; shift
  local out_dir="$EXPERIMENT_ROOT/$exp_id"
  mkdir -p "$out_dir"
  printf '%s\n' "$prompt" > "$out_dir/prompt.txt"
  local t0 t1
  t0=$(date +%s)
  "$CLAUDE_BIN" -p \
    --output-format stream-json \
    --verbose \
    --dangerously-skip-permissions \
    "$@" \
    "$prompt" \
    >"$out_dir/stream.jsonl" 2>"$out_dir/stderr.log"
  local rc=$?
  t1=$(date +%s)
  local model
  model=$(extract_model_name "$out_dir/stream.jsonl")
  printf 'exit=%s\nwall_seconds=%s\nmodel=%s\n' "$rc" "$((t1 - t0))" "$model" > "$out_dir/meta.txt"
  return $rc
}

# extract_total_cost <stream.jsonl>  -> prints total_cost_usd or "?" if missing
extract_total_cost() {
  python3 - "$1" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        for ln in f:
            try:
                ev = json.loads(ln)
            except Exception:
                continue
            if ev.get("type") == "result":
                print(ev.get("total_cost_usd", "?"))
                sys.exit(0)
    print("?")
except FileNotFoundError:
    print("?")
PY
}

# extract_num_turns <stream.jsonl>  -> prints num_turns from result event
extract_num_turns() {
  python3 - "$1" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    for ln in f:
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        if ev.get("type") == "result":
            print(ev.get("num_turns", "?"))
            sys.exit(0)
print("?")
PY
}

# extract_model_name <stream.jsonl>  -> prints model id from system init or result event
extract_model_name() {
  python3 - "$1" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        for ln in f:
            try:
                ev = json.loads(ln)
            except Exception:
                continue
            if ev.get("type") == "system" and ev.get("subtype") == "init":
                m = ev.get("model")
                if m: print(m); sys.exit(0)
            if ev.get("type") == "assistant":
                m = (ev.get("message") or {}).get("model")
                if m: print(m); sys.exit(0)
    print("unknown")
except FileNotFoundError:
    print("missing")
PY
}

# extract_tool_uses <stream.jsonl>  -> JSON lines per Agent/Task tool_use
extract_tool_uses() {
  python3 - "$1" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    for ln in f:
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        if ev.get("type") != "assistant":
            continue
        for blk in ev.get("message", {}).get("content", []) or []:
            if blk.get("type") == "tool_use" and blk.get("name") in ("Task", "Agent"):
                print(json.dumps({
                    "tool": blk.get("name"),
                    "subagent_type": (blk.get("input") or {}).get("subagent_type"),
                    "id": blk.get("id"),
                }))
PY
}

# count_response_text_hits <stream.jsonl> <needle>
# Counts occurrences of <needle> in PARENT-RESPONSE TEXT only:
#   - assistant message text blocks
#   - tool_result content (sub-agent return text)
#   - result.result string
# Explicitly EXCLUDES:
#   - user message text (the input prompt — would echo the marker)
#   - tool_use input (the prompt the parent SENDS to a sub-agent — also echoes)
#   - system message (could include role-spec text mentioning the marker)
# Use this to verify a marker was actually emitted by the model, not echoed from input.
count_response_text_hits() {
  local stream="$1"; local needle="$2"
  python3 - "$stream" "$needle" <<'PY'
import json, sys
needle = sys.argv[2]
hits = 0
with open(sys.argv[1]) as f:
    for ln in f:
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        t = ev.get("type")
        if t == "assistant":
            for blk in (ev.get("message", {}).get("content") or []):
                if blk.get("type") == "text":
                    s = blk.get("text", "")
                    if isinstance(s, str): hits += s.count(needle)
        elif t == "user":
            for blk in (ev.get("message", {}).get("content") or []):
                if blk.get("type") != "tool_result":
                    continue
                content = blk.get("content")
                if isinstance(content, str):
                    hits += content.count(needle)
                elif isinstance(content, list):
                    for sub in content:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            txt = sub.get("text", "")
                            if isinstance(txt, str): hits += txt.count(needle)
        elif t == "result":
            r = ev.get("result")
            if isinstance(r, str): hits += r.count(needle)
print(hits)
PY
}

# Backwards-compat alias kept for any caller still using the loose grep — but flagged.
# Prefer count_response_text_hits for verdicts.
grep_subagent_text() {
  count_response_text_hits "$@"
}

# write_summary <exp_id> <line...> -> writes summary.md for the experiment
write_summary() {
  local exp_id="$1"; shift
  local out_dir="$EXPERIMENT_ROOT/$exp_id"
  mkdir -p "$out_dir"
  printf '%s\n' "$@" > "$out_dir/summary.md"
}
