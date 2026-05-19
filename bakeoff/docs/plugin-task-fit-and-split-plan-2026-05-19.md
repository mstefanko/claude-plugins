# Plugin Task Fit And Split Plan

Date: 2026-05-19

Status: implementation plan

## Recommendation

Add a lightweight task-fit and clean-split check to the Claude plugin drafting
path. Keep Bakeoff itself small: no general decomposition agent, no DAG runner,
no recursive planner, and no work-order-list schema in v1.

The plugin should do two simple things before it drafts natural-language work
orders:

1. Warn when the request is a weak Bakeoff fit and ask for human confirmation.
2. Suggest 2-3 separate work orders only when the split is obvious and each
   piece can run as a normal existing Bakeoff work order.

This belongs in the plugin instructions first, not the Go CLI. The Go CLI should
continue to own validation, execution, judging, verifier runs, reports, ledgers,
triage, and exit codes.

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

Optional follow-up docs:

- `README.md`: one short sentence that Bakeoff may suggest separate work orders
  for cleanly independent large requests.
- `docs/work-orders.md`: one short note that split runs are separate normal work
  orders, not a new schema.

Do not change the Go CLI initially. The existing `validate`, `research`, and
`build` commands are enough for the light version.

## Proposed Plugin Behavior

### 1. Task-Fit Check

Run this check after parsing flags and before drafting JSON from natural
language.

If the request looks like a weak Bakeoff case, the plugin should stop and ask for
confirmation instead of silently drafting. The gate is advisory, not a hard
block.

Weak cases:

- Mechanical edits.
- Formatter-only work.
- One-clear-path fixes where a single normal agent is likely enough.
- Build requests with no meaningful verifier or acceptance criterion.
- Vague requests like "make it better" without a target, scope, or evidence
  standard.
- Review requests with no bounded branch, PR, diff, file set, or local-change
  scope.
- RCA/analyze requests with no concrete symptom, logs, reproduction, trace,
  files, incident, or command to inspect.
- Highly sequential planning where each answer depends on the prior result.

Suggested human-gate wording:

```text
This looks like a weak Bakeoff fit because <reason>. The evidence favors Bakeoff
when independent providers can produce different useful evidence or patches, and
when we have a verifier, scope, or citations to judge against. Continue anyway?
Reply `yes` to draft the work order, or tell me how to narrow it.
```

Examples:

```text
This looks like a weak Bakeoff fit because it is formatter-only work. A normal
single-agent edit is likely cheaper and clearer. Continue anyway?
```

```text
This looks like a weak Bakeoff fit because build mode needs at least one
meaningful gate verifier, such as `go test ./...`, a regression test, or a
benchmark script. Continue anyway, or tell me the verifier to use?
```

```text
This looks like a weak Bakeoff fit because the RCA request has no concrete
symptom, log, trace, repro command, or file scope. Continue anyway, or give me
the symptom and evidence surface?
```

If the user confirms, continue with the normal drafting flow. If the user
narrows the request, re-run the check on the revised prompt.

### 2. Clean-Split Check

Run this check only for large natural-language requests. Do not split existing
work-order paths. Do not run a decomposition agent. Do not invent a project
plan. The plugin should suggest a split only when it can see 2-3 obvious,
independent work orders.

Suggest a split only when all conditions are true:

- There are 2-3 subtasks.
- Each subtask has its own goal.
- Each subtask has its own evidence surface or verifier.
- No subtask depends on another Bakeoff result.
- Shared context is short enough to repeat safely in each work order.
- Each subtask maps to a normal existing work-order type: `gather`, `compare`,
  `analyze`, review-as-`gather` plus `code-review`, or `build`.

Do not suggest a split when:

- There are more than 3 parts.
- The parts form a sequence where later steps depend on earlier findings.
- The "split" would require shared state, cross-run synthesis, or a final merge
  agent.
- Any subtask would be under-scoped after the split.
- The user already supplied a valid work-order file.

Suggested wording:

