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

  if ! command -v bd >/dev/null 2>&1; then
    printf '%s: bd CLI not on PATH\n' "$caller" >&2
    exit 1
  fi

  local rig
  rig="$(bd where 2>/dev/null || true)"
  if [[ -z "$rig" ]]; then
    cat >&2 <<EOF
$caller: no beads database found for this repo.

The swarm pipeline requires an existing beads rig. Choose one:

  1. Repo-local beads rig (recommended for cartledger-style projects):
       cd $PWD
       bd init --stealth

  2. Shared beads rig (single rig across multiple repos):
       export BEADS_DIR=/path/to/.beads

Then verify:
  bd where

Then rerun your swarm command.
EOF
    exit 1
  fi

  BEADS_RIG="$rig"
  export BEADS_RIG
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  bd_preflight_or_die "${1:-swarm-preflight}"
fi
