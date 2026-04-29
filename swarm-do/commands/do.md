---
description: "Execute a phased implementation plan via the beads swarm pipeline"
argument-hint: "<plan-path>|<plan-path> --prepare --continue|--prepared <run-id> [--phase-sessions auto|off] [--codex-review auto|on|off] [--risk low|moderate|high] [--decompose=off|inspect|enforce] [--force-simple <phase_id>] [--force-decompose <phase_id>] [--auto]"
---

# /swarmdaddy:do

Orchestrate a multi-agent swarm pipeline against a plan file. Routes each phase through research → analysis/debug + clarify → writer (worktree) → spec-review → review + docs, with per-role model selection.

## Argument

`$ARGUMENTS` — absolute or repo-relative path to a plan file with numbered phases; `<plan-path> --prepare --continue` for opt-in auto-continue through the prepare gate when the deterministic artifact is clean enough; or `--prepared <run-id>` / `<prepared-artifact-path> --prepared` for an accepted prepared artifact. `--phase-sessions auto|off` controls the durable fresh-context phase queue for accepted prepared artifacts; `auto` means initialize or resume `phase_sessions.v1.json` and render phase-scoped context bundles instead of handing workers the full prepared plan. `--codex-review` controls the opt-in Codex review lane when supported by the active preset; `--risk` is an operator override for high-risk routing decisions. `--decompose=off|inspect|enforce` overrides the active preset's plan-prepare mode for legacy plan-path runs only; prepared runs ignore it because work units already live on the artifact. `--force-simple` and `--force-decompose` override one phase classification; `--auto` allows non-interactive acceptance where the prepare policy permits it.

## What happens

1. **Preflight:** verify `bd where` succeeds in the current repo. If not, halt with: `No Beads rig detected in this repo. Run /swarmdaddy:init-beads (or /swarmdaddy:quickstart for guided first-run setup) first.` Do **not** auto-init.
2. **Load orchestration prompt:** the skill at `skills/swarmdaddy/SKILL.md` contains the full per-phase protocol. Follow it exactly.
3. **Plan-prepare or prepared gate:** for normal plan paths, inspect the plan, optionally decompose each phase into a `work_units.v2` artifact, and create writer/spec-review child issues only after the artifact is accepted. For `--prepare --continue`, run `bin/swarm do <plan-path> --prepare --continue`; it auto-accepts only clean deterministic artifacts, then runs the same prepared-dispatch validation. If it prints `Status: NEEDS_INPUT`, stop and have the operator run `/swarmdaddy:prepare --accept <run-id>` after review. For `--prepared`, validate the accepted artifact with `bin/swarm do --prepared <run-id>` before creating any Beads children; skip plan prepare and do not invoke `agent-decompose`. When phase sessions are enabled, use `bin/swarm phases status/init/pump <run-id>` and `bin/swarm context render --run-id <run-id> --phase <phase-id> --role <role>` as the execution boundary.
4. **Per phase:** load the active preset, create beads issues for that graph, spawn subagents in topological order, and use the deterministic work-unit executor for the writer/spec-review lane when a `work_units.v1` or `work_units.v2` artifact is present. Poll background writers, run validation before spec-review, merge only APPROVED unit branches into the integration branch, and close on APPROVED review.
5. **After all phases:** open exactly one consolidated PR into `main`.

## Execute

Follow the SKILL.md at `${CLAUDE_PLUGIN_ROOT}/skills/swarmdaddy/SKILL.md` for the full orchestrator protocol. The plan file to execute is: `$ARGUMENTS`.

When spawning any subagent, load its role persona via:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/bin/load-role.sh" <role-name>
```

and inline the output in the subagent prompt. Never instruct a subagent to `Read ~/.claude/agents/...` — that path will not exist after the cutover completes.
