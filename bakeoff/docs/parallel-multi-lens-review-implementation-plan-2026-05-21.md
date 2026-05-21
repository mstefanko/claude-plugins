# Parallel Multi-Lens Review Implementation Plan

Date: 2026-05-21

Status: proposed

Scope: add opt-in parallel fanout to the existing explicit multi-lens review
flow

## Recommendation

Add parallel multi-lens review as a small extension of the current multi-lens
workflow.

Keep the current shape:

```text
explicit multi-lens request -> normal review work orders per lens -> validate all lens files -> run lenses -> write <out>/<base>.multi-lens-summary.md
```

Only change the execution choice after approval:

```text
sequential/write and run -> current one-after-another execution
parallel -> launch all approved lens review runs concurrently
```

Do not add a Go scheduler, a batch work-order schema, `facets[]`, provider
personas, cross-run triage, automatic synthesis, or generic split summary
artifacts.

This should be implemented as a prompt-contract and docs update first. The Go
CLI already runs one normal `bakeoff research` child, emits useful `--json`
summaries, writes review artifacts, auto-triages code-review runs, and has
concurrency-safe `latest` updates.

## Why This Is Now Reasonable

Parallel multi-lens review was deliberately kept sequential in
`docs/parallel-nonbuild-split-implementation-plan-2026-05-21.md` because it has
specialized approval text, partial-stop behavior, and a persisted
`<base>.multi-lens-summary.md` contract.

Those concerns are real, but they are not hard blockers. They mean multi-lens
should not blindly inherit generic split semantics. The better design is to
keep the existing multi-lens drafting and summary behavior, then reuse the
parallel research-child fanout only for execution.

The valuable behavior is:

```text
validated lens review work orders -> launch all lens `bakeoff research` runs in parallel -> wait for every lens to settle -> write the normal multi-lens summary, marked partial when needed
```

## Code Reality Check

The existing code supports the needed child-run behavior:

- `internal/commands/researchcmd/run.go::RunResearch` executes one normal
  non-build work order. With `--json`, it suppresses human output by making the
  run quiet and emits one final JSON summary.
- `internal/commands/researchcmd/run.go::finalizeResearchRun` auto-triages
  code-review gather runs when the research decision exits `0`, then includes
  triage state in JSON output.
- `internal/summary/summary.go::BuildResearch` exposes run id, run dir, exit
  code, command status, decision kind, provider summaries, judge summary,
  triage state, and artifact paths. The parallel parent can construct
  `bakeoff show <run-id>` commands from the child run id and output directory.
- `internal/ledger/ledger.go::UpdateLatest` now uses unique temp paths before
  atomically replacing `latest`, so concurrent child starts do not share one
  `.latest.tmp` path.
- `internal/manifest/manifest.go::triageSummary` already knows how to derive
  triage state and classification counts from run artifacts.

The parent still cannot report child-internal provider, judge, or triage phase
progress while child output is captured via `--json --quiet`. Parent progress
must remain lifecycle-only:

```text
launched -> running -> completed with exit code
```

## Original Concerns

### 1. Separate Approval Text

Status: valid concern, easy to handle.

Current multi-lens approval text asks the user to run lens work orders one
after another. Generic parallel split already uses a local approval choice, but
that exact text should not replace multi-lens preview copy because multi-lens
has lens-specific cost and summary language.

Recommended behavior:

- keep plain review as one normal review;
- trigger multi-lens only for explicit separate-lens/separate-pass wording;
- keep `write and run` as a sequential approval for backward compatibility;
- offer `sequential`, `parallel`, and `show` only inside an eligible multi-lens
  preview;
- accept `parallel` only after the displayed eligible preview offered it;
- if the user replies `parallel` to an ineligible preview, say parallel is not
  available for that preview and re-show the valid approval choices;
- outside that preview, treat `parallel` as ordinary user text;
- preserve `show` and `show <lens>` behavior for full JSON inspection.

Suggested preview ending:

