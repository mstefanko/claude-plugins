# MCO Review Prompt: 1.12b Preflight + Permissions

You are reviewing the `1.12b — Preflight + permissions` slice of a draft
architecture plan for `swarm-do`. Work read-only. Do not edit files or write
artifacts in the repository.

Primary plan file:

- `plans/swarm-do-1.12-orchestration-friction-fixes.md`

Relevant sections:

- Mapping rows 5 and 6
- Net-new item:
  - `1.12-N2. Role-scoped permission presets`
- Execution sub-phase:
  - `1.12b — Preflight + permissions`

Repository context to inspect:

- `swarm-do/skills/swarm-do/SKILL.md`
- `swarm-do/commands/init-beads.md`
- `swarm-do/bin/_lib/beads-preflight.sh`
- `swarm-do/py/swarm_do/pipeline/cli.py`
- `swarm-do/py/swarm_do/pipeline/providers.py`
- `swarm-do/py/swarm_do/pipeline/validation.py`

Review questions:

- Does the permissions plan avoid brittle grep/append behavior and preserve
  unrelated `settings.local.json` keys?
- Is `swarm permissions install` too risky as specified, or sufficiently
  bounded by parse/merge/backup/atomic-write constraints?
- Are the proposed preflight checks executable before any destructive work
  begins?
- Is `branch != main` compatible with the current plugin workflow, where the
  user may intentionally ask to work on `main`?
- Should this be one sub-phase or split into permissions first and external
  dependency stage second?

Findings desired:

- Blocking or high-risk flaws only.
- Every finding should include file:line evidence where possible.
- Call out safety hazards, operator UX traps, missing rollback behavior, or
  validation gaps.
