# swarm-do

Beads-backed multi-agent swarm orchestration for Claude Code. Plans execute through a research → analysis → writer → review pipeline, with per-role backend routing across Claude and Codex.

## Status

Packaging Phases 0–6 complete. Phase 7 (final dogfood + M1 handoff verification) and cutover deletion of `~/.swarm/` + `~/.claude/agents/agent-*.md` originals are pending. See `~/cartledger/PLAN-swarm-plugin.md` for the migration context.

## Commands

Shipped:

- `/swarm-do:do <plan>` — main orchestrator. Full beads pipeline per phase.
- `/swarm-do:init-beads` — explicit, idempotent `bd init --stealth` bootstrap for a repo.

Planned (packaging Phase 3 and Integration Phases 1–2):

- `/swarm-do:resume <bd-id>` — re-enter a stalled pipeline
- `/swarm-do:debug <bd-id>` — agent-debug on an existing issue
- `/swarm-do:review <target>` — review-only on code / PR / branch
- `/swarm-do:research <question>` — ad-hoc research
- `/swarm-do:brainstorm <topic>` — pre-plan exploration
- `/swarm-do:compete <analysis-bd-id>` — Pattern 5 manual (gated on integration Phase 2)
- `/swarm-do:help` — decision tree

## Invariants

- **Memory layer stays pluggable.** No role file, command body, or runner script imports claude-mem-specific commands or data shapes. Memory interaction is via skills only.
- **Beads coupling is accepted but disciplined.** Single `bd_preflight_or_die` helper at `bin/_lib/beads-preflight.sh`, uniform flag patterns. No wrapper abstraction until a concrete alternative is under evaluation.
- **Never edit the install cache.** `~/.claude/plugins/cache/mstefanko-plugins/swarm-do/` is overwritten on `/plugin marketplace update`. Edit the marketplace clone at `~/.claude/plugins/marketplaces/mstefanko-plugins/swarm-do/`, commit, push, then `/plugin marketplace update mstefanko-plugins` + `/reload-plugins`.
- **Never auto-init beads.** `bd init --stealth` is always operator-invoked via `/swarm-do:init-beads` (or directly). The pipeline halts with a setup message if the rig is missing.

## Rollback

The migration is reversible. A pre-migration backup lives at `~/swarm-backup-<timestamp>.tgz` — snapshot of `~/.swarm/`, `~/.claude/agents/agent-*.md`, and the thedotmack claude-mem `/do` skill with the original swarm fork edits.

If swarm-do becomes unusable and you need the pre-packaging workflow back:

```sh
# 1. Uninstall the plugin.
/plugin uninstall swarm-do@mstefanko-plugins

# 2. Restore the originals. The tarball paths are absolute, so extract at /.
tar xzf ~/swarm-backup-<timestamp>.tgz -C /

# 3. Restore the fork edits to the claude-mem install cache.
cp ~/.claude/plugins/marketplaces/thedotmack/plugin/skills/do/SKILL.md \
   ~/.claude/plugins/cache/thedotmack/claude-mem/10.5.2/skills/do/SKILL.md
cp ~/.claude/plugins/marketplaces/thedotmack/plugin/skills/make-plan/SKILL.md \
   ~/.claude/plugins/cache/thedotmack/claude-mem/10.5.2/skills/make-plan/SKILL.md

# 4. Reload.
/reload-plugins

# 5. Verify the swarm fork is live again via claude-mem.
/claude-mem:do <some-plan-path>
```

The pre-migration entry point was `/claude-mem:do` (or bare `/do`, which claude-mem registers). After rollback, use that instead of `/swarm-do:do`.

The fork-diff patch that was active pre-rollback is preserved in `docs/provenance/fork-diff-<date>.patch` for audit — no need to reconstruct it from the tarball.

## Directory layout

```
swarm-do/
├── .claude-plugin/plugin.json    Plugin manifest
├── commands/                     Slash-command surface (/swarm-do:*)
├── skills/swarm-do/SKILL.md      Orchestrator prompt (fires on /swarm-do:do)
├── agents/agent-*.md             Per-role personas (14 roles)
├── bin/
│   ├── _lib/
│   │   ├── paths.sh              Plugin-root resolution (source from runners)
│   │   ├── beads-preflight.sh    Shared bd_preflight_or_die helper
│   │   └── hash-bundle.sh        SHA-256 of role prompt bundle (interface: hash-bundle.sh <role> <backend> → 64-char hex)
│   ├── swarm-run                 M1 manual runner (one role, one beads issue)
│   ├── swarm-gpt                 alias → swarm-run --backend codex
│   ├── swarm-claude              alias → swarm-run --backend claude
│   ├── swarm-gpt-review          alias → swarm-run --backend codex --role agent-codex-review
│   ├── codex-review-phase        Phase 0 experiment harness (not wired into /swarm-do:do)
│   └── load-role.sh              emit <plugin>/agents/agent-<role>.md for prompt injection
├── roles/agent-<role>/           Prompt bundles (shared.md + claude.md + codex.md overlays)
├── schemas/telemetry/            JSON Schema v1 ledger definitions (runs, findings, outcomes, adjudications) — see schemas/telemetry/README.md
├── phase0/                       Codex cross-model review experiment artifacts
└── docs/provenance/              Audit trail for the claude-mem unfork
```
