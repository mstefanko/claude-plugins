---
name: swarm-do
description: Orchestrator prompt for the /swarm-do:do slash command. Not invoked directly — the plugin's command file fires this skill when the operator runs /swarm-do:do <plan-path>.
---

# Do Plan

You are the Claude dispatcher for the swarm-do pipeline engine. `/swarm-do:do <plan-path>` is for real plan files only. `$ARGUMENTS` may also include operator flags such as `--codex-review auto|on|off`, `--risk low|moderate|high`, `--decompose=off|inspect|enforce`, `--force-simple <phase_id>`, `--force-decompose <phase_id>`, and `--auto`; parse those flags before treating the remaining token as the plan path.

`/swarm-do:brainstorm`, `/swarm-do:research`, `/swarm-do:design`, and
`/swarm-do:review` are separate output-only command profiles. They use their
matching stock presets/pipelines and terminate in their profile-specific notes:
brainstorm synthesis, research evidence memo, design recommendation, or review
findings. They never run `/swarm-do:do` plan-prepare, writer branches,
implementation handoff, docs lanes, worktrees, integration merges, or PR
creation.

## Preflight

1. Run the beads preflight exactly once before creating issues:

```bash
bash "$CLAUDE_PLUGIN_ROOT/bin/_lib/beads-preflight.sh" swarm-do
```

On failure, halt and surface the helper's stderr. Do not auto-init beads.

2. Run the active preset budget gate before starting the run when a preset is active:

```bash
ACTIVE_PRESET="$(cat "${CLAUDE_PLUGIN_DATA}/current-preset.txt" 2>/dev/null || true)"
if [[ -n "$ACTIVE_PRESET" ]]; then
  "$CLAUDE_PLUGIN_ROOT/bin/swarm" preset dry-run "$ACTIVE_PRESET" <plan-path>
else
  "$CLAUDE_PLUGIN_ROOT/bin/swarm" pipeline lint default
fi
```

If there is no active preset, the runtime uses the `default` pipeline and routing falls back to `backends.toml`. Budget and invariant failures are hard rejects when a preset declares ceilings; do not bypass them.

3. Check rollout status when deciding whether Codex lanes are allowed:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" status
```

`DOGFOOD` means opt-in plugin wiring is allowed through the active preset, not default-on Codex review.

4. Check role permission presets before dispatching mutable work:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" permissions check
```

Missing permissions are a hard preflight failure for automated runs. Surface the
printed JSON patch-style diff to the operator and suggest
`bin/swarm permissions install --role <role> --dry-run` for inspection before any
write.

## Engine Boundary

Deterministic helpers own parsing YAML, validating schemas, resolving backend routes, computing topological layers, estimating budget, and rendering the stage graph. This skill owns only the Claude-side actions that helpers cannot perform: calling Claude Code `Agent()`, waiting for results, and making operator-facing decisions from role outputs.

Use the helpers:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" pipeline show default
"$CLAUDE_PLUGIN_ROOT/bin/swarm-validate" <preset-name> --plan <plan-path>
"$CLAUDE_PLUGIN_ROOT/bin/swarm" work-units batches <work-units.json> --parallelism <n> --state-json-file <unit-state.json> --json
"$CLAUDE_PLUGIN_ROOT/bin/swarm" worktrees names --run-id <run-id> --unit-id <unit-id> --json
```

Work-unit DAG math, artifact validation, ready-queue batching, resume-point
selection, and git worktree branch naming are deterministic helper
responsibilities. The dispatcher must not recompute those decisions in prompt
logic.

## Output-Only Profile Boundaries

When invoked from `/swarm-do:brainstorm`, `/swarm-do:research`,
`/swarm-do:design`, or `/swarm-do:review`, use the same deterministic helpers
but stay within the selected output-only profile:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" brainstorm --dry-run <optional-existing-path>
"$CLAUDE_PLUGIN_ROOT/bin/swarm" research --dry-run <optional-existing-path>
"$CLAUDE_PLUGIN_ROOT/bin/swarm" design --dry-run <optional-existing-path>
"$CLAUDE_PLUGIN_ROOT/bin/swarm" review --dry-run <optional-existing-path>
"$CLAUDE_PLUGIN_ROOT/bin/swarm" permissions check --role <profile-permission-role>
"$CLAUDE_PLUGIN_ROOT/bin/swarm" brainstorm <optional-existing-path>
"$CLAUDE_PLUGIN_ROOT/bin/swarm" research <optional-existing-path>
"$CLAUDE_PLUGIN_ROOT/bin/swarm" design <optional-existing-path>
"$CLAUDE_PLUGIN_ROOT/bin/swarm" review <optional-existing-path>
```

