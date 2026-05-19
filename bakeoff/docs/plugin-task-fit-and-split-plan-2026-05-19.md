# Plugin Task Fit And Split Plan

Date: 2026-05-19

Status: implementation plan

## Recommendation

Add a lightweight task-fit and clean-split check to the Claude plugin drafting
path. Keep Bakeoff itself small: no general decomposition agent, no DAG runner,
no recursive planner, and no work-order-list schema in v1.

The plugin should do two simple things before it drafts natural-language work
orders:

1. Warn when the request is a weak fit for Bakeoff and ask for human confirmation.
2. Suggest 2-3 separate work orders only when the split is obvious and each
   piece can run as a normal existing Bakeoff work order.

This belongs in the plugin instructions first, not the Go CLI. The Go CLI should
continue to own validation, execution, judging, verifier runs, reports, ledgers,
triage, and exit codes.

## What Changes For The User

The user-visible change is small and explicit:

```text
User: /bakeoff:run format these files

Bakeoff: This may not need Bakeoff because it is formatter-only work. Bakeoff
usually pays off when two independent providers can produce meaningfully
different evidence or patches, and when there is a verifier, scope, or citation
standard. Reply `draft anyway` to continue with Bakeoff, or tell me how to
narrow it.
```

For a large request with two or three independent goals, the plugin first shows
a short split proposal. If the user replies `split`, it shows a one-line summary
and full JSON for each work order, lists the filenames it will write, and asks
for one explicit `write and run` approval before writing or executing anything.

## Why This Shape

Bakeoff's current product promise is a thin, auditable launcher. The README says
it runs providers, captures artifacts, verifies or judges outputs, writes a
ledger, and does not apply patches or hide state outside the run directory
(`README.md:5`). It also says every run is small, pairwise, replayable, and
auditable, and that property erodes as scheduling, role coordination, shared
state, retries, and synthesis are added (`README.md:207-209`).

The local work-order contract is also single-object and pairwise. Work orders
are JSON/JSONC objects with `schema_version: 1`, exactly two providers, one
judge, budgets, a scope policy, and one workflow type (`docs/work-orders.md:3-5`).
The validator rejects non-object work orders (`internal/workorder/workorder.go:231-235`)
and requires exactly two providers (`internal/workorder/workorder.go:371-374`).
The CLI command surfaces also accept one work order path at a time:
`bakeoff research WORK_ORDER` (`internal/commands/researchcmd/research.go:28`)
and `bakeoff build WORK_ORDER` (`internal/commands/buildcmd/build.go:23`).

The research supports this conservative boundary. Anthropic's multi-agent
research writeup supports breadth-first parallel research for broad search
tasks, but also warns about high token costs and fewer parallelizable subtasks
in coding work. The local evidence memo captures the same caveat
(`docs/research-basis.md:20-24`). MAST reports that many multi-agent failures
come from specification and coordination issues, not just weak base models
(`docs/competitive-builds-evidence-2026-05-18.md:39-42`). Agentless is a useful
counterweight: a simple localize -> repair -> validate pipeline can compete with
heavier SWE-bench agents when the verifier is good
(`docs/research-basis.md:93-95`).

So the right move is not "more orchestration." It is "help users avoid bad
Bakeoff runs, and split only when the split is clean."

## Where It Belongs

Implement first in:

- `skills/bakeoff/SKILL.md`: shared policy used by Bakeoff-aware Claude flows.
- `commands/run.md`: concrete `/bakeoff:run` natural-language drafting behavior.

Required docs:

- `README.md`: one short sentence that Bakeoff may suggest separate work orders
  for cleanly independent large requests.
- `docs/work-orders.md`: one short note that split runs are separate normal work
  orders, not a new schema.
- `docs/task-fit-test-scenarios.md`: the manual regression checklist for this
  plugin-instructions-only behavior.

Do not change the Go CLI initially. The existing `validate`, `research`, and
`build` commands are enough for the light version.

## Proposed Plugin Behavior

### 1. Task-Fit Check

Run this check after parsing flags and existing-path detection, but before
drafting JSON from natural language. Existing work-order paths bypass both the
task-fit check and the clean-split check; the user already supplied the work
order and should get the current validate-and-run behavior.

If the request looks like a weak fit, the plugin should stop and ask for
confirmation instead of silently drafting. The gate is advisory, not a hard
block. The v1 opt-out should be conversational only: a clear phrase such as
`draft anyway` or "run Bakeoff anyway" satisfies the warning for that turn. Do
not add a plugin-only flag or a persistent "never warn me again" setting in v1.

