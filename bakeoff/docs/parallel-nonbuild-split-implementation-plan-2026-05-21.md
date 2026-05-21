# Parallel Non-Build Split Implementation Plan

Date: 2026-05-21

Status: proposed, trimmed after review

Scope: harden concurrent run startup, then add opt-in parallel fanout for
independent non-build split and multi-lens runs

## Recommendation

Ship a trimmed PR1 + PR2 sequence.

PR1 fixes the real shared-state blocker: concurrent `UpdateLatest` calls.

PR2 then adds the actual value: opt-in parallel fanout for independent
non-build split work. Keep PR2 small enough that it remains a thin execution
choice over normal work orders, not a new orchestration system.

Do not add build parallelism, a batch work-order schema, a Go scheduler, a
native task-manager dependency, generic persisted split summaries, or automatic
cross-run synthesis.

## Why PR2 Should Not Be Deferred

The previous revision over-trimmed by making PR2 conditional on future dogfood.
That misses the main value of the plan.

The valuable behavior is simple:

```text
validated normal work orders -> launch eligible `bakeoff research` runs in parallel -> summarize each normal run by explicit run id
```

Once `UpdateLatest` is concurrency-safe, the remaining PR2 coordination cost is
mostly prompt contract and shell fanout. It does not require a Go scheduler or
new artifact model.

Valid use cases are broader than review:

```text
/bakeoff:run review this diff with security, performance, and UX as separate lenses
/bakeoff:run research this auth flow from architecture, security, and UX lenses
/bakeoff:run analyze this incident separately from database and queueing angles
```

The right boundary is **non-build clean split**, not review-only.

## What Stayed Trimmed

The review was right about bloat. Keep these cuts:

- no PR3 native task-manager visibility;
- no generic `<out>/<base>.split-summary.md`;
- no nine-state result taxonomy;
- no prompt-level cancellation;
- no build mode;
- no batch schema;
- no Go-backed scheduler;
- no automatic synthesis.

## What Changed From The Review

This revision does **not** keep the fixed parallelism `2` recommendation.

There is no current evidence that three eligible non-build parts are
qualitatively riskier than two. The existing split and multi-lens contracts
already cap normal split size at 2-3 parts. If a user explicitly chooses
parallel execution for three eligible parts, running all three concurrently is
the clearest value path.

The real cost is linear provider fanout, and it can be shown directly:

```text
3 runs x 2 providers = up to 6 provider workers at once
```

That is a soft warning, not a reason to silently serialize one part. For more
than three parts, parallel fanout should not be offered in PR2.

## PR1: Concurrent `latest` Safety

### Problem

Today `internal/ledger/ledger.go::UpdateLatest` uses one shared temporary path:

```text
<out>/.latest.tmp
```

Concurrent runs against the same `--out` directory can remove, link, or rename
each other's temp path. That race exists even without parallel split, because
users can launch independent `bakeoff research` runs from multiple terminals or
scripts.

### Required Behavior

Preserve current semantics:

- `latest` updates when a run starts, not when it completes;
- `latest` remains a convenience pointer, not a parallel group pointer;
- `ResolveRunDir(out, "latest")` still supports symlink and text-file fallback;
- single runs and sequential split/multi-lens behavior are unchanged.

### Implementation Detail

Files:

- `internal/ledger/ledger.go`
- `internal/ledger/ledger_test.go`

Recommended helper shape:

- `writeLatestSymlinkAtomic(outDir, runID string) error`
- `writeLatestFileAtomic(outDir, runID string) error`

Algorithm:

1. Ensure `outDir` exists.
2. Create a unique temp path inside `outDir`, for example with
   `os.CreateTemp(outDir, ".latest.*.tmp")`.
3. Try to create a symlink temp target pointing to `runID`.
4. Atomically rename that unique temp path to `<out>/latest`.
5. If symlink creation is unsupported, fall back to a unique temp file:
   write `runID + "\n"`, sync, close, chmod `0600`, then rename to
   `<out>/latest`.
