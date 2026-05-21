# Parallel Non-Build Split Implementation Plan

Date: 2026-05-21

Status: proposed, trimmed after review

Scope: harden concurrent run startup, then add opt-in parallel fanout for
independent generic non-build split runs

## Recommendation

Ship a trimmed PR1 + PR2 sequence.

PR1 fixes the real shared-state blocker: concurrent `UpdateLatest` calls.

PR2 then adds the actual value: opt-in parallel fanout for independent generic
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

The progress surface is buildable at the child-run lifecycle level. The current
Go CLI already has provider heartbeat support inside a single run, but split
and multi-lens execution are Claude-side `/bakeoff:run` flows, not a Go parent
command. PR2 should therefore report parent orchestration progress:

```text
launched -> running -> completed with exit code
```

Do not promise provider, judge, or triage phase progress for each child while
using `--json --quiet`. That would require either interleaving child output or
adding a Go fanout/status protocol, which is outside the trimmed PR2.

Valid PR2 use cases are broader than review, but they must use the existing
generic split path:

```text
/bakeoff:run research this auth flow as separate architecture, security, and UX work orders
/bakeoff:run analyze this incident separately from database and queueing angles
```

The right PR2 boundary is **generic non-build clean split**, not review-only and
not specialized multi-lens review. Parallelizing the multi-lens review summary
flow should be deferred.

## What Stayed Trimmed

The review was right about bloat. Keep these cuts:

- no native task-manager visibility;
- no generic `<out>/<base>.split-summary.md`;
- no nine-state result taxonomy;
- no third `decision_incomplete` result class;
- no prompt-level cancellation;
- no build mode;
- no parallel multi-lens review in PR2;
- no batch schema;
- no Go-backed scheduler;
- no automatic synthesis.

## What Changed From The Review

This revision does **not** keep the fixed parallelism `2` recommendation.

There is no current evidence that three eligible generic non-build split parts
are qualitatively riskier than two. The existing split contract already caps
normal split size at 2-3 parts. If a user explicitly chooses parallel execution
for three eligible parts, running all three concurrently is the clearest value
path.

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
- when multiple runs start concurrently, the final `latest` target is
  nondeterministic and only means "one of the most recently started children";
- `ResolveRunDir(out, "latest")` still supports symlink and text-file fallback;
- single runs and sequential split/multi-lens behavior are unchanged.

### Implementation Detail

Files:

- `internal/ledger/ledger.go`
- `internal/ledger/ledger_test.go`

Recommended helper shape:

- `writeLatestAtomic(outDir, runID string) error`