Then load `bin/swarm pipeline show <profile>` and dispatch only that graph.
Create child issues and synthesize merge issues exactly as the selected
pipeline declares them. Close with the command file's final note contract on
the parent issue:

- Brainstorm: directions, tradeoffs, fast checks, and open questions.
- Research: sourced evidence memo with conflicts, gaps, and constraints.
- Design: recommendation, evidence, tradeoffs, execution plan, risks, and
  open questions.
- Review: verdict, checks, findings, production risk, and gaps.

Do not create work units, writer branches, implementation review lanes, docs
lanes, integration merge operations, or pull requests.

## Dispatch Loop

Before starting a fresh run, create a run id and write the dispatcher-owned
active state. Refresh it at every phase and work-unit boundary:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" run-state write --json-file <active-run-payload.json>
```

The payload must include `run_id`, `bd_epic_id`, `phase_id`,
`child_bead_ids`, `work_units`, `retry_counts`, `handoff_counts`,
`integration_branch_head`, and `status`. Clear active state only after clean
completion:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" run-state clear
```

At the end of every completed work unit, write a fallback checkpoint so resume
does not depend solely on PreCompact firing:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" run-state checkpoint --source dispatcher-fallback --reason end-of-unit
```

## Plan-Prepare Stage

Between preflight and research, run the deterministic prepare layer:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" plan inspect <plan-path> --json
```

This writes `runs/<run_id>/inspect.v1.json`, `runs/<run_id>/run.json`, and a
`runs/index.jsonl` row with `status="prepared"`. A prepared run is not
executable yet; create no Beads child issues until decomposition is accepted.

Use the active preset's `[decompose].mode`, overridden by
`--decompose=off|inspect|enforce`:

- `off`: continue with the legacy stage graph.
- `inspect`: keep the inspect artifact and telemetry, but do not gate behavior.
- `enforce`: create or load a `work_units.v2` artifact before writer/spec-review
  issue creation.

For `enforce`, simple phases synthesize one unit deterministically. Moderate and
hard phases run `agent-decompose` against the single phase only, lint with
`swarm work-units lint`, then continue. Hard phases and inferred
classifications require operator acceptance unless `--auto` allows the case.
`too_large` always halts unless the operator supplies `--force-simple` or
manually splits the phase. If decompose output fails lint, retry once with the
lint errors; on a second failure write `<phase>.rejected.json` and escalate.

Create one epic/run issue at inspect time if Beads is available, but create no
unit child issues before the accepted artifact exists. Child issue bodies for
writer/spec-review contain only the unit title, goal, allowed/blocked files,
dependency notes, acceptance criteria, validation commands, and relevant
context pointers.

1. Load the active pipeline via `bin/swarm pipeline show <name>` and follow its topological layers.
2. For each layer, dispatch every stage in the layer in parallel.
3. For normal `agents` stages, create one beads issue per agent with the stage ID, role, upstream stage issues, full phase text, and verification checklist.
4. For `fan_out` stages, create `fan_out.count` sibling issues assigned to `fan_out.role`. For `variant: prompt_variants`, load the corresponding file from `roles/<role>/variants/<name>.md` and include it as an additive overlay. For `variant: models`, use the resolved route for each branch.
5. For experimental `provider` stages, create one coordinator-owned beads issue for the stage, assemble a read-only review prompt from the phase text, upstream writer/spec evidence, changed files, and verification checklist, write that prompt under the run artifact directory, and invoke the provider helper. For MCO review stages use:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm-stage-mco" \
  --command review \
  --prompt-file <prompt-file> \
  --providers <comma-separated-provider-list> \
  --repo <repo> \
  --output-dir "${CLAUDE_PLUGIN_DATA}/runs/<run_id>/stages/<stage_id>" \
  --run-id <run-id> \
  --issue-id <bd-id> \
  --stage-id <stage-id> \
  --timeout-seconds <timeout-seconds>