```text
Choose how to run these lens reviews:

- `write and run` or `sequential` - write, validate, then run one after another.
- `parallel` - write, validate, then run all <N> lens reviews at once.
- `show` - print the JSON before approving.
- `show <lens>` - print one lens JSON.

Parallel cost note: <N> lens runs x <provider-count> providers can launch up to
<N*provider-count> provider workers at once. Later phases can also overlap
across lenses: up to <N> judge calls, and up to <N> triage calls when triage is
enabled. Child output will be captured per run, and `latest` will point to one
child run, not the group.
```

This keeps the current multi-lens approval surface recognizable while making
parallel fanout explicit and local.

### 2. Partial-Stop Behavior

Status: most important valid concern.

Sequential multi-lens can stop before later lenses run, then ask whether to
continue remaining lenses. Parallel multi-lens cannot preserve that exact
control point after children launch. Once the parent starts every child,
prompt-level cancellation is not part of the contract; the honest behavior is
to wait for every child to settle.

Recommended behavior:

- validation failure remains all-or-nothing before launch;
- launch failure for one lens is recorded as failed, but does not hide other
  launched lens results;
- after launch, wait for every child to settle;
- do not try prompt-level cancellation;
- do not ask `continue lenses` unless some lens truly never launched;
- mark the conversation summary and persisted summary as partial if any lens
  failed, was interrupted, had missing required artifacts, or did not launch.

Result classification:

| Child signal | Parent class | Multi-lens handling |
| --- | --- | --- |
| exit `0` | completed | Include report, decision kind, triage state, and triage counts when present. |
| exit `3` | completed with caveat | Include unresolved-disagreement caveat; mark triage raw/missing unless artifacts exist. |
| exit `4` | completed with caveat | Include decision-incomplete caveat, durable artifact paths, and judge-only rerun guidance when applicable. |
| exit `1`, `2`, `130` | failed | Include command, exit code, stderr/log path, and any existing report/decision/triage artifacts. |
| launch failure | failed | Include command and launch error. |
| pid gone, exit file missing | failed | Classify as `orphaned_child`; include command, pid path, stdout/stderr paths, and any run artifacts that exist. |
| missing required artifacts | failed | Include run id, run dir if known, and which artifacts were missing. |

Auto-triage can turn an otherwise successful code-review child into exit `1`.
The parent should still summarize any available `report.md`, `decision.json`,
and triage artifacts, and should clearly mark triage as failed, missing, stale,
dry-run, or raw as appropriate.

Sequential multi-lens behavior intentionally remains stricter in v1: it still
stops on exit `4` and asks before continuing remaining lenses. Parallel
multi-lens treats exit `4` as completed with a caveat because all eligible
children have already launched by the time the parent sees the exit code.
Relaxing sequential exit-`4` behavior can be considered separately, but is not
part of this plan.

### 3. Persisted Multi-Lens Summary

Status: valid concern, but compatible with parallel fanout.

Generic parallel split intentionally avoids a persisted split summary.
Multi-lens review should keep its existing persisted summary contract because
that summary is part of the user value: it indexes lens reports, triage states,
actionable findings, overlap, clean lenses, caveats, and next commands.

Recommended behavior:

- always attempt to write `<out>/<base>.multi-lens-summary.md` after all
  launched lens children settle;
- apply the current numeric collision policy to summary filenames;
- preserve the current summary sections from `references/run-appendix.md`;
- include every requested lens, not just cleanly completed lenses;
- mark failed, skipped, interrupted, missing-artifact, or decision-incomplete
  lens entries clearly;
- mark the whole summary partial when any lens is not fully completed and
  verified;
- never use `latest` in the summary;
- include explicit `bakeoff show <run-id>` commands for each lens run.

This summary remains a plugin-created convenience artifact, not a Go CLI
decision artifact and not a cross-run synthesis.

## Eligibility

Parallel multi-lens review is available only when all of these are true:

- the request already qualifies for the explicit multi-lens review path;
- the review target passes task-fit and is bounded by branch, PR, diff, file
  set, or local changes;
- every lens drafts to a normal `type: "gather"` work order with
  `facet.id: "code-review"`;
