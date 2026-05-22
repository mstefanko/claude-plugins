#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

require_file() {
  local path=$1
  [[ -f "$path" ]] || fail "missing required prompt file: $path"
}

require_contains() {
  local path=$1
  local needle=$2
  local label=$3
  grep -Fq -- "$needle" "$path" || fail "$path missing $label"
}

extract_invariants() {
  local path=$1
  awk '
    /^- \*\*One batched context pass\.\*\*/ { printing = 1 }
    printing { print }
    printing && /the file-mutating tool call\.$/ { exit }
  ' "$path"
}

require_file commands/run.md
require_file skills/bakeoff/SKILL.md
require_file skills/bakeoff-run/SKILL.md
require_file references/run-appendix.md
require_file CLAUDE.md

require_contains commands/run.md 'Use the `bakeoff-run` skill for the entire workflow.' 'bakeoff-run shim invocation'
require_contains commands/run.md 'If the `bakeoff-run` skill is unavailable' 'missing-skill stop rule'
require_contains skills/bakeoff/SKILL.md '`/bakeoff:run` must use the `bakeoff-run` skill.' 'core routing rule'
require_contains skills/bakeoff-run/SKILL.md 'name: bakeoff-run' 'bakeoff-run skill frontmatter'
require_contains skills/bakeoff-run/SKILL.md 'user-invocable: false' 'hidden bakeoff-run slash menu entry'
require_contains skills/bakeoff-run/SKILL.md 'references/run-appendix.md' 'appendix references'
require_contains skills/bakeoff-run/SKILL.md '--check --print-path' 'resolved CLI path capture'
require_contains references/run-appendix.md 'BAKEOFF_CLI="/absolute/path/printed/by/bakeoff-ensure-cli"' 'parallel helper resolved CLI placeholder'
require_contains references/run-appendix.md '"$BAKEOFF_CLI" research' 'parallel helper resolved CLI invocation'

claude_invariants=$(extract_invariants CLAUDE.md)
run_invariants=$(extract_invariants skills/bakeoff-run/SKILL.md)

[[ -n "$claude_invariants" ]] || fail 'could not extract CLAUDE.md /bakeoff:run invariants'
[[ -n "$run_invariants" ]] || fail 'could not extract bakeoff-run invariants'
[[ "$claude_invariants" == "$run_invariants" ]] || fail 'bakeoff-run invariants drifted from CLAUDE.md'

printf 'Prompt integrity OK\n'
