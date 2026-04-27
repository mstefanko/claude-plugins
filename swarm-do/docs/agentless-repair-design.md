# Agentless Repair Design

Date: 2026-04-27

`agentless-repair` is intentionally not a stock runnable preset yet. The
current pipeline DSL can express agent stages, provider review stages, fan-out,
and synthesize/vote merges. It cannot yet express deterministic candidate patch
artifacts, temp-worktree validation/reranking, or a non-mutating patch handoff
from one stage to another.

## Target Flow

```text
localization -> candidate unified diffs -> temp-worktree validation/rerank
  -> winning patch handoff -> normal writer/spec-review/provider-review/review
```

## Required Runtime Primitives

- Patch artifact format: each candidate must be a unified diff with metadata
  for source role/provider, touched files, assumptions, and validation commands.
- Temp-worktree lifecycle: create isolated worktrees, apply one patch per
  worktree, run validation, collect logs, and delete worktrees fail-open.
- Validation command contract: deterministic commands, timeout, environment,
  expected pass/fail handling, and output size caps.
- Rerank contract: compare candidates by validation success, diff size,
  localized blast radius, and test evidence; ties become `NEEDS_HUMAN`.
- Handoff contract: pass only the winning patch and evidence to the normal
  writer, which remains the single mutating actor.
- Telemetry fields: candidate count, validation result per candidate,
  selected candidate id, rejected candidate reasons, and rerank confidence.

## Open Decisions

- Whether localization reuses `agent-debug` or gets a narrower read-only
  `agent-localize-bug` role.
- Whether candidate generation is an agent fan-out, provider stage, or new
  deterministic patch primitive.
- Whether reranking writes findings/run notes first or waits for a dedicated
  candidate-outcome schema.

Until these decisions are made, use `repair-loop` for normal implementation
work and treat Agentless-style repair as a benchmark-oriented design track.
