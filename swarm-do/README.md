# swarm-do

Beads-backed multi-agent swarm orchestration for Claude Code. Plans execute through a research → analysis → writer → review pipeline, with per-role backend routing across Claude and Codex.

## Status

Packaging migration is complete and `docs/plan.md` is the canonical roadmap.
Preset/pipeline routing, telemetry ledgers, rollout status, provider doctoring,
resume helpers, and the TUI MVP are all in the plugin. Phase 0's standalone
Codex review harness is retained as an experiment surface only; normal dogfood
measurement now happens through plugin presets and telemetry.

## Commands

Shipped:

- `/swarm-do:do <plan>` — main orchestrator. Full beads pipeline per phase.
- `/swarm-do:init-beads` — explicit, idempotent `bd init --stealth` bootstrap for a repo.
- `/swarm-do:resume <bd-id>` — resume entrypoint keyed by the BEADS epic/run issue.
- `bin/swarm preset ...` — preset load/save/diff/list/clear/dry-run.
- `bin/swarm pipeline ...` — stock/user pipeline list/show/lint.
- `bin/swarm permissions ...` — role-scoped permission preflight, dry-run install, and rollback support.
- `bin/swarm providers doctor [--mco]` — local backend health checks plus optional `mco doctor --json`.
- `bin/swarm status` / `bin/swarm rollout ...` — rollout status and decision log.
- `bin/swarm resume <bd-id> [--json]` — resume manifest, checkpoint lookup, and drift reporting.
- `bin/swarm-spike [precompact|hook-context|writer-observability|all]` — operator harness for hook and live-signal proof artifacts.
- `bin/swarm compete <plan-path>` — manual Pattern 5 setup; validates and activates the competitive preset.
- `bin/swarm-validate <preset>` — validation gates for preset + pipeline loading.

Planned (packaging Phase 3 and Integration Phases 1–2):

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

The migration is reversible. A pre-migration backup lives at `~/swarm-backup-<timestamp>.tgz` — snapshot of the old fallback runner directory, `~/.claude/agents/agent-*.md`, and the thedotmack claude-mem `/do` skill with the original swarm fork edits.

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

> Several contract-level sections in this file and in `schemas/telemetry/README.md` are generator-backed — bounded by `<!-- BEGIN/END: generated-by ... -->` markers. Do not hand-edit inside those markers; run the relevant generator instead (see `## Roles` and `## bin/swarm-telemetry` sections below for the exact commands).

```
swarm-do/
├── .claude-plugin/plugin.json    Plugin manifest
├── commands/                     Slash-command surface (/swarm-do:*)
├── hooks/                        PreCompact hook wiring + checkpoint writer
├── permissions/                  Role-scoped permission preset fragments
├── skills/swarm-do/SKILL.md      Orchestrator prompt (fires on /swarm-do:do)
├── agents/agent-*.md             Per-role personas (15 roles)
├── bin/
│   ├── _lib/
│   │   ├── paths.sh              Plugin-root resolution (source from runners)
│   │   ├── beads-preflight.sh    Shared bd_preflight_or_die helper
│   │   ├── hash-bundle.sh        SHA-256 of role prompt bundle (interface: hash-bundle.sh <role> <backend> → 64-char hex)
│   │   └── normalize-path.sh     Canonical repo-relative path for stable hash input; strips WORKTREE_ROOT then REPO_ROOT prefix
│   ├── swarm-run                 M1 manual runner (one role, one beads issue)
│   ├── swarm-spike               Operator spike harness for hook/context/writer observability
│   ├── swarm                     Preset/pipeline CLI
│   ├── swarm-validate            Preset/pipeline validation shim
│   ├── extract-phase.sh          Findings extractor — thin shim; dispatches to python3 -m swarm_do.telemetry.extractors (Phase 4)
│   ├── swarm-telemetry           Read-only reporter for telemetry ledgers (Phase 9c) — see below
│   ├── swarm-gpt                 alias → swarm-run --backend codex
│   ├── swarm-claude              alias → swarm-run --backend claude
│   ├── swarm-gpt-review          alias → swarm-run --backend codex --role agent-codex-review
│   ├── codex-review-phase        Standalone Phase 0 experiment harness (not wired into /swarm-do:do)
│   └── load-role.sh              emit <plugin>/agents/agent-<role>.md for prompt injection
├── roles/agent-<role>/           Prompt bundles (shared.md + claude.md + codex.md overlays)
├── presets/                      Stock preset TOML files
├── pipelines/                    Stock pipeline YAML files
├── schemas/{preset,pipeline}.schema.json  Preset/pipeline JSON Schema contracts
├── schemas/telemetry/            JSON Schema ledger definitions (runs, findings, outcomes, adjudications, run_events, observations, knowledge) — see schemas/telemetry/README.md
├── tests/fixtures/               Synthetic ledger data for self-test and dev (generate-synthetic-runs.sh, 66 runs, 35 findings)
├── phase0/                       Standalone Phase 0 experiment artifacts
├── docs/history/                 Archived migration/spike summaries
└── docs/provenance/              Audit trail for the claude-mem unfork
```

