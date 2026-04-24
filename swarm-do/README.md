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
├── agents/agent-*.md             Per-role personas (15 roles)
├── bin/
│   ├── _lib/
│   │   ├── paths.sh              Plugin-root resolution (source from runners)
│   │   ├── beads-preflight.sh    Shared bd_preflight_or_die helper
│   │   ├── hash-bundle.sh        SHA-256 of role prompt bundle (interface: hash-bundle.sh <role> <backend> → 64-char hex)
│   │   └── normalize-path.sh     Canonical repo-relative path for stable hash input; strips WORKTREE_ROOT then REPO_ROOT prefix
│   ├── swarm-run                 M1 manual runner (one role, one beads issue)
│   ├── extract-phase.sh          Findings extractor — thin shim; dispatches to python3 -m swarm_do.telemetry.extractors (Phase 4)
│   ├── swarm-telemetry           Read-only reporter for telemetry ledgers (Phase 9c) — see below
│   ├── swarm-gpt                 alias → swarm-run --backend codex
│   ├── swarm-claude              alias → swarm-run --backend claude
│   ├── swarm-gpt-review          alias → swarm-run --backend codex --role agent-codex-review
│   ├── codex-review-phase        Phase 0 experiment harness (not wired into /swarm-do:do)
│   └── load-role.sh              emit <plugin>/agents/agent-<role>.md for prompt injection
├── roles/agent-<role>/           Prompt bundles (shared.md + claude.md + codex.md overlays)
├── schemas/telemetry/            JSON Schema v1 ledger definitions (runs, findings, outcomes, adjudications) — see schemas/telemetry/README.md
├── tests/fixtures/               Synthetic ledger data for self-test and dev (generate-synthetic-runs.sh, 66 runs, 35 findings)
├── phase0/                       Codex cross-model review experiment artifacts
└── docs/provenance/              Audit trail for the claude-mem unfork
```

## bin/swarm-telemetry

Reporter and write utility for the telemetry ledgers. Read-only subcommands shipped in Phase 9c; `join-outcomes` write subcommand shipped in Phase 9d. As of Phase 3, all six subcommands (`dump`, `validate`, `query`, `report`, `sample-for-adjudication`, `join-outcomes`) are native Python — ported from legacy bash in phases 3/1–3/6. The legacy bash implementation (`bin/swarm-telemetry.legacy`) has been deleted. `bin/swarm-telemetry` is a 9-line shim that sources `bin/_lib/python-bootstrap.sh` and execs `python3 -m swarm_do.telemetry.cli "$@"`. The `--test` flag runs `python3 -m unittest discover` (not a bespoke assertion harness).

```
swarm-telemetry query <sql>
swarm-telemetry report [--since Nd] [--role R] [--bucket K]
swarm-telemetry dump <ledger>
swarm-telemetry validate [<ledger>]
swarm-telemetry sample-for-adjudication --count N [--since Nd] [--output-root PATH]
swarm-telemetry join-outcomes [--since Nd] [--dry-run]
swarm-telemetry purge <args>
```

**Subcommands:**

| Subcommand | What it does |
|---|---|
| `query <sql>` | Loads all four JSONL ledgers into an in-memory SQLite database via `python3` (tables: `runs`, `findings`, `outcomes`, `adjudications`) and executes the given SQL. Useful for ad-hoc exploration. |
| `report` | Emits a stratified markdown report from `runs.jsonl`. Stratifies by `role`, `complexity`, `phase_kind`, or `risk_tag` (controlled by `--bucket`). **Never emits global means** — averaging `agent-docs` latency next to `agent-analysis` latency is the exact measurement bias this tool exists to prevent. Accepts `--since Nd` (last N days) and `--role R` filters. |
| `dump <ledger>` | Pretty-prints one ledger (`runs`, `findings`, `outcomes`, `adjudications`) as a JSON array via `jq -s .`. Returns `[]` for absent or empty ledgers. |
| `validate` | Validates every ledger row against the shipped JSON schemas, including types, enums, patterns, bounds, and `additionalProperties`. Exits 1 if any row fails; exits 0 if all rows pass (absent/empty ledgers are skipped with a warning). |
| `sample-for-adjudication` | **(Phase 9f — write subcommand)** Picks a stratified random sample of findings that do not already appear in `adjudications.jsonl` via `overridden_finding_ids`. Writes the existing phase0-style directory layout under `~/.swarm/phase0/runs/` when writable, or falls back to plugin data when running in the plugin sandbox. Accepts `--count N` (required), `--since Nd`, and `--output-root PATH`. |
| `join-outcomes` | **(Phase 9d — write subcommand)** Correlates findings with post-merge maintainer behavior and appends rows to `finding_outcomes.jsonl`. Scans merged PRs via `gh api` plus local git history, anchors each finding to the nearest matching merge commit, then checks whether any commit within 14 days touched the same file within a ±10 line window; if so, appends a `hotfix_within_14d` outcome row. Accepts `--since Nd` (default 30d) and `--dry-run` (prints what would be written without touching the ledger). Idempotent: re-running the same window produces no duplicate rows. **Manual invocation only** — no cron wiring until output proves useful. |
| `purge <args>` | **(Phase 9g — operator-only)** Purge rows older than a retention window per ADR 0001. Atomically rewrites each ledger via tempfile + fsync + os.replace to ensure durability on power loss. Accepts `--older-than Nd [--ledger <name>] [--dry-run]`. Not invoked from swarm-run; operator-invoked only to avoid implicit data loss. |

**Environment:**

`CLAUDE_PLUGIN_DATA` sets the base data directory; telemetry lives at `$CLAUDE_PLUGIN_DATA/telemetry/`. If unset, defaults to `~/.claude/plugin-data/mstefanko-plugins/swarm-do`.

**Self-test:** `swarm-telemetry --test` runs `python3 -m unittest discover` against the full test suite. As of Phase 3, 52 tests run (OK) with 19 skipped: 18 parity tests gate on `LEGACY_SCRIPT.exists()` and auto-skip after deletion, plus 1 pre-existing skip.

## bin/extract-phase.sh

Findings extractor for reviewer roles. The CLI surface is unchanged:

```
extract-phase.sh <findings-json-or-notes-md> <run-id> <role> <issue-id>
extract-phase.sh --test
```

As of Phase 4, `extract-phase.sh` is a thin 9-line shim that execs `python3 -m swarm_do.telemetry.extractors "$@"`. All extraction logic lives in `swarm-do/py/swarm_do/telemetry/extractors/`.

**Role dispatch** (in `extractors/__init__.py`):

| Role(s) | Extractor |
|---|---|
| `agent-codex-review` | `codex_review.extract` — parses `findings.json` (JSON list under `"findings"`) |
| `agent-review`, `agent-code-review` | `claude_review.extract` — parses reviewer markdown notes |
| any other role | skipped with a stderr warning (fail-open, exits 0) |

**Hashing:** `stable_finding_hash_v1` algorithm is unchanged from the Phase 9b bash implementation — same 4-field SHA-256 payload (`file_normalized|category_class|line_bucket|short_summary`), same hex encoding. Cross-backend dedup in the findings ledger is preserved.

**Self-test:** `extract-phase.sh --test` passes `--test` through to the Python entrypoint, which runs `python3 -m unittest discover`.

**Environment:** Same `CLAUDE_PLUGIN_DATA` variable as `swarm-telemetry`.
