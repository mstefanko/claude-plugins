---
description: "Prepare a plan for explicit acceptance before swarm execution"
argument-hint: "<plan-path> [--dry-run] [--auto-mechanical-fixes] | --accept <run-id> | --reject <run-id>"
---

# /swarmdaddy:prepare

Prepare a phased implementation plan and stop at the acceptance gate. This
command writes `prepared.md`, a `prepared_plan.v1.json` artifact, and
`work_units.v2` sidecars; it does not create writer issues, worktrees, merges,
or pull requests.

## Argument

`$ARGUMENTS` - either a repo-relative plan path, optionally with `--dry-run` or
`--auto-mechanical-fixes`, or a separate acceptance action:
`--accept <run-id>` / `--reject <run-id>`.

## What Happens

1. **Preflight:** verify Beads is available with the normal SwarmDaddy helper.
2. **Deterministic prepare:** run plan lint, canonical phase writing, phase
   inspection, and deterministic work-unit decomposition.
3. **Review boundary:** summarize model-labeled `safe_fix` proposals; do not
   auto-apply them under any flag.
4. **Acceptance gate:** print the prepared plan path, finding counts, work-unit
   count, allowed-file summary, validation-command summary, hashes, and git
   base. Stop with `Status: READY_FOR_ACCEPTANCE | NEEDS_INPUT | REJECTED`.
5. **Separate action:** only `--accept <run-id>` may transition a ready artifact
   to accepted, after schema, trust-boundary, and stale checks pass.

## Execute

Parse `$ARGUMENTS` first. If it contains `--dry-run`, remove that flag and stop
after the validation command below.

Run preflight:

```bash
bash "$CLAUDE_PLUGIN_ROOT/bin/_lib/beads-preflight.sh" swarmdaddy
```

For a new prepare run:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" prepare <plan-path> [--dry-run]
```

For acceptance or rejection:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" prepare --accept <run-id>
"$CLAUDE_PLUGIN_ROOT/bin/swarm" prepare --reject <run-id>
```

Do not dispatch the implementation graph from this command. A later
`/swarmdaddy:do --prepared` action consumes only an accepted prepared artifact.
