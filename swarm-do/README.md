# swarm-do

Beads-backed multi-agent swarm orchestration for Claude Code. Plans execute through a research → analysis → writer → review pipeline, with per-role backend routing across Claude and Codex.

## Status

Scaffold only. Orchestration assets (SKILL, agents, runners, roles, phase0 harness) land in Phase 2 of the packaging migration — see `~/cartledger/PLAN-swarm-plugin.md`.

## Commands

Populated in Phase 2:

- `/swarm-do:do <plan>` — main orchestrator
- `/swarm-do:resume <bd-id>` — re-enter a stalled pipeline
- `/swarm-do:debug <bd-id>` — agent-debug on an existing issue
- `/swarm-do:review <target>` — review-only on code / PR / branch
- `/swarm-do:research <question>` — ad-hoc research
- `/swarm-do:brainstorm <topic>` — pre-plan exploration
- `/swarm-do:compete <analysis-bd-id>` — Pattern 5 manual (gated)
- `/swarm-do:help` — decision tree

## Invariants

- Memory layer stays pluggable. No role file, command body, or runner script imports claude-mem-specific commands or data shapes. Memory interaction is via skills only.
- Beads coupling is accepted but disciplined: single `bd_preflight_or_die` helper, uniform flag patterns. No wrapper abstraction.
- Never edit the marketplace cache at `~/.claude/plugins/marketplaces/mstefanko-plugins/` expecting it to survive a `/plugin marketplace update`. Edit in the working clone, commit, push, update.

## Rollback

See Phase 8 in the packaging plan. Backup at `~/swarm-backup-*.tgz`.
