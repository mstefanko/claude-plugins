# ADR 0002: Pipeline Invariants And Evolution

Date: 2026-04-24

## Status

Accepted.

## Context

Swarm-do now supports named presets and YAML pipelines. That makes pipeline shape and backend routing operator-configurable, so validation has to distinguish ordinary preferences from structural facts of the runtime.

## Decision

The following invariants are hard rejects with no force override:

- The orchestrator resolves to a Claude backend. The `/swarm-do:do` skill runs inside the Claude session and owns `Agent()` dispatch, worktree coordination, and merge decisions.
- `agent-code-synthesizer` resolves to a Claude backend. It is the highest-risk merge step and combines implementation changes, so it stays on the Claude synthesis lane until a future ADR changes the architecture.
- Any `merge.strategy = synthesize` stage uses a Claude-backed merge agent. Synthesis is a merge decision, not just a parallel worker output.

These are structural invariants, not policy recommendations. A failing invariant means the pipeline cannot faithfully execute in the current architecture.

Budget ceilings are also hard rejects at dry-run and run start. They are declared in the preset's `[budget]` table so raising a ceiling requires an attributable file edit.

## Pipeline Evolution

Every stock pipeline carries `pipeline_version`. When a user forks a stock preset, `swarm preset save <new> --from <stock>` records `forked_from_hash = "sha256:<stock-preset-hash>"`. `swarm preset list` can then flag `fork-outdated` automatically when the stock preset hash changes. `swarm preset diff` shows the user-visible delta instead of relying on manual review.

Bump `pipeline_version` when stage IDs, dependencies, fan-out counts, merge semantics, failure tolerance, or role contracts change. Do not bump it for description-only edits.

## Consequences

Preset loading and pipeline linting can reject unsafe or stale shapes before a run creates beads issues. Operators can still experiment freely by editing presets and pipelines, but structural safety and budget authorization remain reviewable in files.