The user-facing phrase should be "this may not need Bakeoff." Keep "task-fit
check" as the engineering label and "weak fit" as short internal wording.

Weak cases:

- Mechanical edits.
- Formatter-only work.
- Build requests with no meaningful verifier or acceptance criterion.
- Vague requests like "make it better" without a target, scope, or evidence
  standard.
- Review requests with no bounded branch, PR, diff, file set, or local-change
  scope.
- RCA/analyze requests with no concrete symptom, logs, reproduction, trace,
  files, incident, or command to inspect.
- Highly sequential planning where each answer depends on the prior result.

Do not warn solely because a request looks small or straightforward. The warning
should be based on an objective fit problem above, where Bakeoff is likely to
add cost, ambiguity, or risk without producing better evidence.

Suggested human-gate wording:

```text
This may not need Bakeoff because <reason>. Bakeoff usually pays off when two
independent providers can produce meaningfully different evidence or patches,
and when there is a verifier, scope, or citation standard. Reply `draft anyway`
to continue with Bakeoff, or tell me how to narrow it.
```

Examples:

```text
This may not need Bakeoff because it is formatter-only work. A normal
single-agent edit is likely cheaper and clearer. Reply `draft anyway` to
continue with Bakeoff, or tell me how to narrow it.
```

```text
This may not need Bakeoff because build mode needs at least one meaningful gate
verifier, such as a project test command, a regression test, or a benchmark
script. Reply `draft anyway` to continue with Bakeoff, or tell me the verifier
to use.
```

```text
This may not need Bakeoff because the RCA request has no concrete symptom, log,
trace, repro command, or file scope. Reply `draft anyway` to continue with
Bakeoff, or give me the symptom and evidence surface.
```

If the user confirms, restart the natural-language flow on the same request with
the task-fit warning considered satisfied for that turn. If the user narrows the
request, re-run the check on the revised prompt.

### 2. Clean-Split Check

Run this check only for natural-language requests after the task-fit check has
passed or been explicitly confirmed. If the task-fit gate fires, do not also
propose a split in the same response; wait for the user's confirmation or
revision, then restart the flow.

"Large" does not mean a token threshold. Treat a request as large for this
check when it describes at least two distinct goals or at least two unrelated
evidence surfaces or verifiers. Do not split existing work-order paths. Do not
run a decomposition agent. Do not invent a project plan. The plugin should
suggest a split only when it can see 2-3 obvious, independent work orders.

Suggest a split only when all conditions are true:

- There are 2-3 subtasks.
- Each subtask has its own goal.
- Each subtask has its own evidence surface or verifier.
- No subtask depends on another Bakeoff result.
- Shared context can be summarized in 1-2 sentences and repeated safely in each
  work order; long logs, diffs, or research packets should be scoped to one
  part, not duplicated across all parts.
- Each subtask maps to a normal existing work-order type: `gather`, `compare`,
  `analyze`, review-as-`gather` plus `code-review`, or `build`.

Do not suggest a split when:

- There are more than 3 parts.
- The parts form a sequence where later steps depend on earlier findings.
- The "split" would require shared state, cross-run synthesis, or a final merge
  agent.
- Any subtask would be under-scoped after the split.
- The user already supplied a valid work-order file.

Suggested split-proposal wording:

```text
This looks like it cleanly splits into <N> independent Bakeoff work orders:

1. <part one goal>
2. <part two goal>
3. <part three goal>

Each can run separately with the same shared context, and none depends on
another result. Reply `split` to draft separate work orders, or tell me to keep
it as one.
```

If the user declines, draft one normal work order if the task is still valid. If
the user approves, draft each work order separately.

When drafting split work orders, put a one-line summary above each JSON block.
Each part gets focused `goal` and `background`: a short shared request summary
plus that part's specific evidence surface, verifier, scope, and constraints.
If the user asks to change one part, rebuild the set as needed and show all
final JSON blocks again before writing. One approval covers only the currently
shown set.

## Lightest Run Model

Use separate existing Bakeoff calls, run sequentially from the plugin.

Flow:

1. Parse flags once from `/bakeoff:run` and decide whether the remaining input
   is an existing path or natural language.
2. For existing work-order paths, preserve the current validate-and-run path and
   skip the new advisory checks.
3. For natural language, apply the task-fit check unless the user has already
   satisfied the warning for that turn with an explicit phrase such as
   `draft anyway`.
4. Apply the clean-split check after task fit is satisfied.
5. If split is accepted, draft `N` normal JSON work orders.
6. Show a one-line summary and full JSON block for each work order before
   writing anything.