## bin/swarm

Preset and pipeline registry CLI:

```sh
swarm preset list
swarm preset load <name>
swarm preset clear
swarm preset save <new-name> --from <current|preset-name>
swarm preset diff <name>
swarm preset dry-run <name> <plan-path>
swarm pipeline list
swarm pipeline show <name>
swarm pipeline lint <name-or-path>
swarm permissions check [--role <role>] [--scope repo|user] [--path <settings.json>]
swarm permissions install --role <role> [--dry-run] [--rollback] [--scope repo|user] [--path <settings.json>]
swarm providers doctor [--mco] [--json]
swarm mode claude-only|codex-only|balanced|custom
swarm status
swarm resume <bd-id> [--merge] [--json]
swarm run-state write --json-file <path|->
swarm run-state checkpoint [--source <name>] [--reason <name>]
swarm run-state clear
swarm rollout show [--json]
swarm rollout dogfood [--notes "..."]
swarm rollout set <path> <value>
swarm rollout history
swarm compete <plan-path> [--dry-run]
```

Active preset state lives at `${CLAUDE_PLUGIN_DATA}/current-preset.txt`. Fresh installs have no active preset; routing falls back to `backends.toml`, while the runtime uses the `default` pipeline.

Dispatcher state lives at `${CLAUDE_PLUGIN_DATA}/active-run.json`. The
dispatcher owns that file via `swarm run-state`; PreCompact and the
end-of-unit fallback both write `${CLAUDE_PLUGIN_DATA}/runs/<run_id>/checkpoint.v1.json`
and append `checkpoint_written` rows to `telemetry/run_events.jsonl`.

Spike proof artifacts live under
`${CLAUDE_PLUGIN_DATA}/runs/<run_id>/spikes/<spike-name>/` and include
`metadata.json`, `stdout.txt`, `stderr.txt`, `stdin.json`, and `result.json`.

Stock presets include `hybrid-review` for Phase 1 dogfooding. It keeps the default pipeline shape and adds a fail-open `agent-codex-review` lane after spec-review. `mco-review-lab` is an opt-in experimental read-only provider lane: it runs MCO's working Claude provider after writer and feeds that evidence to the normal Claude review stage. `competitive` remains the manual Pattern 5 preset for two-writer trials.

`swarm providers doctor` checks the local backend commands required by the active preset's pipeline, or the `default` pipeline when no preset is active. `--mco` additionally runs `mco doctor --json` and fails closed on missing, failing, or malformed MCO output. MCO is also checked automatically when the active pipeline contains an MCO provider stage; otherwise, without `--mco`, it is reported as skipped.

## Roles

Roles are the personas the swarm pipeline dispatches to; this inventory is generated from `role-specs/` — edit specs, then run `python3 -m swarm_do.roles gen readme-section --write`.

