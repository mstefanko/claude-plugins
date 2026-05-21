#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

aggregate_limit=1100
run_target=60
core_target=180
appendix_target=200

count_lines() {
  local path=$1
  if [[ -f "$path" ]]; then
    wc -l < "$path"
  else
    printf '0\n'
  fi
}

print_count() {
  local path=$1
  local count=$2
  if [[ -f "$path" ]]; then
    printf '%5d %s\n' "$count" "$path"
  else
    printf '%5d %s (missing)\n' "$count" "$path"
  fi
}

command_lines=$(count_lines commands/run.md)
core_lines=$(count_lines skills/bakeoff/SKILL.md)
run_skill_lines=$(count_lines skills/bakeoff-run/SKILL.md)
appendix_lines=$(count_lines references/run-appendix.md)
aggregate=$((command_lines + core_lines + run_skill_lines))
status=0

printf 'Prompt line budget\n'
print_count commands/run.md "$command_lines"
print_count skills/bakeoff/SKILL.md "$core_lines"
print_count skills/bakeoff-run/SKILL.md "$run_skill_lines"
print_count references/run-appendix.md "$appendix_lines"
printf '%5d live /bakeoff:run aggregate\n' "$aggregate"
printf '%5d aggregate limit\n' "$aggregate_limit"

if (( aggregate > aggregate_limit )); then
  printf 'ERROR: live /bakeoff:run aggregate exceeds %d lines\n' "$aggregate_limit" >&2
  status=1
fi

if (( command_lines > run_target )); then
  printf 'WARN: commands/run.md exceeds %d-line design target\n' "$run_target" >&2
fi

if (( core_lines > core_target )); then
  printf 'WARN: skills/bakeoff/SKILL.md exceeds %d-line design target\n' "$core_target" >&2
fi

if (( appendix_lines > appendix_target )); then
  printf 'WARN: references/run-appendix.md exceeds %d-line design target\n' "$appendix_target" >&2
fi

exit "$status"