7. List the filenames to be written and the commands to be run.
8. Ask for one explicit approval.
9. Write separate files:
   - `./<base-id>.part-1.work-order.json`
   - `./<base-id>.part-2.work-order.json`
   - `./<base-id>.part-3.work-order.json`
10. Validate all files with `bakeoff validate <path>` before running any part.
11. Run each file sequentially with the existing command:
   - `bakeoff research <path>` for `gather`, `compare`, and `analyze`;
   - `bakeoff build <path>` for `build`.
12. Summarize each run independently. Do not synthesize a new answer, patch, or
    decision across parts unless the user asks separately after the runs finish.

Validation and execution policy:

- Validate every generated file before running any of them.
- If any validation fails, stop before execution, surface the validation error
  verbatim, repair the affected JSON, and show the full final set again before
  asking for approval.
- During execution, continue after exit `0` and exit `3`. Exit `3` is a
  completed Bakeoff handoff with unresolved disagreement.
- Stop the sequence on exit `1`, exit `2`, exit `130`, or an interrupted command.
  Summarize completed parts and the failed part, then ask before running any
  remaining parts. These failures are likely to reflect runtime, config,
  validation, provider, verifier, or user-interruption problems that should not
  be multiplied automatically.

Run-id rule:

- Derive one base slug from the original request, then append `.part-N` for the
  generated work-order ids and filenames.
- If the user supplied `--run-id base`, pass `--run-id base.part-1`,
  `--run-id base.part-2`, and `--run-id base.part-3`.
- If no run id was supplied, let the CLI use each work-order id, which should
  already include the `.part-N` suffix.
- Apply the existing filename and run-id collision policies after appending
  `.part-N`. Do not overwrite unless the user explicitly asks to replace exact
  files.

Approval wording:

```text
Files to write:
- ./<base-id>.part-1.work-order.json
- ./<base-id>.part-2.work-order.json

Commands to run:
- bakeoff <research|build> ./<base-id>.part-1.work-order.json ...
- bakeoff <research|build> ./<base-id>.part-2.work-order.json ...

Write these files and run them one after another? Reply `write and run` to
continue, or tell me what to change.
```

This extends the existing one-work-order approval flow without adding a new file
format. Current plugin docs already require showing full JSON and waiting for
explicit approval before writing or running (`commands/run.md:114-126` and
`skills/bakeoff/SKILL.md:104-122`).

## Implementation Work Breakdown

1. Update `skills/bakeoff/SKILL.md`.

   Add a new section after `Work-Order Classification` and before `Drafting
   Rules` named `Task Fit And Clean Splits`.

   Include:

   - task-fit ordering and existing-path bypass;
   - weak-fit list;
   - conversational per-turn opt-out, with no flag and no persistent opt-out;
   - human-gate wording using `draft anyway`;
   - clean-split rules;
   - `.part-N` run-id and filename rules;
   - validation and execution failure policy;
   - explicit non-goals: no decomposition agent, no DAG, no work-order-list
     schema, no cross-run synthesis.

2. Update `commands/run.md`.

   In `Natural Language Drafting`, add the executable behavior:

   - insert the task-fit check before silent type inference and JSON drafting;
   - skip both advisory checks for existing work-order paths;
   - ask confirmation when weak fit changes safety, cost, or likely usefulness;
   - optionally propose 2-3 clean separate work orders;
   - show summaries plus all JSON before writing;
   - after approval, write and run each sequentially;
   - validate all parts before running any;
   - route each work order by its own `type`.

3. README/docs polish.

   Add one concise README note near the natural-language drafting or thin
   launcher section:

   ```text
   For large requests, the plugin may suggest 2-3 separate work orders when the
   split is clean. Each part is still a normal Bakeoff run.
   ```

   Add one concise `docs/work-orders.md` note:

   ```text
   Bakeoff has no batch work-order schema in v1. Split runs are represented as
   separate normal work-order files.
   ```

4. Add the manual validation checklist.

   Create `docs/task-fit-test-scenarios.md` and treat it as the regression
   checklist for this plugin-instructions-only behavior. No Go tests should be
   required for the first pass because the Go CLI is unchanged and there is no
   automated plugin-instruction harness today.

   Include at least these scenarios:

   - `format these files` -> weak-fit warning.
   - `build competing fixes but no verifier` -> asks for verifier or confirmation.
   - `review this diff` -> normal review draft.
   - `analyze why import retries duplicate receipts` with files/logs supplied ->
     normal analyze draft.
   - Large request with two independent research questions -> split suggestion.
   - Large sequential request where part 2 depends on part 1 -> no split
     suggestion.
   - Existing work-order path -> no task-fit or split warning.
   - Split validation failure -> no part executes before repair and reapproval.
   - Split exit `3` -> next part still runs; split exit `1` or `2` -> sequence
     stops and summarizes completed parts.

