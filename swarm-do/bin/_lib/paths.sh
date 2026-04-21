#!/usr/bin/env bash
# paths.sh — single-source resolution for swarm-do plugin paths.
#
# Sourced by every bin/swarm-* runner. Exports:
#   PLUGIN_ROOT  absolute path to the plugin directory
#   AGENTS_DIR   role persona files (agent-*.md)
#   ROLES_DIR    prompt bundles (shared + claude/codex overlays)
#   PHASE0_DIR   Phase 0 experiment artifacts (schema + rubric)
#
# Resolution rule: prefer ${CLAUDE_PLUGIN_ROOT} if Claude Code set it, else
# resolve from the sourcing script's location. Same value either way.

if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" ]]; then
  PLUGIN_ROOT="$CLAUDE_PLUGIN_ROOT"
else
  _paths_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  PLUGIN_ROOT="$(cd "$_paths_dir/../.." && pwd)"
  unset _paths_dir
fi

AGENTS_DIR="$PLUGIN_ROOT/agents"
ROLES_DIR="$PLUGIN_ROOT/roles"
PHASE0_DIR="$PLUGIN_ROOT/phase0"

export PLUGIN_ROOT AGENTS_DIR ROLES_DIR PHASE0_DIR