- all lens work-order files validate before launch;
- every lens has an explicit collision-free run id;
- every parallel lens label slug matches `^[a-z0-9][a-z0-9-]{0,31}$`;
- lens count is 2-3.

For more than three lenses, keep the current narrowing flow. Do not offer
parallel fanout for `run all lenses` in the first implementation.

Build work orders remain ineligible. Generic clean splits and multi-lens review
remain separate flows with separate naming and summary rules.

## Naming And Files

Preserve current multi-lens naming:

```text
<base>.<lens>.work-order.json
--run-id <base>.<lens>
```

For parallel fanout, the lens label used in shell paths must be a stricter
lowercase slug:

```text
^[a-z0-9][a-z0-9-]{0,31}$
```

Normalize known presets to these labels (`security`, `performance`, `ux`,
`tests`, etc.). For custom lens names, generate a kebab-case label that matches
the regex. If a requested lens cannot be normalized without ambiguity or would
need spaces, punctuation, uppercase, dots, underscores, path separators, or more
than 32 characters, do not offer parallel; ask the user to rename the lens or
run sequentially.

Resolve collisions after the lens slug:

```text
review-auth.security-2.work-order.json
--run-id review-auth.security-2
```

Never switch multi-lens to `.part-N`; that belongs to generic splits.

All generated work-order files are ordinary normal review work orders. The
parallel parent should not create a batch manifest or group run directory.

## Shared Output Directory Audit

Parallel children share the same `--out` directory, so the implementation must
keep writes run-id-keyed or parent-owned.

Expected writes under shared `--out`:

- each child writes only inside `<out>/<run-id>/...`;
- each child may update `<out>/latest`, which is concurrency-safe but
  nondeterministic;
- auto-triage writes under the same child run directory:
  `<out>/<run-id>/triage/...`;
- manifests are per-run files at `<out>/<run-id>/manifest.json`;
- the parent writes one summary file at
  `<out>/<base>.multi-lens-summary.md` after child settlement.

There should be no global ledger append, shared manifest index, shared split
directory, or group run directory in v1. Before implementation is accepted,
audit the final command paths and confirm every other write is either
run-id-keyed or the single parent summary file.

## Execution Contract

After approval:

1. Write every lens work-order file using the existing collision policy.
2. Run `bakeoff validate` on every final file path.
3. If any validation fails, launch nothing, repair, re-preview, and require
   fresh approval.
4. If approved as sequential, keep the current one-after-another execution and
   stop/continue behavior.
5. If approved as parallel, launch every eligible lens child concurrently:

```text
bakeoff research <lens-work-order> --run-id <base>.<lens> [--out <dir>] [review flags] --json --quiet
```

Forward routed research flags to every lens where applicable:

- `--out`
- `--base`
- `--diff`
- `--changed-files`
- `--quiet` is superseded by `--json --quiet` for parallel children
- `--no-triage`
- `--no-repo-layout`

Do not pass build-only flags.

Use separate stdout, stderr, exit, and pid files per child. Parent progress is
derived only from launch and exit files.

## Fanout Primitive

Reuse the existing parallel split fanout shape, but make the shell semantics
explicit. A dry run showed the pattern works under `/bin/sh`; it can hang or
miscount if copied into `zsh` with scalar word-splitting assumptions.

Contract requirements:

- run the fanout snippet under `/bin/sh` or Bash;
- use one subshell per child;
- do not use `xargs -P`;
- do not use `eval`;
- do not use `set -e`;
- use lens labels matching `^[a-z0-9][a-z0-9-]{0,31}$`;
- write the exit file from inside each child subshell after `bakeoff research`
  returns;
- poll only child exit files and pids for progress;
- after every child settles, parse captured stdout JSON when present and fall
  back to run-dir artifacts when JSON is missing.

Example labels:

```text
security
performance
ux
```

Example progress:

```text
parallel multi-lens: launched 3 lens runs
parallel multi-lens: running 3/3: security, performance, ux
parallel multi-lens: completed security exit=0; running 2/3
parallel multi-lens: completed ux exit=1; running 1/3
parallel multi-lens: completed performance exit=4; summarizing
```