```text
This looks like it cleanly splits into <N> independent Bakeoff work orders:

1. <part one goal>
2. <part two goal>
3. <part three goal>

Each can run separately with the same shared context, and none depends on
another result. Draft and run these as separate work orders? Reply `yes` to see
all JSON, or tell me to keep it as one.
```

If the user declines, draft one normal work order if the task is still valid. If
the user approves, draft each work order separately.

## Lightest Run Model

Use separate existing Bakeoff calls, run sequentially from the plugin.

Flow:

1. Parse flags once from `/bakeoff:run`.
2. Apply the task-fit check.
3. Apply the clean-split check.
4. If split is accepted, draft `N` normal JSON work orders.
5. Show all JSON blocks before writing anything.
6. Ask for one explicit approval.
7. Write separate files:
   - `./<base-id>-part-1.work-order.json`
   - `./<base-id>-part-2.work-order.json`
   - `./<base-id>-part-3.work-order.json`
8. Validate each file with `bakeoff validate <path>`.
9. Run each file sequentially with the existing command:
   - `bakeoff research <path>` for `gather`, `compare`, and `analyze`;
   - `bakeoff build <path>` for `build`.
10. Summarize each run independently. Do not synthesize a new answer, patch, or
    decision across parts unless the user asks separately after the runs finish.

Run-id rule:

- If the user supplied `--run-id base`, use `base-part-1`, `base-part-2`, and
  `base-part-3`.
- If no run id was supplied, let the CLI use each work-order id.
- Preserve the existing collision policy from `skills/bakeoff/SKILL.md:117-122`.

Approval wording:

```text
Write and run these <N> work orders sequentially? Reply `yes` to continue, or
tell me what to change.
```

This extends the existing one-work-order approval flow without adding a new file
format. Current plugin docs already require showing full JSON and waiting for
explicit approval before writing or running (`commands/run.md:114-126` and
`skills/bakeoff/SKILL.md:104-122`).

## Implementation Work Breakdown

1. Update `skills/bakeoff/SKILL.md`.

   Add a new section after `Work-Order Classification` named `Task Fit And
   Clean Splits`.

   Include:

   - weak-case list;
   - human-gate wording;
   - clean-split rules;
   - explicit non-goals: no decomposition agent, no DAG, no work-order-list
     schema, no cross-run synthesis.

2. Update `commands/run.md`.

   In `Natural Language Drafting`, add the executable behavior:

   - run task-fit check before drafting;
   - ask confirmation when weak fit changes safety, cost, or likely usefulness;
   - optionally propose 2-3 clean separate work orders;
   - show all JSON before writing;
   - after approval, write and run each sequentially;
   - route each work order by its own `type`.

3. Optional README/docs polish.

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

4. Manual validation.

   Use prompt-only dry runs or command review; no Go tests should be required
   because this first pass changes only plugin/docs behavior.

   Check these scenarios:

   - `format these files` -> weak-fit warning.
   - `build competing fixes but no verifier` -> asks for verifier or confirmation.
   - `review this diff` -> normal review draft.
   - `analyze why import retries duplicate receipts` with files/logs supplied ->
     normal analyze draft.
   - Large request with two independent research questions -> split suggestion.
   - Large sequential request where part 2 depends on part 1 -> no split
     suggestion.

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

## Risks And Open Questions

- Over-splitting could increase cost and make evidence harder to read. Mitigate
  by requiring only 2-3 obvious independent parts.
- Weak-fit warnings could annoy users if too eager. Mitigate by warning only
  when usefulness, cost, or safety changes materially.
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

- `/bakeoff:run` warns before drafting weak Bakeoff cases.
- The warning is advisory and can be overridden by explicit user approval.
- The plugin suggests splits only for 2-3 independent normal work orders.
- Split runs write separate normal work-order JSON files after one explicit
  approval.
- Split runs validate and execute sequentially through existing `bakeoff
  research` and `bakeoff build` commands.
- No Go CLI schema or command changes are required.
- The docs make clear that this is a plugin drafting aid, not a decomposition
  subsystem.
