---
description: "Run an output-only design swarm and produce an execution-ready recommendation"
argument-hint: "<design-question-or-path> [--dry-run]"
---

# /swarmdaddy:design

Run a design-only swarm profile. This command gathers evidence, explores design
risks through analysis lenses, checks ambiguities, and closes with an
execution-ready recommendation. It must not open writer branches,
implementation handoffs, docs lanes, consolidated PRs, or `/swarmdaddy:do`
plan-prepare work.

## Argument

`$ARGUMENTS` - a design question, topic, or repo-relative/absolute path whose
contents define the design request. `--dry-run` validates the profile and
prints the graph without dispatching agents.

## What Happens

1. **Preflight:** verify Beads is available with the normal SwarmDaddy helper.
2. **Profile validation:** validate and activate the `design` preset/pipeline,
   including budget preview and route invariants.
3. **Permissions:** check read-only research and clarify permission presets.
4. **Dispatch:** run the active `design` pipeline only: research,
   prompt-variant analysis fan-out, clarify, and final recommendation.
5. **Terminal output:** write a recommendation and execution-ready plan. Do not
   create writer issues or a PR.

## Execute

Parse `$ARGUMENTS` first. If it contains `--dry-run`, remove that flag and stop
after the validation commands below.

Run preflight:

```bash
bash "$CLAUDE_PLUGIN_ROOT/bin/_lib/beads-preflight.sh" swarmdaddy
```

Validate the command profile. If the design request is a single existing file
path, pass that path to the dry run for budget estimation.

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" design --dry-run <optional-existing-path>
```

Check permissions:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" permissions check --role research --role clarify
```

If not a dry run, activate the design profile:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" design <optional-existing-path>
```

Then dispatch the `design` pipeline described by:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" pipeline show design
```

Create one parent Beads issue for the design request. Dispatch only the graph
from the `design` pipeline: research, exploration branches, clarify, merge, and
the final `agent-analysis` recommendation stage. Do not create work units,
writer/spec-review/review/docs issues, worktrees, merge operations, or pull
requests.

When spawning any Claude-backed subagent, load its role persona through:

```bash
bash "$CLAUDE_PLUGIN_ROOT/bin/load-role.sh" <role-name>
```

and inline that role text in the prompt.

## Final Design Contract

The final parent issue note must include:

```markdown
## Design Recommendation

### Recommendation
<chosen approach and why>

### Evidence
- <source, child id, or file:line> - <what it confirmed>

### Tradeoffs
<rejected alternatives and why they lose>

### Execution Plan
<ordered, implementation-ready steps without spawning a writer>

### Risks And Tests
<risks, mitigations, and validation needed before implementation>

### Open Questions
<unknowns that block or should be accepted explicitly>

## Status: COMPLETE | NEEDS_INPUT
```