Do not claim provider, judge, or triage phase progress for quiet children.

Add a committed shell test for the fanout primitive rather than relying only on
a human dry-run. A small test under `scripts/` should run three mock children
with different sleep durations and exits `0`, `1`, and `4`; assert separate
stdout/stderr capture, exit-file handling, lifecycle progress, final wait
behavior, and the orphaned-child classification path.

## Summary Contract

After all launched children settle, read available artifacts for every lens:

- captured child JSON summary;
- `report.md`;
- `decision.json`;
- `manifest.json`;
- `triage/final.json`;
- `triage/triage.md`;
- `triage/source_finding_filter.json`;
- child stdout/stderr logs when the child failed or JSON is missing.

Context-window invariant: artifact reading for summary construction must happen
through the context-mode sandbox. Use `ctx_execute_file`/`ctx_execute` or an
equivalent sandboxed helper to read and distill child artifacts; the parent
conversation should receive compact digests, extracted counts, finding IDs,
short finding summaries, paths, and hashes, not raw `report.md`, `triage.md`,
or large JSON bodies. This avoids flooding the parent context when a successful
three-lens run produces dozens of artifact files.

Write `<out>/<base>.multi-lens-summary.md` with the existing summary section
shape:

```text
# Multi-Lens Review Summary

Summary file: <path>

## Runs
## Triage Counts
## Most Actionable
## Overlap
## Clean Lenses
## Caveats
## Next Commands
## Optional Synthesis
```

The summary must:

- list each lens and run id;
- list each report path when present;
- list triage path/state and triage counts when present;
- include child exit code and result class;
- distinguish raw, missing, stale, dry-run, failed, and verified triage states;
- include most actionable findings by lens from triage when available;
- use raw report findings only when triage is disabled or unavailable, and say
  they are raw/unverified;
- identify overlapping themes without inventing new findings;
- identify clean lenses only when triage or report artifacts support that;
- include `bakeoff show <run-id>` commands;
- state that `latest` may point to any one child run and is not the group.

Always include `## Optional Synthesis` in the persisted summary. It is only an
invitation or status note, not an automatic synthesis run. If at least one lens
completed with usable artifacts, say the user can request a separate
`type: "analyze"` synthesis pass. If no lens has usable artifacts, say
synthesis is unavailable until a lens completes successfully.

The final conversation response should include a concise version of the same
summary and link to the persisted summary file.

## Simplifications

Keep the first implementation intentionally small:

- cap parallel multi-lens at 2-3 lenses;
- no parallel `run all lenses`;
- no persisted group manifest;
- no Go parent scheduler;
- no native task-manager integration;
- no prompt-level cancellation;
- no automatic cross-lens synthesis;
- no cross-run triage;
- no generic `.split-summary.md`;
- no changes to the work-order schema.

This keeps the flow close to the current multi-lens implementation and limits
the new behavior to an execution choice.

## Documentation Updates

Update:

- `skills/bakeoff-run/SKILL.md`
  - surgically remove only the multi-lens clause from the compound "Never offer
    parallel for build parts, more than three parts, or multi-lens review" rule;
    keep the build and more-than-three restrictions;
  - broaden `--json --quiet` from parallel split children to parallel research
    children;
  - add the multi-lens parallel choice, eligibility, execution, partial-summary,
    and summary rules.
- `references/run-appendix.md`
  - add a parallel multi-lens preview ending;
  - add parallel multi-lens progress examples;
  - clarify the fanout snippet must run under `/bin/sh` or Bash.
- `README.md`
  - update the review section to say explicit multi-lens review can be run
    sequentially or in parallel after preview.
- `docs/work-orders.md`
  - update the schema note so multi-lens review is still not a schema feature
    but may be launched in parallel by the plugin.
- `docs/task-fit-test-scenarios.md`
  - replace the bullet titled "Specialized multi-lens review remains
    sequential" with parallel-choice scenarios.