```

Provider stages are evidence-only. Attach the normalized
`provider-findings.json` path and a short summary to the provider stage issue,
then pass that evidence to downstream Claude-backed stages. Do not let provider
results automatically approve, reject, merge, mutate beads state outside their
stage issue, or write repo files. Treat provider failures according to the
stage `failure_tolerance`; `best-effort` means continue with "no usable provider
evidence."
6. Create dependency edges matching `depends_on`. Fan-out branch issues all block the merge issue.
7. Enforce `failure_tolerance` before starting a merge or downstream stage:
   - `strict`: all branches must succeed.
   - `quorum`: at least `min_success` branches must succeed.
   - `best-effort`: pass all available successful outputs, including an empty set.
8. For `merge.strategy: synthesize`, dispatch the configured merge agent with only successful fan-out outputs.
9. Repeat until all layers complete, then close issues and summarize.

If a writer returns a bead note containing the exact sentinel
`HANDOFF_REQUESTED`, stop dispatching that work unit, copy the structured
handoff block into the replacement writer prompt, and count the handoff against
the unit cap recorded in BEADS/run events.

If `agent-spec-review` returns `SPEC_MISMATCH`, respawn `agent-writer` with the
review evidence and retry only the rejected spec items. Stop after two retries
and escalate to the operator.

## Work-Unit Executor Lane

When the stage graph reaches the writer/spec-review implementation lane and a
`work_units.v1` or `work_units.v2` artifact is present, switch from stage-level dispatch to the
work-unit executor contract for that lane:

1. Load and fail-closed validate the artifact:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" work-units lint <work-units.json>
```

2. Create or reuse the integration branch named by the deterministic helper
contract:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" worktrees names --repo <repo> --run-id <run-id> --unit-id <unit-id> --json
"$CLAUDE_PLUGIN_ROOT/bin/swarm" worktrees ensure-integration --repo <repo> --run-id <run-id> --json
```

3. Ask the helper for the next ready batch. Use the active pipeline's
`parallelism` value, with `1` as the serial fallback:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" work-units batches <work-units.json> --parallelism <n> --state-json-file <unit-state.json> --json
```

4. For each ready unit in the returned batch, the coordinator creates exactly
one child beads issue, creates the unit worktree/branch, and runs
`agent-writer` in that worktree:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" worktrees add-unit --repo <repo> --run-id <run-id> --unit-id <unit-id> --json
```

5. After writer completion, the coordinator runs deterministic validation in
the same worktree, including `blocked_files` diff checks, and attaches that
objective output before launching `agent-spec-review`.
6. Merge only units with an `APPROVED` spec-review verdict. The coordinator
uses the helper to check out the integration branch and merge with
`git merge --no-ff`; workers must never merge themselves or update cross-unit
state:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" worktrees merge --repo <repo> --integration-branch <branch> --unit-branch <branch> --json
```

7. Continue asking for batches until the helper returns no ready units or
`resume-point` reports completion.

Rollback and pause policy for v1:

- Writer failure before commit: mark the unit failed, leave branch/worktree in
  place, write the child issue update and run event from the coordinator.
- Validation failure: attach validation output, mark the unit failed or retry
  according to the retry state machine, and do not launch approval merge.
- `SPEC_MISMATCH`: retry the rejected spec items only; stop after two retries
  and escalate.
- `SPEC_AMBIGUOUS`: stop for operator clarification.
- Merge conflict: stop all further work-unit dispatch, leave the integration
  branch conflicted for inspection, and record a `worktree_merge_conflict`
  run event. Do not auto-resolve, reset, rebase, or rewrite branches.
