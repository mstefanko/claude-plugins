# Parallel Non-Build Split Implementation Plan

Date: 2026-05-21

Status: proposed

Scope: Claude plugin orchestration for optional parallel execution of independent
non-build Bakeoff runs; one small CLI hardening change first

## Recommendation

Add opt-in parallel execution for cleanly independent non-build split runs. Do
not limit the idea to code review, but do keep build mode out of scope.

The user-facing model should be:

- default single request: one normal Bakeoff run;
- default split or multi-lens request: validate all files, then run one after
  another;
- explicit parallel request: validate all files, then run independent non-build
  parts in parallel with a small concurrency cap.

The implementation should preserve Bakeoff's core shape: every part is still a
normal work-order file, every result is still a normal run directory, and any
cross-run synthesis is a separate follow-up request.

Do not add a batch work-order schema, a Go-backed split scheduler, a new
`/bakeoff:review-swarm` command, or continuation-specific parallel behavior in
PR1.

## Why Not Review-Only

Review multi-lens is the clearest first consumer, but the execution problem is
not review-specific. Current split guidance already supports independent
`gather`, `compare`, `analyze`, review-as-`gather`, and `build` parts, then
routes `gather` / `compare` / `analyze` through `bakeoff research` and build
through `bakeoff build`.

Valid non-review examples:

```text
/bakeoff:run research this auth flow from architecture, security, and UX lenses; run the lenses in parallel
/bakeoff:run analyze this incident separately from database, queueing, and frontend behavior angles in parallel
/bakeoff:run gather evidence for the migration risks of option A and option B in parallel
```

The mechanics are almost identical to review multi-lens: draft separate normal
work orders, validate them all, launch separate `bakeoff research` commands with
explicit run ids, then summarize the run artifacts.

The harder part is product semantics. Review has a natural bounded summary:
findings by lens, triage counts, overlap, clean lenses, and optional fix-plan
synthesis. General research does not always have a natural merged answer. A
parallel architecture/security/UX research request may need three independent
reports rather than one integrated conclusion.

For that reason, frame this as **parallel clean split**, not as a new generic
multi-lens schema. When the user asks for "lenses" outside review, those lenses
are just named independent split parts.

## Current Behavior And Constraints

Current work orders are singular, normal CLI inputs. `docs/work-orders.md`
states that Bakeoff has no batch work-order schema, and that split plugin runs
and multi-lens review are represented as separate normal work-order files.

Current split rules in `commands/run.md` and `skills/bakeoff/SKILL.md` are the
right eligibility gate:

- 2-3 obvious independent parts;
- each part has its own goal;
- each part has its own evidence surface or verifier;
- no part depends on another Bakeoff result;
- shared context fits in 1-2 repeatable sentences;
- each part maps to an existing work-order type.

Those rules should continue to decide whether a request can be split at all.
Parallel execution is an execution option after the split is valid, not a new
reason to split fuzzy work.

Current multi-lens review is stricter than generic split:

- it triggers only for explicit review-shaped separate-lens wording;
- each lens is one normal `type: "gather"` work order with
  `facet.id: "code-review"`;
- code-review triage is on by default;
- after completion, the plugin writes `<out>/<base>.multi-lens-summary.md`;
- synthesis is optional and must be drafted as a separate `type: "analyze"`
  work order.

Keep those review-specific summary rules. Use the same parallel execution
machinery underneath.

## Research Findings Incorporated

This plan folds in three investigation threads:

- Coordination fixes: parallel child runs are feasible if shared `latest`
  updates are hardened, child output is captured, concurrency is capped, and
  partial states are explicit.
- Default-run risk: the only required shared-code change is `UpdateLatest`.
  That can be made safe for existing single runs and sequential multi-lens if
  it preserves start-time `latest` semantics.
- Value versus bloat: wall-clock value is real for 2-3 long-running non-build
  runs, but it does not justify a batch schema, Go scheduler, or native task
  dependency yet.

Relevant existing implementation surfaces:

- `internal/ledger/ledger.go`: `UpdateLatest` shared-state behavior.
- `internal/commands/researchcmd/run.go`: `bakeoff research` creates a run dir,
  updates `latest`, runs providers, writes decision/report/meta/manifest, and
  optionally auto-triages code review.
- `internal/commands/researchcmd/run.go`: provider workers already run in
  parallel inside one research run, so parallel split multiplies that existing
  fanout.
- `internal/commands/shared.go`: heartbeat output is tied to child process
  output and should not be streamed directly from multiple children.
- `internal/buildworkspace/`: build mode has repository lock and worktree
  semantics, which is why build is excluded.

