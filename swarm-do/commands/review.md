---
description: "Run an output-only review swarm and produce a findings/evidence summary"
argument-hint: "<branch-pr-diff-or-path> [--dry-run]"
---

# /swarmdaddy:review

Run a review-only swarm profile. This command inspects an existing branch, PR,
diff, or code area and closes with a findings/evidence summary. It must not
open writer branches, implementation handoffs, docs lanes, consolidated PRs, or
`/swarmdaddy:do` plan-prepare work.

## Argument

`$ARGUMENTS` - a branch name, PR identifier, diff description, review question,
or repo-relative/absolute path whose contents define the review target.
`--dry-run` validates the profile and prints the graph without dispatching
agents.

## What Happens

1. **Preflight:** verify Beads is available with the normal SwarmDaddy helper.
2. **Profile validation:** validate and activate the `review` preset/pipeline,
   including budget preview and route invariants.
3. **Permissions:** check the read-only review permission preset.
4. **Dispatch:** run the active `review` pipeline only: rubric-lensed review
   fan-out and synthesized findings.
5. **Terminal output:** write a findings/evidence summary. Do not create a PR.

## Execute

Parse `$ARGUMENTS` first. If it contains `--dry-run`, remove that flag and stop
after the validation commands below.

Run preflight:

```bash
bash "$CLAUDE_PLUGIN_ROOT/bin/_lib/beads-preflight.sh" swarmdaddy
```

Validate the command profile. If the review target is a single existing file
path, pass that path to the dry run for budget estimation.

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" review --dry-run <optional-existing-path>
```

Check permissions:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" permissions check --role review
```

If not a dry run, activate the review profile:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" review <optional-existing-path>
```

Then dispatch the `review` pipeline described by:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" pipeline show review
```

Create one parent Beads issue for the review target. Create one child issue per
`agent-review` branch, including the target, rubric lens, changed-file hints,
and any available verification commands. After quorum succeeds, create the
synthesize merge issue assigned to `agent-review`, dependent on successful
branches. Provider stages, writers, spec-review, docs, worktrees, merge
operations, and pull requests are out of scope.

When spawning any Claude-backed subagent, load its role persona through:

```bash
bash "$CLAUDE_PLUGIN_ROOT/bin/load-role.sh" <role-name>
```

and inline that role text in the prompt.

## Final Review Contract

The final parent issue note must include:

```markdown
## Review Findings

### Verdict
APPROVED | NEEDS_CHANGES | INCONCLUSIVE

### Checks Run
- <command or inspection and result>

### Findings
1. <file:line or target reference> - <issue and evidence>

### Production Risk
<risk not covered by checks, or "No uncovered production risk found">

### Gaps
<missing context or "No gaps found">

## Status: COMPLETE | NEEDS_INPUT
```
