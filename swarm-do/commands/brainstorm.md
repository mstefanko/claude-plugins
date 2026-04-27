---
description: "Run an output-only brainstorm swarm and produce a synthesis note"
argument-hint: "<topic-or-path> [--dry-run]"
---

# /swarmdaddy:brainstorm

Run a brainstorm-only swarm profile. This command explores options and closes
with a synthesis note. It must not open writer branches, implementation
handoffs, docs lanes, consolidated PRs, or `/swarmdaddy:do` plan-prepare work.

## Argument

`$ARGUMENTS` - a topic, question, or repo-relative/absolute path whose contents
frame the brainstorm. `--dry-run` validates the profile and prints the graph
without dispatching agents.

## What Happens

1. **Preflight:** verify Beads is available with the normal SwarmDaddy helper.
2. **Profile validation:** validate and activate the `brainstorm` preset,
   including budget preview and route invariants.
3. **Permissions:** check the read-only brainstorm permission preset.
4. **Dispatch:** run only the `brainstorm` fan-out and synthesize merge.
5. **Terminal output:** write a synthesis note with directions, tradeoffs, fast
   checks, and open questions. Do not create a PR.

## Execute

Parse `$ARGUMENTS` first. If it contains `--dry-run`, remove that flag and stop
after the validation commands below.

Run preflight:

```bash
bash "$CLAUDE_PLUGIN_ROOT/bin/_lib/beads-preflight.sh" swarmdaddy
```

Validate the command profile. If the brainstorm target is a single existing
file path, pass that path to the dry run for budget estimation.

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" brainstorm --dry-run <optional-existing-path>
```

Check permissions:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" permissions check --role brainstorm
```

If not a dry run, activate the brainstorm profile:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" brainstorm <optional-existing-path>
```

Then dispatch the graph described by:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" preset show brainstorm
```

Create one parent Beads issue for the brainstorm request. Create one child
issue per `agent-brainstorm` branch, giving each branch the same request plus a
distinct angle when a natural split is available. After quorum succeeds, create
the synthesize merge issue assigned to `agent-brainstorm`, dependent on
successful branches.

When spawning any Claude-backed subagent, load its role persona through:

```bash
bash "$CLAUDE_PLUGIN_ROOT/bin/load-role.sh" <role-name>
```

and inline that role text in the prompt.

## Final Note Contract

The final parent issue note must include:

```markdown
## Brainstorm Synthesis

### Goal Frame
<goal and constraints>

### Directions
- <direction and why it is promising>

### Tradeoffs
<tensions or decision points>

### Fast Checks
<questions, prototypes, or evidence that would narrow the choice>

### Open Questions
<unknowns that need human or research input>

## Status: COMPLETE | NEEDS_INPUT
```