## Build Is Out Of Scope

Parallel build split should stay out of scope.

Reasons:

- Build mode mutates isolated worktrees and has repository-level setup and
  cleanup concerns.
- The build command already uses a repository lock around git worktree admin and
  source preflight.
- Build work has verifier, patch capture, protected-path, winner-selection, and
  cleanup semantics that are much heavier than research runs.
- A parallel build split would need queueing and failure semantics beyond this
  feature.

This plan is only for runs routed through `bakeoff research`: `gather`,
`compare`, `analyze`, and review-as-`gather`.

## Required CLI Hardening First

Do not launch parallel child runs until concurrent independent `bakeoff
research` starts are safe.

The known shared-state risk is `runs/latest`.

Today `internal/ledger/ledger.go::UpdateLatest` uses one fixed temp path,
`<out>/.latest.tmp`, then renames it to `latest`. Multiple concurrent runs
against the same `--out` directory can remove, link, or rename each other's temp
file. That can make a child run fail early or leave `latest` pointing to an
arbitrary sibling.

Fix this before parallel split:

1. Use a unique temporary file/link name in the output directory.
2. Rename the unique temp path to `latest` atomically.
3. Keep the text-file fallback atomic too: write unique temp, fsync/close,
   chmod, then rename to `latest`.
4. Preserve existing semantics: `latest` updates when a run starts, not when it
   completes.
5. Add a concurrency test that launches many `UpdateLatest` calls against one
   temp output directory and asserts:
   - no call fails;
   - `ResolveRunDir(out, "latest")` resolves to one of the known run ids;
   - no fixed shared temp file is left behind;
   - symlink and text fallback behavior still works.

Residual caveat after the fix: in parallel mode, `latest` still means "whichever
child run updated latest last." It does not mean "the parallel group" or "the
run that completed last." Parallel summaries must therefore always use explicit
run ids and `bakeoff show <run-id>` commands, never `latest`.

## User-Facing Contract

Sequential remains the default.

Existing approval:

```text
write and run
```

continues to mean: write all files, validate them, then run one after another.
This preserves current split and multi-lens behavior.

Do not rely on users remembering a new long phrase. When parallel execution is
available, the preview should present the execution choices inline and accept a
short explicit reply from that preview.

Recommended approval choices after an eligible preview:

- `sequential` or `write and run`: write files, validate all, then run one
  after another;
- `parallel`: write files, validate all, then run eligible non-build parts with
  the displayed concurrency cap;
- `show`: print JSON;
- any edit/change request: revise and re-preview.

The word `parallel` should count as approval only in the immediate context of a
preview that explicitly offers it as an option and names the write, validate, and
run consequences. Do not treat a stray earlier mention of parallelism as
approval.

Preview text should include:

- part/lens names;
- work-order file paths;
- run ids;
- commands;
- whether execution is sequential or parallel;
- concurrency cap;
- maximum simultaneous reviewer/provider worker count;
- whether child stdout/stderr will be captured instead of streamed;
- warning that `latest` is not meaningful for the parallel group;
- warning that already-started runs may spend budget even if another run fails.

Use a soft warning rather than a blocking warning for normal 2-3 part requests:
parallel saves wall-clock time but increases concurrent provider load. Escalate
to a stronger confirmation only when the user asks to exceed the default
parallelism cap or run more than three parts.

Example:

```text
This can run as 3 independent non-build Bakeoff runs.

Choose how to run them:

- `sequential` - write, validate, then run one after another.
- `parallel` - write, validate, then run up to 2 at a time.
- `show` - print the JSON before approving.

Parallel cost note: with 2 providers per run and parallelism 2, this can launch
up to 4 provider workers at once, followed by judge and triage phases. Child
output will be captured per run; I will report progress and summarize artifacts
after the runs settle. Already-started runs may spend budget even if another run
fails.
```

## Execution Design

Parallel execution should be plugin-side shell-process orchestration over normal
CLI commands, not a Go scheduler in PR1.

For each selected non-build part:

```text
bakeoff research <work-order> --run-id <base>.<part> [--out <dir>] [mode flags] --json --quiet
```

Use explicit run ids for every part. Never rely on auto-generated run ids or
`latest` for the final summary.

Run all validations before launching any child process. If any validation fails,
launch nothing, repair the generated JSON, show the final set again, and ask for
approval again.

Use `--json --quiet` for parallel child commands. `--quiet` alone is not enough:
normal human output can still interleave. `--json` makes the child command emit
machine-readable final summary output and disables normal human output. Capture
stdout and stderr per child command for debugging and summary construction.

Default concurrency cap:

```text
parallelism = 2
```

