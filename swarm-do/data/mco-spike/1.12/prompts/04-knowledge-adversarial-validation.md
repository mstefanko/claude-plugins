# MCO Review Prompt: 1.12d Knowledge Loop + Adversarial Contract

You are reviewing the `1.12d — Knowledge loop + adversarial contract` slice of
a draft architecture plan for `swarm-do`. Work read-only. Do not edit files or
write artifacts in the repository.

Primary plan file:

- `plans/swarm-do-1.12-orchestration-friction-fixes.md`

Relevant sections:

- Mapping rows 10, 11, and 12
- Superpowers borrowing item 1: brainstorming gate
- Metaswarm borrowing items:
  - orchestrator-side independent validation
  - adversarial review file:line contract
  - knowledge extraction at run close
  - hard-plan-review gate
- Execution sub-phase:
  - `1.12d — Knowledge loop + adversarial contract`
- Open question 3 about knowledge-base context bloat

Repository context to inspect:

- `swarm-do/skills/swarm-do/SKILL.md`
- `swarm-do/py/swarm_do/telemetry/registry.py`
- `swarm-do/py/swarm_do/telemetry/schemas.py`
- `swarm-do/schemas/telemetry/README.md`
- `swarm-do/roles/agent-spec-review/shared.md`
- `swarm-do/roles/agent-review/shared.md`
- `swarm-do/roles/agent-research/shared.md`

Review questions:

- Is `knowledge.jsonl` scoped tightly enough to avoid becoming a second memory
  system or context-bloat source?
- Is the file:line evidence contract enforceable with current role output
  shapes?
- Does orchestrator-side independent validation belong in 1.12d, 1.12c, or
  both?
- Is the regression-test generator too large for this sub-phase?
- What schema/versioning rules are missing?

Findings desired:

- Blocking or high-risk flaws only.
- Every finding should include file:line evidence where possible.
- Prioritize telemetry contract, context-bloat, and false-positive feedback
  loop risks.
