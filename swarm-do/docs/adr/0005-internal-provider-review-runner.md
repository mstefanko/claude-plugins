# ADR 0005: Internal Provider Review Runner

Date: 2026-04-25

## Status

Proposed.

Intended to supersede: ADR 0003, after the internal runner passes its Phase 0
eligibility gates and becomes the preferred provider-review path.

## Context

ADR 0003 deliberately constrained provider stages to the opt-in MCO spike. That
kept the experiment bounded, but it also coupled normal provider review UX to a
separate CLI and a hardcoded provider list.

Operators should configure local Claude, Codex, and future review-capable
agents once through swarm-do routing and provider policy. A review stage should
then discover the eligible read-only review pool, run the selected providers,
and pass normalized evidence to downstream review without giving any provider
ownership of Beads, routing, memory, merges, or quality gates.

## Decision

Build a small swarm-owned `swarm-provider-review` runner and keep
`swarm-stage-mco` as the comparison spike.

- Add `provider.type = "swarm-review"` beside the existing `mco` stage type.
- Keep the MCO v1 provider-findings schema unchanged.
- Add a small model-facing emission schema under `schemas/provider_review/`.
- Add `provider-findings.v2-draft` for normalized internal runner artifacts.
- Use a shim registry for known providers rather than scanning arbitrary local
  commands.
- Fail closed for real provider eligibility until Phase 0 proves structured
  output, non-spend readiness checks, and read-only write denial.
- Let stock automatic review collect one eligible provider as evidence after
  its proof gates are green. Single-provider findings remain
  `needs-verification`; only exact stable-hash agreement from at least two
  schema-valid providers can produce `confirmed`.
- Keep secondary anchored clusters at `needs-verification` unless labeled
  captured samples show acceptable false merge and false split rates.
- Allow fake shims for deterministic runner, doctor, and DSL tests.

## Phase 0 Gates

Before Claude or Codex can be selected for stock automatic review, the runner
must prove:

- the exact command flags still exist,
- structured output can be validated locally,
- the selected read-only posture denies create, edit, and delete attempts in a
  temporary repo,
- doctor can distinguish installed/configured/readiness states without an
  unbounded review run or clearly labels a bounded spend probe,
- raw sidecar retention and redaction policy is documented and implemented.

Until those gates are green, real shims may appear in doctor diagnostics but are
not eligible for automatic selection.

## Consequences

MCO remains useful for comparison and dogfood, but normal provider-review
development moves to a smaller internal contract. Provider output remains
evidence only; downstream Claude-backed review decides how to use it.

Stock review-capable pipelines may include a `swarm-review` stage before real
Claude/Codex eligibility is complete because the runner fails closed and records
`skipped` when no read-only shim is eligible. This wires the operator UX without
turning on real provider execution prematurely.

ADR 0003 should be marked superseded only after `swarm-review` has validated
runner fixtures, doctor behavior, read-only eligibility, and at least one
stock-pipeline integration path.
