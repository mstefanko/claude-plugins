# MCO Review Prompt: 1.12c DAG Execution + Retry Cap

You are reviewing the `1.12c — DAG execution + retry cap` slice of a draft
architecture plan for `swarm-do`. Work read-only. Do not edit files or write
artifacts in the repository.

Primary plan file:

- `plans/swarm-do-1.12-orchestration-friction-fixes.md`

Relevant sections:

- Mapping rows 2, 4, 7, 11, and 12
- Metaswarm borrowing items:
  - per-work-unit commit contract
  - retry cap on `SPEC_MISMATCH`
  - orchestrator-side independent validation
  - adversarial review file:line contract
- Execution sub-phase:
  - `1.12c — DAG execution + retry cap`

Repository context to inspect:

- `swarm-do/skills/swarm-do/SKILL.md`
- `swarm-do/py/swarm_do/pipeline/engine.py`
- `swarm-do/py/swarm_do/pipeline/validation.py`
- `swarm-do/pipelines/default.yaml`
- `swarm-do/pipelines/hybrid-review.yaml`
- `swarm-do/roles/agent-spec-review/shared.md`
- `swarm-do/roles/agent-writer/shared.md`

Review questions:

- Is DAG execution specified in a way that fits the current pipeline engine, or
  does it imply a new orchestrator?
- Are per-work-unit commits safe with worktree isolation and integration branch
  merging?
- Does the retry cap have an unambiguous state transition model?
- Does the plan clearly separate spec-review from code-quality review?
- What validation/schema artifacts are missing before this can be implemented?

Findings desired:

- Blocking or high-risk flaws only.
- Every finding should include file:line evidence where possible.
- Prioritize merge-safety, retry-loop, and state-machine issues.
