---
description: "Run an output-only research swarm and produce an evidence memo"
argument-hint: "<research-question-or-path> [--dry-run]"
---

# /swarm-do:research

Run a research-only swarm profile. This command gathers evidence and closes with
a memo or Beads synthesis note. It must not open writer branches, implementation
handoffs, docs lanes, consolidated PRs, or `/swarm-do:do` plan-prepare work.

## Argument

`$ARGUMENTS` - a research question, topic, or repo-relative/absolute path whose
contents define the research request. `--dry-run` validates the profile and
prints the graph without dispatching agents.

## What Happens

1. **Preflight:** verify Beads is available with the normal swarm-do helper.
2. **Profile validation:** validate and activate the `research` preset/pipeline,
   including budget preview and route invariants.
3. **Permissions:** check the read-only research permission preset.
4. **Dispatch:** run the active `research` pipeline only: parallel
   `agent-research` branches followed by `agent-research-merge`.
5. **Terminal output:** write a final evidence memo or Beads synthesis note with
   sources, conflicts, gaps, constraints, and open questions. Do not create a PR.

## Execute

Parse `$ARGUMENTS` first. If it contains `--dry-run`, remove that flag and stop
after the validation commands below.

Run preflight:

```bash
bash "$CLAUDE_PLUGIN_ROOT/bin/_lib/beads-preflight.sh" swarm-do
```

Validate the command profile. If the research request is a single existing file
path, pass that path to the dry run for budget estimation; otherwise run the dry
run without a path and treat the free-form request as the Beads issue body.

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" research --dry-run <optional-existing-path>
```

Check permissions:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" permissions check --role research
```

If not a dry run, activate the research profile:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" research <optional-existing-path>
```

Then dispatch the `research` pipeline described by:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" pipeline show research
```

Create one parent Beads issue for the research request. For the fan-out stage,
create one child issue per branch assigned to `agent-research`; each branch gets
the same request plus a distinct angle or file cluster when a natural split is
available. After the quorum succeeds, create the synthesize merge issue assigned
to `agent-research-merge`, dependent on successful branches.

When spawning any Claude-backed subagent, load its role persona through:

```bash
bash "$CLAUDE_PLUGIN_ROOT/bin/load-role.sh" <role-name>
```

and inline that role text in the prompt.

## Final Memo Contract

The final parent issue note must include:

```markdown
## Research Evidence Memo

### Answer
<concise evidence-backed answer, or "inconclusive" with why>

### Sources
- <file:line, Beads child id, or URL> - <what it confirmed>

### Conflicts
<conflicting evidence or "No conflicts found">

### Gaps And Open Questions
<unknowns that would need follow-up>

### Constraints
<facts future design or implementation must preserve>

## Status: COMPLETE | NEEDS_INPUT
```
