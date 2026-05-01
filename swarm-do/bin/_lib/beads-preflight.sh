#!/usr/bin/env bash
# beads-preflight.sh — single-source hard-stop for the beads rig requirement.
#
# Usage:
#   As a function: `source beads-preflight.sh; bd_preflight_or_die "<caller>"`
#   As a script:   `bash beads-preflight.sh [caller]`
#
# Behavior: runs `bd where`. On success, exports $BEADS_RIG and returns. On
# failure, prints the canonical remediation message and exits 1.
#
# NEVER auto-initializes beads. The operator must choose `bd init --stealth`
# or `BEADS_DIR` explicitly — that's the load-bearing contract documented in
# integration plan §2.7 and every swarm role file.

bd_preflight_or_die() {
  local caller="${1:-swarm}"
  local lib_dir swarm_bin payload rig
  lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  swarm_bin="$(cd "$lib_dir/.." && pwd)/swarm"

  if [[ ! -x "$swarm_bin" ]]; then
    printf '%s: bin/swarm not found next to beads preflight helper\n' "$caller" >&2
    exit 1
  fi

  payload="$("$swarm_bin" beads check --json 2>/dev/null || true)"
  rig="$(python3 -c 'import json,sys; p=json.load(sys.stdin); print(p.get("rig") or "")' <<<"$payload" 2>/dev/null || true)"
  if [[ -z "$rig" ]]; then
    printf 'No Beads rig detected in this repo. Run /swarmdaddy:init-beads (or /swarmdaddy:quickstart for guided first-run setup) first.\n' >&2
    exit 1
  fi

  BEADS_RIG="$rig"
  export BEADS_RIG
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  bd_preflight_or_die "${1:-swarm-preflight}"
fi