<!-- BEGIN: generated-by swarm_do.roles gen readme-section -->
| Name | Description | Consumers |
|------|-------------|-----------|
| `agent-analysis-judge` | Competitive analysis judge. Reads two competing agent-analysis outputs for the same task and produces a single authoritative work breakdown. Run after BOTH analysis instances close. Allowed to open source files only for items flagged UNVERIFIED in either analysis — reads notes, not files. | agents |
| `agent-analysis` | Swarm pipeline planner. Evaluates approaches and produces a concrete work breakdown for the writer. Trusts research notes — only opens source files for items marked UNVERIFIED. Runs in parallel with agent-clarify after research closes. | agents |
| `agent-clarify` | Swarm pipeline pre-flight checker. Reads research notes via bd show only — no source file access. Surfaces blockers and ambiguities before implementation begins. Runs in parallel with agent-analysis after research closes. | agents |
| `agent-code-review` | Thorough code reviewer combining Chain-of-Verification discipline with multi-domain analysis (quality, security, performance, design). Use for post-writer pipeline verification or standalone PR/branch/module reviews. | agents |
| `agent-code-synthesizer` | Code synthesis agent. Reads two completed writer implementations with complementary approach constraints and cherry-picks the best elements from each into a single unified implementation. Operates at function/method level only — never mixes within a single function or across incompatible data structures. Used in Pattern 6 — Code Synthesis. | agents |
| `agent-codex-review-phase0` | Cross-model reviewer (GPT-5.4 via Codex CLI). Specialized for blocking-issues only — types, null/nil edges, off-by-one, boundary conditions, parser/serializer mismatches, security boundaries. Invoked manually during Phase 0 validation. | agents |
| `agent-codex-review` | Blocking-issues-only pipeline reviewer (backend-neutral contract). Runs in the post-spec-review quality lane focused on types, null/edge cases, off-by-one, boundary conditions, and security-relevant bugs. | agents, roles-shared |
| `agent-debug` | Swarm pipeline bug analyzer. Replaces agent-analysis for phases tagged kind=bug. Produces a root-cause-first work breakdown — trigger, call chain, fix location, defense-in-depth — never symptom patches. | agents |
| `agent-docs` | Swarm pipeline documentation updater. Edits .md files and doc comments only — no source code. Reads writer notes to understand what changed before editing anything. Runs in parallel with agent-review after writer closes. | agents |
| `agent-research-merge` | Synthesizes parallel sub-research outputs into a single unified research report. Runs after all sub-researchers close, before clarify and analysis. Reads only beads notes — no source file access except for items explicitly flagged UNVERIFIED by sub-researchers. | agents |
| `agent-research` | Swarm pipeline fact-finder. Reads codebase, searches memory, gathers raw findings. No opinions or recommendations — pure discovery. Use at the start of a swarm pipeline before analysis or clarify. | agents |
| `agent-review` | Swarm pipeline verifier. Runs tests and confirms implementation matches analysis intent. Flags issues in notes only — does not edit files. Runs in parallel with agent-docs after writer closes. | agents, roles-shared |
| `agent-spec-review` | Swarm pipeline spec-compliance checker. Confirms the writer's code matches the work breakdown from analysis. Does NOT evaluate code quality — that is agent-review's job. Fast reject on acceptance-criteria mismatch. | agents, roles-shared |
| `agent-writer-judge` | Competitive implementation judge. Reads two completed writer implementations, evaluates using execution signals and code quality criteria, and selects the winning implementation. Primary decision criterion is test results (objective). Secondary criteria are edge case coverage, code quality, and pattern adherence. Used in Pattern 5 — Competitive Implementation. | agents |
| `agent-writer` | Swarm pipeline executor. Implements exactly what agent-analysis specified. Holds the merge slot for the duration of work. Reads analysis and clarify notes before writing any code. | agents, roles-shared |
<!-- END: generated-by swarm_do.roles gen readme-section -->

## bin/swarm-telemetry

Reporter and write utility for the telemetry ledgers. Read-only subcommands shipped in Phase 9c; `join-outcomes` write subcommand shipped in Phase 9d. As of Phase 3, all six subcommands (`dump`, `validate`, `query`, `report`, `sample-for-adjudication`, `join-outcomes`) are native Python. The old bash implementation has been deleted. `bin/swarm-telemetry` is a 9-line shim that sources `bin/_lib/python-bootstrap.sh` and execs `python3 -m swarm_do.telemetry.cli "$@"`. The `--test` flag runs `python3 -m unittest discover` (not a bespoke assertion harness).

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

<!-- BEGIN: generated-by swarm_do.telemetry.gen readme-section -->
| Subcommand | What it does |
|------------|--------------|
| `dump` | Pretty-print a JSONL ledger as a JSON array. |
| `join-outcomes` | Correlate findings with post-merge maintainer actions. |
| `purge` | Purge rows older than retention window |
| `query` | Execute SQL against all ledgers loaded into sqlite3 :memory:. |
| `report` | Stratified markdown report from runs.jsonl. |
| `sample-for-adjudication` |  Stratified random sample of non-adjudicated findings. |
| `validate` | Validate every ledger row against its JSON schema. |
<!-- END: generated-by swarm_do.telemetry.gen readme-section -->

**Environment:**

`CLAUDE_PLUGIN_DATA` sets the base data directory; telemetry lives at `$CLAUDE_PLUGIN_DATA/telemetry/`. If unset, defaults to `~/.claude/plugin-data/mstefanko-plugins/swarm-do`.

**Self-test:** `swarm-telemetry --test` runs `python3 -m unittest discover` against the full test suite. Add `--check-docs` to verify the generator-backed telemetry docs sections.

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
