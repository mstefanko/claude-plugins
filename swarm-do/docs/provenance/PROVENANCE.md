# Provenance — swarm-do fork diff from claude-mem

This directory preserves the fork diff between our swarm orchestration edits and the upstream `thedotmack/claude-mem` plugin at v10.5.2, captured immediately before Phase 4 of the packaging migration ran a hard reset on the thedotmack marketplace clone.

## Why this exists

Before the swarm orchestration was packaged as its own plugin (`mstefanko-plugins/swarm-do`), the orchestration logic lived as in-place edits to `thedotmack/claude-mem`'s `/do` and `/make-plan` skill files inside Claude Code's marketplace cache. That arrangement was fragile — `/plugin update claude-mem@thedotmack` would wipe those edits silently.

Phase 4 of the packaging migration (see `~/cartledger/PLAN-swarm-plugin.md`) removes the fork by reverting the thedotmack marketplace clone's working tree, returning claude-mem to upstream pristine. The patch in this directory is the full audit trail of what was taken out.

## Files

- `fork-diff-2026-04-21.patch` — unified `git diff` output against `thedotmack` HEAD (`ecb09df42002`, "docs: update CHANGELOG.md for v10.5.2"). 336 lines. Touches `plugin/skills/do/SKILL.md` and `plugin/skills/make-plan/SKILL.md`.

## The edits, summarized

- **`skills/do/SKILL.md`** — rewritten as the swarm orchestrator: beads rig preflight, per-role complexity-model matrix, kind-routed analysis agent (feature/refactor → analysis, bug → debug), seven-role per-phase pipeline (research → analysis/debug + clarify → writer → spec-review → review + docs), worktree-isolated background writers, single-PR-per-plan final handoff. None of this was in upstream 10.5.2.
- **`skills/make-plan/SKILL.md`** — smaller changes (≈55 lines): likely early plan-file conventions that the swarm needed (complexity tags, kind tags) but that upstream's `/make-plan` didn't emit.

## Where this logic lives now

The orchestration is `~/.claude/plugins/marketplaces/mstefanko-plugins/swarm-do/skills/swarm-do/SKILL.md` as of Phase 2 of the migration — no longer dependent on the claude-mem skill surface.

## Restoring the fork (do not)

These edits are superseded by the swarm-do plugin. `fork-diff-2026-04-21.patch` exists only for audit, not for replay. If you need to replay it onto a fresh claude-mem clone for any reason:

```bash
cd ~/.claude/plugins/marketplaces/thedotmack
git apply "$CLAUDE_PLUGIN_ROOT/docs/provenance/fork-diff-2026-04-21.patch"
```

But don't — the swarm-do plugin is where this work belongs now.