For three requested parts, run two first, then start the third only if no stop
condition has occurred. If the user explicitly asks to run all three at once,
the preview must show the larger provider fanout and require the exact parallel
approval phrase.

Do not implement provider-aware semaphores in PR1. A simple run-level cap is
easier to explain and sufficient for 2-3 parts.

## Failure Semantics

Sequential behavior should remain unchanged:

- split runs continue after exit `0`, `3`, or `4`;
- multi-lens review continues after `0`, treats `3` as unusual completed
  handoff, and stops on `4` before spending more lens budget;
- both stop on validation failure, exit `1`, exit `2`, exit `130`,
  interruption, or command failure.

Parallel mode cannot preserve the same "stop before spending more budget"
guarantee for already-started runs. It can only prevent queued runs from
starting and try to cancel active siblings.

Parallel stop policy:

- validation failure: launch nothing;
- exit `0`: completed;
- exit `3`: completed but unresolved/unusual handoff;
- exit `4`: decision-incomplete; record judge-only rerun advice for that run
  when applicable, stop starting queued parts, and cancel active siblings if
  feasible;
- exit `1` or `2`: failed; stop starting queued parts and cancel active
  siblings if feasible;
- exit `130` or user interruption: cancelled/interrupted; stop queued parts and
  summarize artifacts that exist;
- command launch failure: failed before run; summarize as no artifacts unless a
  run directory exists.

After the first stop condition:

1. do not start additional queued parts;
2. cancel active child processes if the orchestration layer can do so cleanly;
3. wait for active children to settle;
4. read artifacts for every part where a run directory exists;
5. write a partial summary.

Use explicit per-part states:

- `completed`;
- `completed_unresolved`;
- `decision_incomplete`;
- `failed`;
- `cancelled`;
- `not_started`;
- `launch_failed`;
- `untriaged`;
- `raw_unverified`.

Cancelled or failed runs may have sparse run directories because `latest` and
the run directory are created before provider artifacts complete. Summary
generation must tolerate missing `report.md`, `decision.json`, and triage files.

## Summary Behavior

Review multi-lens keeps its existing richer summary file:

```text
<out>/<base>.multi-lens-summary.md
```

For generic parallel clean split, write a separate lightweight summary when
parallel execution is used:

```text
<out>/<base>.split-summary.md
```

Use this structure:

```text
# Parallel Split Summary

Summary file: <path>

## Runs
## Results
## Caveats
## Next Commands
## Optional Synthesis
```

The summary should not invent an integrated answer. It should list each part,
run id, status, report path when present, decision kind when present, triage
state when relevant, and `bakeoff show <run-id>` commands. Existing sequential
split can keep its current conversation-level summary unless a separate change
explicitly adds persisted split summaries there too.

If the user wants one integrated answer, ask whether to draft a separate
`type: "analyze"` work order over the completed reports. That follow-up must
cite source run ids and report paths and must not invent findings unsupported by
the prior artifacts.

## Native Task Manager / Visibility

Native task manager support is useful for visibility, but it should not be a
correctness dependency.

Research notes:

- The `pcvelz/superpowers` fork uses Claude Code native task features to track
  planning and execution state, with embedded metadata because task metadata is
  not always retrievable as structured state:
  <https://github.com/pcvelz/superpowers>
- Upstream discussion on an earlier task-management PR noted the limitation that
  native tasks are session-scoped and less durable than committed plan files:
  <https://github.com/obra/superpowers/pull/344>
- A follow-up upstream PR explores dependency-aware parallel task execution with
  durable JSON plus task waves, which is closer to what robust orchestration
  would need:
  <https://github.com/obra/superpowers/pull/1117>

Recommendation:

- Use native task manager only opportunistically, when available, to show outer
  progress:
  - "Validate work orders";
  - "Run architecture research";
  - "Run security research";
  - "Run UX research";
  - "Write summary".
- Do not mirror provider-level heartbeats into native tasks.
- Do not depend on native tasks for resume, cancellation, correctness, or final
  status.
- Durable run directories and summary files remain the source of truth.

## Things Decided Against

### Always Parallel

Rejected.

Reasons:

- Sequential is easier to understand and cheaper when a stop condition appears.
- Parallel multiplies provider load: `parallelism * provider_count` worker
  processes, followed by judge and possible triage phases.
- Defaulting to parallel would surprise users who only approved multiple runs,
  not a concurrency fanout.

### Review-Only Parallel

Rejected as too narrow.

Review multi-lens is the easiest first example, but independent non-build
research and analysis lenses are legitimate. The existing clean-split rules
already provide the right guardrail.

### Build Parallelism

Rejected for this plan.