No Go source changes are expected for the first implementation.

## Manual Scenarios

Add or update manual regression scenarios:

- plain review remains one normal `code-review` work order;
- explicit two-lens review preview offers sequential/parallel/show choices;
- `write and run` remains sequential for multi-lens;
- `parallel` before an eligible multi-lens preview is not approval;
- `parallel` after an eligible multi-lens preview launches all 2-3 lens runs
  concurrently;
- `parallel` on an ineligible multi-lens preview replies that parallel is not
  available and re-shows the valid approval choices;
- multi-lens with more than three lenses does not offer parallel fanout;
- a custom lens name with spaces or punctuation is normalized only if it can
  become a unique `^[a-z0-9][a-z0-9-]{0,31}$` label; otherwise parallel is not
  offered;
- multi-lens validation failure launches no children;
- parent progress reports launched/running/completed lens counts and exit
  codes without child-internal phase claims;
- one child exit `0`, one exit `4`, and one exit `1` still produce a persisted
  partial multi-lens summary;
- an orphaned child with pid gone and no exit file is classified as failed
  `orphaned_child`;
- failed triage after an otherwise completed review child is summarized as
  partial with raw/unverified triage caveats;
- provider-concurrency dogfood confirms Claude and Codex CLIs tolerate
  concurrent invocations from the same host/session, or documents any
  self-serialization that limits speedup;
- final and persisted summaries use explicit run ids and never rely on
  `latest`;
- optional synthesis remains a separate `type: "analyze"` approval flow.

Before acceptance, run a local three-child shell dry-run under `/bin/sh` with
different sleep durations and exit codes. It must prove launch, lifecycle
progress, completion, separate stdout/stderr capture, JSON parsing fallback,
and final wait behavior.

## Acceptance Criteria

- Existing single-review behavior is unchanged.
- Existing sequential multi-lens behavior still works with `write and run`.
- Eligible 2-3 lens multi-lens previews offer local `sequential`, `parallel`,
  `write and run`, `show`, and `show <lens>` behavior as documented.
- `parallel` is accepted only after an eligible multi-lens preview offers it.
- `parallel` on an ineligible preview explains that parallel is unavailable and
  re-shows valid choices.
- Parallel lens labels must match `^[a-z0-9][a-z0-9-]{0,31}$`; non-conforming
  custom labels make parallel ineligible until renamed or normalized.
- The displayed parallel cost note computes the explicit provider, judge, and
  triage fanout envelope for the selected lens count and provider count.
- All lens work-order files validate before any parallel child launches.
- Every parallel child uses an explicit run id.
- Every parallel child runs `bakeoff research ... --json --quiet`.
- Parent progress is lifecycle-only.
- The parent waits for all launched children to settle.
- The fanout primitive has a committed shell test covering three mock children,
  mixed exits, separate logs, final wait behavior, and orphaned-child handling.
- Shared `--out` writes are audited and documented as run-id-keyed or the single
  parent summary file.
- Provider-concurrency dogfood confirms whether the configured Claude and Codex
  CLIs tolerate concurrent invocations from the same host/session.
- Summary construction reads child artifacts through context-mode sandboxing and
  passes only compact digests/extracted facts to the parent context.
- A persisted `<out>/<base>.multi-lens-summary.md` is written after parallel
  runs, including partial/failure states when needed.
- The summary includes explicit run ids, report paths, triage state/counts when
  present, caveats, and `bakeoff show <run-id>` commands.
- The summary never directs the user to `latest`.
- No schema, Go scheduler, batch command, or automatic synthesis is added.

## Open Questions

- Should `parallel` be offered for a user-explicit `run all lenses` request
  after dogfood, or should that remain sequential to keep concurrent provider
  fanout bounded?
- Should failed child logs be copied into the persisted multi-lens summary
  directory later, or is reporting temporary orchestration log paths enough for
  v1?
- If parallel multi-lens becomes the dominant review path, should a small Go
  parent command replace shell fanout for stronger quoting, process lifecycle,
  and test coverage?

None of these questions block the prompt-contract implementation.