Keep this as one helper. Splitting symlink and file fallback into public-looking
internal helpers adds shape without adding much clarity.

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
go test ./internal/commands/researchcmd -run TestRunResearchScrubsSecretsFromProviderArtifacts
```

## PR2: Opt-In Parallel Fanout

PR2 is a prompt-contract change to `commands/run.md`,
`skills/bakeoff/SKILL.md`, `README.md`, `docs/work-orders.md`, and
`docs/task-fit-test-scenarios.md`.

It should not change the Go work-order schema.

Code reality check:

- `internal/commands/researchcmd/run.go::RunResearch` implements one normal
  research run. In JSON mode it suppresses human output and makes the run quiet,
  then emits one final JSON summary.
- `internal/runner/runner.go` already supports single-run provider heartbeats
  through `runner.Options.OnTick`.
- `internal/commands/shared.go::MakeTickPrinter` prints those heartbeats only
  when the run is not quiet.
- `internal/summary/summary.go::BuildResearch` already exposes the child
  summary fields needed after completion: status, exit code, run id, run dir,
  decision kind, provider summaries, triage state, artifact paths, and next
  command.

Therefore PR2 can report child process lifecycle progress from the parent
fanout, then build the final answer from each child's JSON summary and run
artifacts. It cannot report child-internal provider/judge/triage phase progress
while those child runs are intentionally quiet.

It should not add a Go parent scheduler. The primary implementation lives in:

- `commands/run.md` for the slash-command approval and execution contract;
- `skills/bakeoff/SKILL.md` for the mirrored skill contract;
- documentation and task-fit scenarios for user-facing behavior.

No PR2 change is expected in `internal/commands/researchcmd/run.go`. That file
already implements a single normal research run. If shell orchestration later
proves too fragile, the smallest Go fallback would be a new parent command that
spawns external `bakeoff research` child processes and captures their output;
do not fold that into PR2.

### Eligibility

Parallel fanout is available only when all of these are true:

- the request already qualifies for the existing generic split path with 2-3
  parts;
- every part has `type` in `{gather, compare, analyze}` and therefore routes
  through `bakeoff research`;
- every part has an explicit, collision-free run id and every generated work
  order validates before launch.

If a split contains build, run sequentially or ask the user to remove the build
part from parallel fanout.

For more than three parts, do not offer parallel fanout in PR2. Do not offer
parallel fanout from the specialized multi-lens review path in PR2; keep that
flow sequential and defer parallel multi-lens to a later PR if dogfood justifies
it.

### Approval UX

Do not add a global reserved phrase. This must stay compatible with
`docs/task-fit-prompt-repair-plan-2026-05-21.md`, which avoids new broad
reserved replies parallel to `draft anyway`.

Exact insert points:

- In `commands/run.md`, update only the generic split approval block around
  lines 512-526. Replace the sentence that currently asks "run them one after
  another" with the eligible-choice wording below. Replace the following exact
  `write and run` paragraph with the two local approval rules below.
- In `skills/bakeoff/SKILL.md`, mirror the same generic split approval change
  around lines 214-226.
- Do not change the multi-lens approval blocks around `commands/run.md:670+` or
  `skills/bakeoff/SKILL.md:378-395` in PR2 except to preserve their sequential
  wording. Parallel multi-lens is deferred.

After an eligible generic split preview, show local choices:

```text
Choose how to run them:

- `sequential` - write, validate, then run one after another.
- `parallel` - write, validate, then run all 3 at once.
- `show` - print the JSON before approving.
```

Rules:

- Only the currently displayed eligible split preview can be approved. Edits,
  questions, or changed JSON require a revised preview.
- In that local preview context, `parallel` launches parallel fanout;
  `sequential` or the existing `write and run` phrase runs the same files
  sequentially; `show` is not approval. Outside that preview, `parallel` is just
  normal user text and must not launch anything.

Use a soft warning, not a hard confirmation, for 2-3 eligible parts:

```text
Parallel cost note: 3 runs x 2 providers can launch up to 6 provider workers at
once, followed by judge and any triage phases. Child output will be captured per
run, and `latest` will point to one child run, not the group.
```

### Execution

PR2 guarantees launch atomicity, not write atomicity.

After approval, write every split work-order file using the existing collision
policy, then run `bakeoff validate` for every final file path before launching
any child command. If any validation fails, launch no children. The written
work-order files may remain as approved draft artifacts; repair requires a
revised preview and approval before any launch.

Each child command is a normal research run:

```text
bakeoff research <work-order> --run-id <base>.<part> [--out <dir>] [flags] --json --quiet
```

Use explicit run ids. Never use auto-generated run ids or `latest` in summaries.
This is required because normal auto ids ultimately use a short random suffix
(`internal/ledger/ledger.go::MakeRunID` plus `fsutil.RandomSuffix`), which is
fine for ordinary single starts but unnecessary risk for same-moment fanout.
Resolve work-order filename and run-directory collisions before launch using
the existing smallest numeric suffix policy, and pass the final stem as
`--run-id`.

Launch every eligible child concurrently, up to the existing 3-part cap. There
is no queue in PR2, so there is no not-started state after validation succeeds.

Use `--json --quiet` to avoid interleaved human output. Capture each child
stdout/stderr separately in temporary orchestration logs. The logs are not
Bakeoff decision artifacts; mention them only for failures.

Use a POSIX shell fanout primitive with one subshell per child, not `xargs -P`
and not `eval`. The writer should implement this pattern in the prompt
contract, substituting the already-known validated file paths, run ids, `--out`,
and forwarded flags. Use the collision-resolved part slug as `label`; it must
be a simple file-safe slug, not a display label with spaces:

```sh
tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/bakeoff-parallel.XXXXXX") || exit 1

