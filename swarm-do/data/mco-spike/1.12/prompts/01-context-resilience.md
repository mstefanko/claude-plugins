# MCO Review Prompt: 1.12a Context Resilience

You are reviewing the `1.12a — Context resilience` slice of a draft
architecture plan for `swarm-do`. Work read-only. Do not edit files or write
artifacts in the repository.

Primary plan file:

- `plans/swarm-do-1.12-orchestration-friction-fixes.md`

Relevant sections:

- Origin signal
- Metaswarm borrowing item 1: PreCompact/SessionStart hook idiom + BEADS recovery
- Net-new items:
  - `1.12-N1. Writer token/tool-call budget`
  - `1.12-N3. Observer-as-hook`
  - `1.12-N4. Resume CLI and slash-command grammar`
  - `1.12-N5. Phase-level token budget preview`
- Execution sub-phase:
  - `1.12a — Context resilience`
- Open question 1 about PreCompact hook reliability

Repository context to inspect:

- `swarm-do/skills/swarm-do/SKILL.md`
- `swarm-do/bin/swarm`
- `swarm-do/bin/swarm-run`
- `swarm-do/py/swarm_do/pipeline/cli.py`
- `swarm-do/py/swarm_do/pipeline/rollout.py`
- `swarm-do/schemas/telemetry/*.schema.json`

Review questions:

- Is the checkpoint/resume design clear about BEADS as source of truth and
  checkpoint artifacts as derived state?
- Are the proposed hooks safe, observable, and testable without adding a second
  orchestration loop?
- Is writer handoff specified enough to implement without losing work or
  creating retry loops?
- Are the telemetry/schema choices compatible with the frozen `runs.v1` rule?
- What is the smallest useful spike before implementing 1.12a?

Findings desired:

- Blocking or high-risk flaws only.
- Every finding should include file:line evidence where possible.
- Call out missing contracts, impossible tests, unsafe defaults, or state
  authority ambiguity.
