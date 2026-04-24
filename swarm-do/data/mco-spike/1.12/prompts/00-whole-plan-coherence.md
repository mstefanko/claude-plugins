# MCO Review Prompt: Section 1.12 Whole-Plan Coherence

You are reviewing a draft architecture plan for `swarm-do`. Work read-only.
Do not edit files or write artifacts in the repository.

Plan under review:

- `plans/swarm-do-1.12-orchestration-friction-fixes.md`

Repository context:

- `swarm-do/docs/plan.md` contains the broader architecture plan.
- `swarm-do/docs/adr/0003-external-provider-stage-contract.md` defines the
  external provider boundary: MCO is an adapter, read-only first, not an
  orchestrator.
- `swarm-do/bin/swarm-stage-mco` and
  `swarm-do/schemas/telemetry/provider_findings.schema.json` are the current
  MCO spike surface.
- `swarm-do/skills/swarm-do/SKILL.md` describes the current Claude dispatcher.

Review scope:

- Review the full 1.12 plan for internal contradictions, sequencing problems,
  scope creep, hidden second sources of truth, and mismatches with the 1.11
  MCO adapter boundary.
- Focus on whether the plan can be chunked into safe, measurable dogfood phases.
- Check whether the plan accidentally makes MCO, hooks, checkpoints, or
  telemetry into an orchestrator or source of truth.

Findings desired:

- Blocking or high-risk flaws only.
- Every finding should include file:line evidence where possible.
- Prefer concrete fixes over broad advice.
- If the plan is sound, say so and identify the top residual risk.