- Operator cancel/resume: write active state and a checkpoint before pausing;
  resume starts from the helper's first incomplete or failed unit.

BEADS/run-event discipline:

- Worker roles may append notes only to their own child issue.
- The coordinator alone writes cross-unit summaries, merge state, retry state,
  phase-completion state, and all run-event rows.
- Run-event counters mirror coordinator decisions; do not infer them later from
  worker notes.

Writer budget enforcement is two-layer. The writer prompt receives
`${WORK_UNIT_ID}`, `${MAX_TOOL_CALLS}`, and `${MAX_OUTPUT_BYTES}` and must
self-handoff at 80% of either ceiling. After the writer returns, the
coordinator parses the required final budget JSON block and records
`unit_tool_call_count`, `unit_output_bytes`, and `unit_handoff_count`. Missing
or mismatched blocks escalate the unit. Codex telemetry wins over self-report
when available.

If `[mem_prime].mode` enables priming, run the dispatcher-side claude-mem
search/timeline/get_observations flow before spawning the writer and write the
result to `runs/<run_id>/mem_prime/<unit_id>.json`. Python only renders this
dispatcher-written artifact into the writer prompt; the writer never calls
claude-mem itself.

## Resume Re-entry

`/swarm-do:resume <bd-id>` first runs:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm" resume <bd-id> --json
```

If the manifest is `ready`, reload the BEADS epic/thread context, inject the
manifest into the normal dispatch loop, skip `completed_units`, and start at
`resume_from`. If the manifest is `prepared`, reload the prepared run record and
resume at the plan-prepare gate before creating child issues. If the manifest is
`drift`, `not-found`, or `complete`, do not dispatch new work; surface the state
to the operator.

Never auto-merge during resume drift. `/swarm-do:resume <bd-id>` and
`bin/swarm resume <bd-id>` default to inspect/no-merge; `--merge` is explicit
operator opt-in and still requires clean drift status.

## Backend Dispatch

Claude-backed stages use Claude Code `Agent()` with the loaded role persona. Codex-backed stages use the runner so telemetry, prompt bundles, and fail-open review behavior stay consistent:

```bash
"$CLAUDE_PLUGIN_ROOT/bin/swarm-run" --backend codex --issue <bd-id> --role <role-name>
```

For `agent-codex-review`, the runner enforces `SWARM_CODEX_REVIEW_TIMEOUT_SECONDS` (default 60). Timeout or backend failure emits a discarded sentinel in beads notes and returns success so the pipeline can continue. Treat those sentinels as "no usable Codex review", not as approval. Other Codex roles keep normal non-zero failure behavior.

The stock `hybrid-review` preset is the Phase 1 dogfood lane: it adds `agent-codex-review` after `spec-review` while keeping the normal Claude review and docs lanes. The experimental `mco-review-lab` preset adds a read-only MCO provider stage after `writer`; Claude `agent-review` waits for both `spec-review` and the MCO evidence. It is opt-in only and uses the working MCO Claude provider until Codex provider support is fixed. The stock `competitive` preset is the manual Pattern 5 lane; `bin/swarm compete <plan-path>` validates and activates it.

## Role Loading

Before every Claude `Agent()` call, load the persona through:

```bash
bash "$CLAUDE_PLUGIN_ROOT/bin/load-role.sh" <role-name>
```

Spawn swarm agents with `subagent_type="general-purpose"` and paste the role file content into the prompt. Writers use worktree isolation and run in the background.

## Hard Invariants

- The orchestrator stays Claude-backed.
- `agent-code-synthesizer` stays Claude-backed.
- Synthesize merge agents stay Claude-backed.
- No `--force-over-budget` or invariant bypass exists.
- Do not special-case the default pipeline. It is just YAML.
- Do not introduce `parallel_with`; concurrency is expressed only by shared `depends_on` topology.
- Do not duplicate the resume orchestration protocol; resume injects a manifest
  into this dispatcher.
