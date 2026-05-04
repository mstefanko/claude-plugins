#!/usr/bin/env bash
# Shared experiment harness for phase-session-dispatcher-fanout-plan E6-E17.
# Captures stream-json transcripts from `claude -p` runs and extracts decision-grade signals.

set -u

CLAUDE_BIN="${CLAUDE_BIN:-/Applications/cmux.app/Contents/Resources/bin/claude}"
EXPERIMENT_ROOT="${EXPERIMENT_ROOT:-/tmp/swarmdaddy-experiments}"

# run_claude <experiment_id> <prompt> [extra_args...]
# Captures stream.jsonl, exit code, wall time, prompt, and resolved model.
#
# REUSE_STREAM=1 in the environment short-circuits the claude invocation when
# $EXPERIMENT_ROOT/<exp_id>/stream.jsonl already exists — re-derive metrics
# from the cached transcript instead of re-spending API budget. The cached
# meta.txt is preserved as-is so wall_seconds reflects the original run; if
# meta.txt is missing we synthesize one with reuse=1 marked.
run_claude() {
  local exp_id="$1"; shift
  local prompt="$1"; shift
  local out_dir="$EXPERIMENT_ROOT/$exp_id"
  mkdir -p "$out_dir"
  if [ "${REUSE_STREAM:-0}" = "1" ] && [ -s "$out_dir/stream.jsonl" ]; then
    if [ ! -s "$out_dir/meta.txt" ]; then
      local model
      model=$(extract_model_name "$out_dir/stream.jsonl")
      printf 'exit=0\nwall_seconds=0\nmodel=%s\nreuse=1\n' "$model" > "$out_dir/meta.txt"
    fi
    printf '[reuse] %s — replaying %s\n' "$exp_id" "$out_dir/stream.jsonl" >&2
    return 0
  fi
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

# Helper: short-circuits a direct `claude -p` invocation in a script that
# bypasses run_claude (e.g. e9p/e17 that need stdin-input or custom cwd).
# Usage:
#   if reuse_stream_short_circuit "$out_dir"; then return 0; fi
# Returns 0 (true) and emits a [reuse] log line if the cached stream is
# usable; otherwise returns 1 so the caller proceeds with the real claude
# invocation.
reuse_stream_short_circuit() {
  local out_dir="$1"
  if [ "${REUSE_STREAM:-0}" != "1" ]; then return 1; fi
  if [ ! -s "$out_dir/stream.jsonl" ]; then return 1; fi
  if [ ! -s "$out_dir/meta.txt" ]; then
    local model
    model=$(extract_model_name "$out_dir/stream.jsonl")
    printf 'exit=0\nwall_seconds=0\nmodel=%s\nreuse=1\n' "$model" > "$out_dir/meta.txt"
  fi
  printf '[reuse] replaying %s\n' "$out_dir/stream.jsonl" >&2
  return 0
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

# count_unique_k_markers <stream.jsonl> <prefix> <n> [suffix]
# Returns the number of distinct k in 1..n where "<prefix><k><suffix>" appears
# in PARENT-RESPONSE TEXT only (assistant text blocks, tool_result content,
# result.result string). Excludes user message text and tool_use input — the
# parent dispatcher's own prompts to sub-agents echo the marker template and
# would otherwise inflate the count whether or not the sub-agent ever ran.
# Use this to count actual sub-agent completions, not parent-side echoes.
count_unique_k_markers() {
  local stream="$1"; local prefix="$2"; local n="$3"; local suffix="${4:-}"
  python3 - "$stream" "$prefix" "$n" "$suffix" <<'PY'
import json, re, sys
stream, prefix, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
suffix = sys.argv[4] if len(sys.argv) > 4 else ""
pat = re.compile(re.escape(prefix) + r"(\d+)" + re.escape(suffix))
seen = set()

def scan(s):
    if not isinstance(s, str):
        return
    for m in pat.finditer(s):
        try:
            k = int(m.group(1))
        except ValueError:
            continue
        if 1 <= k <= n:
            seen.add(k)

with open(stream) as f:
    for ln in f:
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        t = ev.get("type")
        if t == "assistant":
            for blk in (ev.get("message", {}).get("content") or []):
                if blk.get("type") == "text":
                    scan(blk.get("text", ""))
        elif t == "user":
            for blk in (ev.get("message", {}).get("content") or []):
                if blk.get("type") != "tool_result":
                    continue
                content = blk.get("content")
                if isinstance(content, str):
                    scan(content)
                elif isinstance(content, list):
                    for sub in content:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            scan(sub.get("text", ""))
        elif t == "result":
            scan(ev.get("result"))
print(len(seen))
PY
}

# write_summary <exp_id> <line...> -> writes summary.md for the experiment
write_summary() {
  local exp_id="$1"; shift
  local out_dir="$EXPERIMENT_ROOT/$exp_id"
  mkdir -p "$out_dir"
  printf '%s\n' "$@" > "$out_dir/summary.md"
}
