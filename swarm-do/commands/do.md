---
description: "Execute a phased implementation plan via the beads swarm pipeline"
argument-hint: "<plan-path>"
---

# /swarm-do:do

Orchestrate a multi-agent swarm pipeline against a plan file. Routes each phase through research → analysis/debug + clarify → writer (worktree) → spec-review → review + docs, with per-role model selection.

## Argument

`$ARGUMENTS` — absolute or repo-relative path to a plan file with numbered phases.

## What happens

1. **Preflight:** verify `bd where` succeeds in the current repo. If not, halt with setup instructions — do **not** auto-init.
2. **Load orchestration prompt:** the skill at `skills/swarm-do/SKILL.md` contains the full per-phase protocol. Follow it exactly.
3. **Per phase:** create 7 beads issues (research, analysis/debug, clarify, writer, spec-review, review, docs), spawn subagents in the prescribed order, poll background writers, merge worktrees, and close on APPROVED review.
4. **After all phases:** open exactly one consolidated PR into `main`.

## Execute

Follow the SKILL.md at `${CLAUDE_PLUGIN_ROOT}/skills/swarm-do/SKILL.md` for the full orchestrator protocol. The plan file to execute is: `$ARGUMENTS`.

When spawning any subagent, load its role persona via:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/bin/load-role.sh" <role-name>
```

and inline the output in the subagent prompt. Never instruct a subagent to `Read ~/.claude/agents/...` — that path will not exist after the cutover completes.
