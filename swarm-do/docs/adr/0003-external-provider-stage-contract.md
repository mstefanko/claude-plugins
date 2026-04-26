# ADR 0003: External Provider Stage Contract

Date: 2026-04-24

## Status

Accepted for the experimental MCO comparison path.

ADR 0005 defines the internal `swarm-review` runner. Its stock
skipped-by-default evidence stage is governed by ADR 0005's Phase 0 gates, not
by the MCO validation gate below. This ADR continues to constrain `mco` stages
until it is formally superseded.

## Context

Phase 10 shipped local presets and pipelines with two executable stage shapes:
`agents` and `fan_out`. Section 1.11 identifies MCO as the first external
provider candidate because it can fan out across non-native model providers and
return machine-readable review artifacts.

That capability is useful only if it stays inside swarm-do's ownership
boundaries. Beads remains the task state. The `/swarm-do` orchestrator owns
pipeline state, routing decisions, worktree coordination, merges, and quality
gate decisions. Telemetry remains the measurement surface.

## Decision

MCO may be evaluated only as an optional read-only stage provider. It is an
adapter, not a second orchestrator.

The first shipped surface is `swarm providers doctor`, which checks the local
backend commands required by the active/default pipeline and can optionally pass
through `mco doctor --json`. This command is useful even if provider stages are
never promoted because it gives operators one place to verify local backend
readiness before a run.

After the MCO spike produced enough signal to continue, experimental
`provider` stages must obey these boundaries:

- `agents`, `fan_out`, and `provider` remain mutually exclusive stage kinds.
- v1 provider stages allow `provider.type = "mco"` only.
- The opt-in lab pipeline uses read-only `provider.command = "review"` only.
- Provider memory defaults to disabled and must be explicit to enable.
- Raw provider output is stored under the swarm run artifact directory.
- Normalized provider findings use a new schema version or provider-findings
  schema; frozen v1/v2 findings schemas are not mutated.
- Provider results are evidence for later Claude-backed stages, not automatic
  accept/reject decisions.
- Provider stages cannot own beads issues, routing state, pipeline state, memory,
  merges, or quality gate decisions.

## Validation Gate

Do not add provider stages to stock pipelines until the spike demonstrates that
MCO:

- emits parseable JSON in at least 95% of read-only review runs,
- fails closed on malformed output,
- classifies provider failures clearly,
- keeps repo writes disabled in review mode, and
- exposes at least one consensus or dedupe field worth importing into
  swarm-do telemetry.

If those properties do not hold, keep `swarm providers doctor` and retire the
provider-stage DSL before it hardens.

## Consequences

The CLI can grow a small provider health surface without committing to a third
pipeline stage kind. Any later provider DSL work must carry explicit telemetry,
schema-versioning, artifact-retention, and operator-disable stories before it
can become default behavior.
