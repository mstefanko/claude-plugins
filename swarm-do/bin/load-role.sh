#!/usr/bin/env bash
# load-role.sh <role-name>
#
# Prints the content of agents/<role-name>.md from the plugin root. Used by
# the orchestrator skill to inject role personas directly into subagent
# prompts — sidesteps the unverified ${CLAUDE_PLUGIN_ROOT} expansion in
# Read-tool prose.
#
# Accepts role-name in either form: "writer" or "agent-writer".

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib/paths.sh
source "$SCRIPT_DIR/_lib/paths.sh"

ROLE="${1:?usage: load-role.sh <role-name>}"
ROLE="${ROLE#agent-}"
FILE="$AGENTS_DIR/agent-$ROLE.md"

if [[ ! -f "$FILE" ]]; then
  echo "load-role.sh: role file not found: $FILE" >&2
  exit 1
fi

cat "$FILE"