6. Clean up only the temp path created by the current call.

Do not use a fixed `.latest.tmp`. Do not remove another process's temp file.

### Tests

Add automated tests:

- many concurrent `UpdateLatest` calls against one temp output dir;
- after concurrency, `ResolveRunDir(out, "latest")` resolves to one of the known
  run ids;
- no fixed `.latest.tmp` artifact exists;
- existing symlink resolution and text fallback tests still pass;
- text fallback does not leave partial `latest` contents.

Run:

```bash
go test ./internal/ledger
```

Recommended smoke:

```bash
go test ./internal/ledger ./internal/commands/researchcmd ./internal/commands/buildcmd ./internal/commands/lscmd ./internal/commands/showcmd
```

## PR2: Opt-In Parallel Fanout

PR2 is a prompt-contract change to `commands/run.md`,
`skills/bakeoff/SKILL.md`, `README.md`, `docs/work-orders.md`, and
`docs/task-fit-test-scenarios.md`.

It should not change the Go work-order schema.

### Eligibility

Parallel fanout is available only when all of these are true:

- the request already qualifies for existing split or multi-lens drafting;
- there are 2-3 parts;
- every part routes through `bakeoff research`;
- no part is `type: "build"`;
- all generated work orders have explicit run ids;
- all generated work orders validate before launch.

If a split contains build, run sequentially or ask the user to remove the build
part from parallel fanout.

For more than three parts, do not offer parallel fanout in PR2.

### Approval UX

Do not add a global reserved phrase. This must stay compatible with
`docs/task-fit-prompt-repair-plan-2026-05-21.md`, which avoids new broad
reserved replies parallel to `draft anyway`.

After an eligible preview, show local choices:

```text
Choose how to run them:

- `sequential` - write, validate, then run one after another.
- `parallel` - write, validate, then run all 3 at once.
- `show` - print the JSON before approving.
```

Rules:

- `write and run` remains backwards-compatible sequential approval;
- `sequential` is accepted only in this preview context;
- `parallel` is accepted only in this preview context;
- a stray earlier mention of "parallel" is not approval;
- edits or questions require a revised preview before approval.

Use a soft warning, not a hard confirmation, for 2-3 eligible parts:

```text
Parallel cost note: 3 runs x 2 providers can launch up to 6 provider workers at
once, followed by judge and any triage phases. Child output will be captured per
run, and `latest` will point to one child run, not the group.
```

### Execution

All work orders are written and validated before any child command starts.

Each child command is a normal research run:

```text
bakeoff research <work-order> --run-id <base>.<part> [--out <dir>] [flags] --json --quiet
```

Use explicit run ids. Never use auto-generated run ids or `latest` in summaries.

Launch every eligible child concurrently, up to the existing 3-part cap. There
is no queue in PR2, so there is no not-started state after validation succeeds.

Use `--json --quiet` to avoid interleaved human output. Capture each child
stdout/stderr separately in temporary orchestration logs. The logs are not
Bakeoff decision artifacts; mention them only for failures.

Do not attempt prompt-level cancellation in PR2. Once launched, wait for all
children to settle. This is simpler and more honest than "cancel if feasible."

### Result Classes

Use three result classes:

| Class | Signals | Summary handling |
| --- | --- | --- |
| `completed` | exit `0` or exit `3` | Include report path, decision kind, and unresolved-disagreement caveat for exit `3`. |
| `decision_incomplete` | exit `4` | Include durable artifact paths when present and judge-only rerun guidance when applicable. |
| `failed` | exit `1`, exit `2`, exit `130`, launch failure, or missing required artifacts | Include command, exit code, stderr/log path if captured, and any artifacts that exist. |

Triage is an attribute, not a result class. A completed code-review child may be
`triage: yes`, `triage: no`, `triage: stale`, or `triage: dry_run`.

### Output

