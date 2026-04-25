---
description: "Execute a phased implementation plan via the beads swarm pipeline"
argument-hint: "<plan-path> [--codex-review auto|on|off] [--risk low|moderate|high] [--decompose=off|inspect|enforce] [--force-simple <phase_id>] [--force-decompose <phase_id>] [--auto]"
---

# /swarmdaddy:do

Orchestrate a multi-agent swarm pipeline against a plan file. Routes each phase through research → analysis/debug + clarify → writer (worktree) → spec-review → review + docs, with per-role model selection.

## Argument

`$ARGUMENTS` — absolute or repo-relative path to a plan file with numbered phases, plus optional orchestration flags. `--codex-review` controls the opt-in Codex review lane when supported by the active preset; `--risk` is an operator override for high-risk routing decisions. `--decompose=off|inspect|enforce` overrides the active preset's plan-prepare mode for this run; `--force-simple` and `--force-decompose` override one phase classification; `--auto` allows non-interactive acceptance where the prepare policy permits it.

## What happens

1. **Preflight:** verify `bd where` succeeds in the current repo. If not, halt with setup instructions — do **not** auto-init.
2. **Load orchestration prompt:** the skill at `skills/swarmdaddy/SKILL.md` contains the full per-phase protocol. Follow it exactly.
3. **Plan-prepare:** inspect the plan, optionally decompose each phase into a `work_units.v2` artifact, and create writer/spec-review child issues only after the artifact is accepted.
4. **Per phase:** load the active preset/pipeline, create beads issues for that graph, spawn subagents in topological order, and use the deterministic work-unit executor for the writer/spec-review lane when a `work_units.v1` or `work_units.v2` artifact is present. Poll background writers, run validation before spec-review, merge only APPROVED unit branches into the integration branch, and close on APPROVED review.
5. **After all phases:** open exactly one consolidated PR into `main`.

## Execute

Follow the SKILL.md at `${CLAUDE_PLUGIN_ROOT}/skills/swarmdaddy/SKILL.md` for the full orchestrator protocol. The plan file to execute is: `$ARGUMENTS`.

When spawning any subagent, load its role persona via:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/bin/load-role.sh" <role-name>
```

and inline the output in the subagent prompt. Never instruct a subagent to `Read ~/.claude/agents/...` — that path will not exist after the cutover completes.