5. Optional examples follow-up.

   If dogfooding shows the split behavior is hard to visualize, add
   `examples/split/` with one canonical two-part prompt and generated work-order
   pair. Do not block v1 on this; the checklist doc is the required artifact.

## Rejected Alternatives

### General Decomposition Agent

Rejected for v1. It would add a hidden planning phase, consume more tokens, and
risk silently changing the user's actual request. It also pushes Bakeoff toward
the orchestration surface the README says it avoids.

### Work-Order List Schema

Rejected for v1. It would require new validation rules, run-id semantics,
partial-failure policy, ledger shape, report aggregation, and CLI command
behavior. The current schema intentionally represents one auditable work order.

### DAG Orchestration

Rejected. DAGs require dependency tracking, shared state, retries, cancellation
policy, and cross-run synthesis. That is the failure-prone coordination surface
the evidence tells us to avoid unless there is strong product demand.

### Automatic Cross-Run Synthesis

Rejected. If three runs produce three reports or patches, the plugin should not
merge them into a new final answer or patch. Synthesis is a new task and needs a
separate request plus fresh verification.

### More Providers For Big Requests

Rejected for this feature. The existing contract is exactly two providers and
one judge. Large requests should split into separate scoped two-provider runs
only when the split is clean.

### Persistent Opt-Out

Rejected for v1. A conversational per-turn override is enough for power users
who know they want Bakeoff despite the warning. A persistent setting would add
state and make the advisory safety/cost gate easy to forget.

### Marketplace Or Cross-Plugin Cleanup

Rejected for this plan. The local marketplace metadata can be improved
separately before publication, but it is not part of Bakeoff's task-fit and
split drafting behavior. The abandoned `swarmdaddy` plugin should not drive
Bakeoff copy or block this feature.

## Risks And Open Questions

- Over-splitting could increase cost and make evidence harder to read. Mitigate
  by requiring only 2-3 obvious independent parts.
- Weak-fit warnings could annoy users if too eager. Mitigate by warning only
  when usefulness, cost, or safety changes materially, and by accepting an
  explicit conversational override for that turn.
- Split run summaries need to stay separate. The plugin should avoid "overall
  winner" language unless a later user request asks for synthesis.
- Sequential execution is simple but slower than parallel execution. Keep it
  sequential until users repeatedly ask for batch behavior.
- Future overwrite or rerun behavior for split run ids needs care. Recommended
  v1 behavior: preserve the existing filename and run-id collision policy, and
  do not replace multiple generated parts unless the user explicitly confirms
  the exact run ids that will be replaced.
- If users repeatedly run accepted split sets, consider a tiny wrapper command
  later. Do not add it until dogfooding shows the separate-call flow is painful.
- Marketplace metadata is outside this implementation plan. If the marketplace
  is prepared for publication, handle `$schema`, `version`, `author`, and
  category polish in a separate maintenance change.

## Evidence Sources

- Anthropic Engineering, ["How we built our multi-agent research system"](https://www.anthropic.com/engineering/multi-agent-research-system):
  breadth-first parallel research can help broad search, but token cost and task
  fit matter.
- Cemri et al., ["MAST: A Multi-Agent Systems Failure Taxonomy"](https://arxiv.org/abs/2503.13657):
  coordination and specification failures are common enough that extra agents
  should be treated as extra surface area, not free quality.
- Xia et al., ["Agentless: Demystifying LLM-based Software Engineering Agents"](https://arxiv.org/abs/2407.01489):
  simple localize -> repair -> validate workflows are a serious baseline against
  heavier agent orchestration.
- The local Bakeoff evidence memo
  (`docs/competitive-builds-evidence-2026-05-18.md:39-58`) already applies those
  findings to the build harness: keep N=2, require gates, avoid DAGs and
  auto-synthesis, and treat provider-authored evidence carefully.

## Acceptance Criteria

The implementation is done when:

- `/bakeoff:run` warns before drafting weak-fit natural-language cases.
- The warning is advisory and can be overridden by explicit user approval.
- The plugin suggests splits only for 2-3 independent normal work orders.
- Split runs write separate normal work-order JSON files after one explicit
  approval.
- Split runs validate and execute sequentially through existing `bakeoff
  research` and `bakeoff build` commands.
- No Go CLI schema or command changes are required.
- The docs make clear that this is a plugin drafting aid, not a decomposition
  subsystem.
- `docs/task-fit-test-scenarios.md` exists and its checklist passes during
  manual command review or prompt-only dry run.