Build mode has worktree, verifier, patch, winner, protected-path, cleanup, and
repository-lock semantics. It needs a separate design if it is ever worth doing.

### New Batch Work-Order Schema

Rejected.

The current work-order contract is small and auditable. A batch schema would
need new validation, reporting, ledger, history, inspect, rerun, and partial
failure semantics. Separate normal work orders already solve the v1 need.

### Go-Backed Split Scheduler

Rejected for PR1.

A scheduler could eventually provide cleaner cancellation, concurrency caps, and
structured state. But adopting scheduler semantics means adding a new CLI
surface, tests, and artifact contracts. The current value does not justify that
yet.

### Prompt-Only Parallel Before CLI Hardening

Rejected.

Launching concurrent child runs before fixing `UpdateLatest` risks avoidable
run-start failures and confusing `latest` behavior.

### Automatic Cross-Run Synthesis

Rejected.

Generic research splits can produce complementary but not directly mergeable
answers. Automatic synthesis would blur source attribution and recreate the
orchestration complexity this feature is trying to avoid. Synthesis remains a
separate `type: "analyze"` run after explicit approval.

### Native Task Manager As Source Of Truth

Rejected.

Native tasks are useful for operator visibility, but they are session-scoped and
not part of Bakeoff's durable artifact model. Use them as a dashboard only.

## Implementation Work Breakdown

### PR1: Concurrent Run Hardening

Files:

- `internal/ledger/ledger.go`
- `internal/ledger/ledger_test.go`

Tasks:

1. Change `UpdateLatest` to use unique temp names.
2. Make symlink and text fallback paths both atomic.
3. Add concurrency tests for `UpdateLatest`.
4. Verify existing lookup safety tests still pass.
5. Run:

```bash
go test ./internal/ledger
```

Recommended broader smoke:

```bash
go test ./internal/ledger ./internal/commands/researchcmd ./internal/commands/buildcmd ./internal/commands/lscmd ./internal/commands/showcmd
```

### PR2: Plugin Contract For Parallel Non-Build Split

Files:

- `commands/run.md`
- `skills/bakeoff/SKILL.md`
- `README.md`
- `docs/work-orders.md`
- `docs/task-fit-test-scenarios.md`

Tasks:

1. Add inline approval choices for eligible split and multi-lens previews:
   `sequential`, `parallel`, and `show`.
2. Preserve `write and run` as a backwards-compatible sequential approval.
3. Restrict parallel eligibility to parts routed through `bakeoff research`.
4. Explicitly exclude `build`.
5. Add preview copy for concurrency cap, provider fanout, captured output,
   `latest` caveat, and failure semantics.
6. Specify `--json --quiet` for parallel child commands.
7. Add partial-state summary requirements.
8. Add docs that generic parallel split summaries are independent summaries,
   not synthesized answers.
9. Add manual scenarios:
   - plain split still sequential on `write and run`;
   - after an eligible preview, `parallel` runs only non-build parts in parallel;
   - `parallel` is not accepted before the preview offers it;
   - build-containing split is not eligible for parallel;
   - one parallel run exits `4`;
   - one parallel run fails while another succeeds;
   - summary does not use `latest`.

### PR3: Optional Visibility Layer

Only after PR2 is stable, add opportunistic native task-manager progress if the
environment exposes the needed tool.

Tasks:

1. Create top-level tasks for validation, each child run, and summary.
2. Update task states from the orchestration layer.
3. Keep all artifact and final-summary behavior unchanged when native tasks are
   unavailable.

This PR must be skippable without changing parallel execution semantics.

## Open Questions

- Should the default parallelism be fixed at `2`, or should explicit
  three-lens parallel requests allow `3` after a stronger warning?
- Should generic parallel split write `<out>/<base>.split-summary.md` for every
  completed parallel run, or only for partial/failure cases?
- Should cancelled child stdout/stderr be written into the child run directory
  or only retained in conversation/session logs?
- Should the plugin expose `continue remaining parts` for parallel split after a
  partial stop, mirroring `continue lenses`?

## Acceptance Criteria

- Default single runs are unchanged.
- Default split and multi-lens `write and run` remain sequential.
- Parallel execution requires choosing `parallel` from an eligible preview.
- Parallel execution never runs build work orders.
- All child runs use normal work-order files and explicit run ids.
- All work orders validate before any child run starts.
- Concurrent run startup does not race on `latest`.
- Parallel summaries use explicit run ids and never rely on `latest`.
- Failed, cancelled, skipped, and decision-incomplete parts are represented
  clearly in the summary.
- Native task-manager visibility, if added, is optional and non-authoritative.