start_child() {
  label=$1
  run_id=$2
  work_order=$3
  shift 3
  (
    "${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" research "$work_order" \
      --run-id "$run_id" "$@" --json --quiet
    printf '%s\n' "$?" > "$tmpdir/$label.exit"
  ) > "$tmpdir/$label.stdout" 2> "$tmpdir/$label.stderr" &
  printf '%s\n' "$!" > "$tmpdir/$label.pid"
}
```

Poll the `*.exit` files for completion progress, then `wait` for all recorded
child pids before summarizing. This keeps progress tied to child process state
and captured JSON/log files, without depending on interleaved provider output.
Do not run this fanout script with `set -e`; each child subshell must write its
exit file even when `bakeoff research` exits non-zero.

### Parent Progress

Add a small parent progress loop to the Claude-side parallel execution
contract. This is not native task-manager integration and not a new persisted
artifact.

The orchestration should track, per child:

- part label;
- explicit run id;
- command;
- stdout log path;
- stderr log path;
- exit code after completion.

Print progress when children launch, when a child completes, and at a bounded
low-frequency interval while children are still running. Prefer the existing
heartbeat budget if it is convenient, but do not make an exact cadence part of
the contract.

Example output:

```text
parallel bakeoff: launched 3 runs
parallel bakeoff: running 3/3: architecture, security, ux
parallel bakeoff: completed security exit=0; running 2/3
parallel bakeoff: completed architecture exit=4; running 1/3
parallel bakeoff: completed ux exit=0; summarizing
```

This progress is limited to child process lifecycle state. It can accurately
say which child commands are still running and which have completed with which
exit codes. It cannot accurately say whether an individual child is currently
inside provider execution, judge execution, or triage while child output is
quiet. The final summary still comes from each child's exit code, JSON summary,
and run artifacts.

Implementation guidance for the prompt contract:

- launch every child as an external `bakeoff research ... --json --quiet`
  process;
- redirect each child's stdout and stderr to separate temp files;
- avoid `eval`; construct commands from the already-known work-order path,
  run id, `--out`, and forwarded flags;
- poll the child exit-status files at the progress interval;
- after every child settles, parse each child's captured JSON summary when
  present and fall back to run-dir artifact paths when JSON is missing.

Do not attempt prompt-level cancellation in PR2. Once launched, wait for all
children to settle. This is simpler and more honest than "cancel if feasible."

### Result Classes

Use two result classes:

| Class | Signals | Summary handling |
| --- | --- | --- |
| `completed` | exit `0`, exit `3`, or exit `4` | Include report path and decision kind when present. For exit `3`, add the unresolved-disagreement caveat. For exit `4`, add a decision-incomplete caveat, durable artifact paths when present, and judge-only rerun guidance when applicable. |
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
- caveats for failed, unresolved, or decision-incomplete parts.

Specialized multi-lens review keeps its existing sequential behavior and
existing `<out>/<base>.multi-lens-summary.md` contract. PR2 does not alter that
flow.

### Manual Scenarios

Add scenarios to `docs/task-fit-test-scenarios.md`:

- existing generic split with `write and run` remains sequential;
- eligible non-build split preview offers `sequential`, `parallel`, and `show`;
- `parallel` before an eligible preview is not approval;
- `parallel` launches all 2-3 eligible generic non-build parts concurrently;
- split containing build does not offer parallel;
- parent progress reports launched/running/completed child counts and exit
  codes without claiming provider/judge/triage phase progress;
- after a parallel run, `latest` points to one child run nondeterministically,
  so the summary must direct users to explicit run ids;
- final response uses explicit run ids and never `latest`;
- specialized multi-lens review remains sequential in PR2.

Before PR2 is accepted, run a local three-child shell dry-run using dummy
commands with different sleep durations. It must prove launch, progress,
completion, separate stdout/stderr capture, and final `wait` behavior. This is
an implementation smoke, not another user-facing task-fit scenario.

### Prompt Budget Coordination

Coordinate PR2 with
`docs/prompt-budget-reduction-implementation-plan-2026-05-21.md`.

If the prompt-budget reduction lands first, add the parallel split contract only
to the canonical prompt surface chosen by that plan, and keep the other surface
as a short pointer. If PR2 lands first, keep the new text short and colocated
only with the generic split approval/execution blocks so the later budget
reduction can extract it mechanically.

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

Parent progress lines are still part of PR2. They are plain command output from
the fanout orchestration, not a second task state system.

## Things Decided Against

### Deferring PR2 Until More Dogfood

Rejected.

The fanout is the value. After PR1 fixes `latest`, a trimmed PR2 can ship
without the removed bells and whistles.

### Fixed Parallelism `2`

Rejected.

There is no evidence that three eligible generic non-build split parts are
qualitatively worse than two. Existing split rules already limit normal scope to
2-3 parts. Show the fanout cost instead of silently serializing one part.

### Always Parallel

Rejected.

Parallel must be explicit. Sequential remains the default and
`write and run` remains sequential.

### Build Parallelism

Rejected.

Build mode has worktree, verifier, patch, winner, protected-path, cleanup, and
repository-lock semantics. It needs a separate design if it is ever worth doing.

### Parallel Multi-Lens Review In PR2

Deferred.

The specialized multi-lens path has separate approval text, partial summary
rules, and persisted summary behavior. Keep it sequential in PR2 so the first
parallel change is only the generic split fanout.

### Third `decision_incomplete` Result Class

Rejected.

Exit `4` is still important, but it does not need its own parent-level class.
Summarize it as a completed handoff with a decision-incomplete caveat and
durable artifact paths.

### Generic `.split-summary.md`

Rejected for PR2.

Conversation-level summaries are enough. Persisted generic split summaries can
be reconsidered only if partial-failure behavior proves they are needed.

### Native Task Manager As Part Of This Plan

Rejected.

It is skippable and non-authoritative. Including it makes the plan larger than
the value justified.

This does not reject simple parent progress output. The rejected piece is a
second status surface based on Claude Code native tasks. Parent progress is
derived directly from the child process handles and child exit codes that the
fanout flow already needs.

### Go-Backed Parent Scheduler

Rejected for PR2.

A Go command could provide stronger quoting, lifecycle handling, and tests, but
it reintroduces scheduler surface area that the trimmed plan is trying to avoid.
If PR2 dogfood shows shell fanout is unreliable, revisit a small parent command
that spawns external `bakeoff research` child processes instead of running
`researchcmd.RunResearch` concurrently in-process.

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

- Existing `write and run` generic split behavior remains sequential, and
  multi-lens behavior remains sequential.
- Eligible generic split previews offer local `sequential`, `parallel`, and
  `show` choices.
- `parallel` is accepted only after an eligible preview offers it.
- Eligibility is exactly: generic split, 2-3 parts, and every part has `type` in
  `{gather, compare, analyze}`.
- Parallel fanout launches all eligible 2-3 generic non-build children
  concurrently.
- Build work orders are never parallelized.
- Every child run has an explicit run id.
- All work orders validate before any child launches.
- Child runs use `--json --quiet`.
- Parent progress output reports child launch, running count, completion, and
  exit code, but does not claim provider/judge/triage phase progress.
- A three-child shell dry-run proves the fanout primitive before PR2 is
  accepted.
- Docs state that `latest` is nondeterministic across concurrent child starts.
- Final summaries use explicit run ids and never rely on `latest`.
- Generic parallel split does not create `.split-summary.md`.