Do not add generic `<out>/<base>.split-summary.md` in PR2.

For generic parallel split, use the final conversation response:

- part name;
- run id;
- result class;
- report path when present;
- decision kind when present;
- triage state when relevant;
- `bakeoff show <run-id>` command;
- caveats for failed or decision-incomplete parts.

Review multi-lens keeps its existing
`<out>/<base>.multi-lens-summary.md` behavior because that is already part of
the multi-lens contract. If any lens fails or exits `4`, label that review
summary partial under the existing multi-lens rules.

If the user wants one integrated answer from generic split results, draft a
separate `type: "analyze"` work order over the completed reports. Do not
auto-synthesize.

### Manual Scenarios

Add scenarios to `docs/task-fit-test-scenarios.md`:

- existing split with `write and run` remains sequential;
- eligible non-build split preview offers `sequential`, `parallel`, and `show`;
- `parallel` before an eligible preview is not approval;
- `parallel` launches all 2-3 eligible non-build parts concurrently;
- split containing build does not offer parallel;
- one child exits `0`, one exits `4`, one exits `1`;
- final response uses explicit run ids and never `latest`;
- multi-lens parallel keeps the existing persisted multi-lens summary behavior.

## Native Task Manager

Native task-manager support is out of scope.

Prior research remains useful context:

- `pcvelz/superpowers` uses native tasks for visible planning/execution state:
  <https://github.com/pcvelz/superpowers>
- Upstream discussion noted native tasks are session-scoped and less durable
  than committed plan artifacts:
  <https://github.com/obra/superpowers/pull/344>
- A follow-up upstream PR explores durable JSON plus task waves:
  <https://github.com/obra/superpowers/pull/1117>

Conclusion: native tasks may be useful later as an optional dashboard, but they
are not part of PR1 or PR2. Durable Bakeoff run directories and final responses
remain the source of truth.

## Things Decided Against

### Deferring PR2 Until More Dogfood

Rejected.

The fanout is the value. After PR1 fixes `latest`, a trimmed PR2 can ship
without the removed bells and whistles.

### Fixed Parallelism `2`

Rejected.

There is no evidence that three eligible non-build parts are qualitatively worse
than two. Existing split rules already limit normal scope to 2-3 parts. Show the
fanout cost instead of silently serializing one part.

### Always Parallel

Rejected.

Parallel must be explicit. Sequential remains the default and
`write and run` remains sequential.

### Build Parallelism

Rejected.

Build mode has worktree, verifier, patch, winner, protected-path, cleanup, and
repository-lock semantics. It needs a separate design if it is ever worth doing.

### Generic `.split-summary.md`

Rejected for PR2.

Conversation-level summaries are enough. Persisted generic split summaries can
be reconsidered only if partial-failure behavior proves they are needed.

### Native Task Manager As Part Of This Plan

Rejected.

It is skippable and non-authoritative. Including it makes the plan larger than
the value justified.

### Automatic Cross-Run Synthesis

Rejected.

Generic research splits can produce complementary but not directly mergeable
answers. Synthesis remains a separately approved `type: "analyze"` run.

## Acceptance Criteria

### PR1

- `UpdateLatest` uses no shared fixed temp path.
- Concurrent `UpdateLatest` calls do not fail under test.
- `latest` resolves to one known run id after concurrent updates.
- Existing single-run and sequential behavior is unchanged.
- Ledger tests pass.

### PR2

- Existing `write and run` split and multi-lens behavior remains sequential.
- Eligible non-build previews offer local `sequential`, `parallel`, and `show`
  choices.
- `parallel` is accepted only after an eligible preview offers it.
- Parallel fanout launches all eligible 2-3 non-build children concurrently.
- Build work orders are never parallelized.
- Every child run has an explicit run id.
- All work orders validate before any child launches.
- Child runs use `--json --quiet`.
- Final summaries use explicit run ids and never rely on `latest`.
- Generic parallel split does not create `.split-summary.md`.
