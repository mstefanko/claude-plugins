#!/usr/bin/env bash
# load-role.sh [--manifest] <role-name>
#
# Default mode: prints the content of agents/<role-name>.md from the plugin
# root. Used by the orchestrator skill to inject role personas directly into
# subagent prompts — sidesteps the unverified ${CLAUDE_PLUGIN_ROOT} expansion
# in Read-tool prose.
#
# --manifest mode: prints a JSON manifest with persona-bundle byte breakdown
# (role file, shared/overlay/lens components if discoverable) instead of the
# role text. Used by callers that want to record persona-bundle bytes for
# telemetry alongside Claude/Agent invocations (Codex pathway records this
# automatically via swarm-run).
#
# Accepts role-name in either form: "writer" or "agent-writer".

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib/paths.sh
source "$SCRIPT_DIR/_lib/paths.sh"

MODE="content"
if [[ "${1:-}" == "--manifest" ]]; then
  MODE="manifest"
  shift
fi

ROLE="${1:?usage: load-role.sh [--manifest] <role-name>}"
ROLE="${ROLE#agent-}"
FILE="$AGENTS_DIR/agent-$ROLE.md"

if [[ ! -f "$FILE" ]]; then
  echo "load-role.sh: role file not found: $FILE" >&2
  exit 1
fi

if [[ "$MODE" == "content" ]]; then
  cat "$FILE"
  exit 0
fi

# Manifest mode: emit JSON with persona-bundle byte counts. Best-effort:
# missing fragments (e.g. roles without an overlay) report 0 bytes rather
# than failing. ROLES_DIR comes from _lib/paths.sh.
SHARED_MD="$ROLES_DIR/agent-$ROLE/shared.md"

_bytes() {
  local f="$1"
  if [[ -n "$f" && -f "$f" ]]; then
    wc -c <"$f" 2>/dev/null | tr -d ' \n'
  else
    printf 0
  fi
}

ROLE_FILE_BYTES="$(_bytes "$FILE")"
SHARED_MD_BYTES="$(_bytes "$SHARED_MD")"
TOTAL_PERSONA_BYTES=$(( ${ROLE_FILE_BYTES:-0} + ${SHARED_MD_BYTES:-0} ))

if command -v jq >/dev/null 2>&1; then
  jq -n \
    --arg role "agent-$ROLE" \
    --arg role_file "$FILE" \
    --arg shared_md "$SHARED_MD" \
    --argjson role_file_bytes "${ROLE_FILE_BYTES:-0}" \
    --argjson shared_md_bytes "${SHARED_MD_BYTES:-0}" \
    --argjson total_persona_bytes "$TOTAL_PERSONA_BYTES" \
    '{role: $role, role_file: $role_file, shared_md: $shared_md, role_file_bytes: $role_file_bytes, shared_md_bytes: $shared_md_bytes, total_persona_bytes: $total_persona_bytes}'
else
  printf '{"role":"agent-%s","role_file":"%s","role_file_bytes":%d,"shared_md_bytes":%d,"total_persona_bytes":%d}\n' \
    "$ROLE" "$FILE" "${ROLE_FILE_BYTES:-0}" "${SHARED_MD_BYTES:-0}" "$TOTAL_PERSONA_BYTES"
fi
