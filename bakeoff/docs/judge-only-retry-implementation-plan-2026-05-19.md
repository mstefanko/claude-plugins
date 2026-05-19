# Judge-Only Retry Implementation Plan

Status: proposed implementation plan

## Problem

When both research providers finish successfully but the judge process fails,
the current handoff treats the run as a failed launcher outcome and recommends a
full rerun. That is wasteful and mildly misleading: the expensive provider
evidence already exists in the run ledger, and the failed component is only the
judge call.

The desired default recommendation should be to retry just the judge when:

- the run is a research run (`gather`, `compare`, or `analyze`);
- every configured provider has a successful `providers/<id>/status.json`;
- every configured provider has a durable `providers/<id>/final.json`;
- the decision indicates the judge ran but failed, or the judge artifacts show a
  failed judge attempt.

## Current Code Facts

- `RunResearch` runs providers first, builds `okResults`, and calls
  `runJudgePhase` only when both providers succeeded. It then writes
  `decision.json`, `report.md`, `meta.json`, and `manifest.json`.
  Source: `internal/commands/researchcmd/run.go:130`.
- `runJudgePhase` is already a separable research-judge phase. It only needs
  the work order, `workerResults`, run directory, quiet flag, and human-output
  flag. Source: `internal/commands/researchcmd/run.go:351`.
- `runSingleJudge` builds the judge prompt from `workerResults[*].final_json`,
  runs the configured judge provider, and writes the judge artifacts. Source:
  `internal/commands/researchcmd/run.go:396`.
- Successful providers already persist the two pieces needed for judge replay:
  `status.json` and `final.json`. Source:
  `internal/artifact/artifact.go:86`.
- `rerun` already means "fresh run id" and replays the previous
  `work-order.json`; extending it preserves user expectations better than
  adding an unrelated command. Source:
  `internal/commands/reruncmd/rerun.go:31`.
- `RunResearch` currently turns any non-zero research exit other than judge
  disagreement into a silent generic error, and `cli.ExitCode` maps generic
  errors to exit 1. Exit 4 therefore needs an explicit error type / mapping,
  not only a returned integer. Sources:
  `internal/commands/researchcmd/run.go:232`,
  `internal/cli/exit.go:19`.
- `manifest.providerSummaries` currently copies raw provider status into
  `manifest.providers.<id>.status`, while `summary.CompactStatus` already
  defines the compact status contract used by research JSON summaries. Sources:
  `internal/manifest/manifest.go:226`,
  `internal/summary/summary.go:125`.
- `researchcmd.researchResultLine` prints `basis=<value>` for analyze
  tiebreaks, while the decision JSON field is `spine_tiebreak`. Sources:
  `internal/commands/researchcmd/run.go:507`,
  `internal/decision/decision.go:165`.
- `lscmd` consumes `manifest.facet_id`; `meta.facet` is the full object while
  `manifest.facet_id` is the hoisted id. Source:
  `internal/commands/lscmd/ls.go:93`.

## Recommendation

Add `bakeoff rerun SOURCE_RUN_ID --judge-only` for research runs, and make the
post-failure plugin recommendation prefer that command when providers are OK and
the judge failed.

Use a fresh run directory by default. The original failed ledger should remain
untouched and auditable, including the failed judge stdout/stderr/status. The
new retry ledger should be self-contained: copy the source work order, provider
artifact directories, optional review-context artifacts, then run only the judge
and write fresh decision/report/meta/manifest artifacts.

This is better than in-place mutation because Bakeoff's strongest property is
that a run ledger is a replayable handoff artifact. Overwriting
`judge/status.json`, `decision.json`, `report.md`, and `manifest.json` would
make the original failure harder to audit unless we also invented attempt
history. A fresh run avoids that extra state model and keeps the implementation
small.

## Decisions Closed

- `--judge-only` is a recovery command for source runs with a failed judge
  attempt, not a generic "rejudge any completed run" command. It must reject
  source runs where the judge never ran, already completed successfully, or has
  no durable failed-judge signal in `decision.json` or `judge/status*.json`.
- The fresh retry run should update `runs/latest`, matching normal research and
  build runs.
- The retry run metadata should include `source_run_id`,
  `source_run_dir`, and `rerun_mode: "judge_only"` in `meta.json`.
  Implement this without broad call-site churn by adding a narrow
  `artifact.WriteMetaWithExtra(..., extra map[string]any)` helper and keeping
  the existing `WriteMeta(...)` wrapper for normal callers.
- Do not add `--json` to `bakeoff rerun` in v1. The shared research
  finalization helper may continue to support JSON for `bakeoff research`, but
  `RunResearchJudgeOnlyOptions` should not expose a JSON field until the CLI
  has a real JSON mode for rerun.
- Keep the command as `bakeoff rerun --judge-only`; do not add
  `bakeoff judge-retry`.
- For provider-status drift, choose the lower-blast-radius F-010 shape:
  keep `manifest.providers.<id>.status` as the raw runner status and add
  `compact_status`. Do not flip the existing `status` value in this plan.

## Rejected Alternative: In-Place Judge Retry

An in-place retry could be implemented with fewer copied files: load the
existing providers, rerun `runJudgePhase` in the same directory, and rewrite the
core artifacts. That loses on product and audit behavior:

- it overwrites the failed judge artifacts unless new attempt filenames are
  introduced;
- it invalidates existing manifest fingerprints until the retry completes;
- it can make existing triage artifacts stale without making the causal change
  obvious;
- it turns a simple retry into an attempt-history design.

In-place retry is acceptable as a future explicit `--in-place` debug option, but
it should not be the default.

## Proposed CLI Shape

```text
bakeoff rerun SOURCE_RUN_ID --judge-only [--run-id NEW_ID] [--out runs] [--quiet] [--no-triage]
```

Behavior:

- Only valid for research work orders.
- Refuse build runs with a validation error such as:
  `--judge-only is currently supported only for research runs`.
- Refuse research runs that do not have durable evidence of a failed judge
  attempt. Accept either `decision.json` with
  `judge_completed=false` / failed-judge decision kind, or `judge/status*.json`
  where at least one judge pass is not `ok` / `ok_after_format_retry`.
- Refuse research runs whose judge completed successfully; users who want a
  different judgment should do a normal fresh `rerun`.
- If `--run-id` is omitted, use the existing fresh run-id generator.
- Update `runs/latest` to the new retry run id, matching normal run behavior.
- Print a short note:
  `note: judge-only rerun reuses provider artifacts from <source-run>`.
- Preserve `--no-triage`; otherwise allow normal auto-triage after a successful
  code-review judge retry.

## Implementation Work Breakdown

### 1. Add CLI Option

- Add `JudgeOnly bool` to `internal/commands/reruncmd.RerunOptions`.
- Add `--judge-only` to `NewCmdRerun`.
- Update `internal/commands/command_options_test.go`.
- Update `internal/commands/reruncmd/rerun_test.go` to assert dispatch.

### 2. Add Research Judge-Only Entry Point

Add a new function in `internal/commands/researchcmd`, for example:

```go
func RunResearchJudgeOnly(ctx context.Context, f commands.Factory, opts *ResearchJudgeOnlyOptions) error
```

Suggested options:

```go
type ResearchJudgeOnlyOptions struct {
    SourceRunDir string
    SourceRunID  string
    Out          string
    RunID        string
    Quiet        bool
    NoTriage     bool
}
```

The function should:

1. Load `sourceRunDir/work-order.json`.
2. Validate `wo.Type != "build"`.
3. Validate that the source run has a failed judge attempt:
   - first read `decision.json` when present and accept
     `judge_completed=false`, `decision_kind="provider_union_only"`,
     `decision_kind="judge_failed"`, or the legacy failed-judge caveat
     patterns;
   - also inspect `judge/status.json` for gather and
     `judge/status-pass1.json` / `judge/status-pass2.json` for compare/analyze;
     accept when at least one present status does not satisfy
     `artifact.ProviderSucceeded`;
   - reject when no judge status is present, all judge statuses succeeded, or
     the decision says the judge did not run.
4. Create a fresh `runDir`, respecting existing run-id collision behavior and
   updating `runs/latest` to the new run.
5. Copy source artifacts needed for a self-contained ledger:
   `work-order.json`, `source-work-order.json`, `review-context.md`,
   `review-context.json`, and `providers/<id>/`.
6. Rehydrate `workerResults` from the copied provider artifacts.
7. Run `runJudgePhase`.
8. Write `decision.json`, `report.md`, `meta.json`, and `manifest.json`.
   `meta.json` must include `source_run_id`, `source_run_dir`, and
   `rerun_mode: "judge_only"`.
9. Run/recommend triage using the same logic as normal research finalization.

### 3. Rehydrate Provider Results Safely

Add a helper such as:

```go
func loadResearchWorkerResultsFromArtifacts(wo *workorder.WorkOrder, runDir string) (map[string]map[string]any, error)
```

For each configured provider:

- require `providers/<id>/status.json` to be a JSON object;
- require status to satisfy `artifact.ProviderSucceeded`;
- require `providers/<id>/final.json` to be a JSON object;
- validate the loaded final JSON with `workorder.ValidateWorkerResult(final,
  wo.Type)` so replay has the same schema guarantees as the original worker
  path;
- set `result["final_json"] = final`;
- preserve status metadata including `scope_enforcement`,
  `final_json_source`, timing, byte counts, and truncation fields.

This helper intentionally does not reconstruct raw `stdout`/`stderr` payloads
in memory. The files are copied into the new ledger for audit, while the report
and decision code only need status metadata plus `final_json`.

### 4. Avoid Duplicating Finalization Logic

Extract the post-judge research finalization block from `RunResearch` into a
shared helper. The helper should take:

- work order;
- run id / out / run dir;
- started timestamp;
- `workerResults`;
- `decisionDoc`;
- `judgeResults`;
- exit code;
- `NoTriage`, `JSON`, quiet/human-output flags.

This prevents judge-only retry from drifting from normal research output,
especially around auto-triage, JSON summary, manifest generation, and exit code
handling.

Exit-code handling must be explicit:

- add `apperror.DecisionIncompleteError`;
- add `cli.ExitDecisionIncomplete = 4` and map that error type in
  `cli.ExitCode`;
- update `summary.CommandStatus` so exit 4 serializes as
  `decision_incomplete` rather than generic `failed`;
- when finalization receives `exitCode == 4`, return a `SilentError` wrapping
  `DecisionIncompleteError`, not a generic `fmt.Errorf("research failed")`;
- keep exit 1 for true runtime / launcher / validation failures and failed
  providers.

### 5. Copy Provider Artifacts With Guardrails

Add a small recursive copy helper scoped to run-ledger children. Requirements:

- copy only from resolved source run directory into the newly-created run
  directory;
- copy provider directories before the judge runs;
- reject missing provider directories or missing required provider files;
- preserve content, not permissions;
- do not follow symlinks outside the source run.

This is narrow enough to avoid a broad filesystem utility. If the repo already
has a suitable safe-copy helper after future refactors, use that instead.

### 6. Update Failure Recommendation UX

Update the plugin summary path so that when the CLI summary or artifacts show:

- command exit is `4` (`decision_incomplete`);
- all providers are `ok` or `ok_after_format_retry`;
- judge status is failed;

the first recommendation is:

```text
bakeoff rerun <run-id> --judge-only
```

The current full rerun should become a secondary option.

Also update `commands/run.md`, `skills/bakeoff/SKILL.md`,
`docs/cli-reference.md`, and `README.md` command references.

## Tests

Add focused tests before broad parity work:

- `rerun --judge-only` dispatches to the research judge-only path.
- `rerun --judge-only` rejects build runs.
- judge-only retry succeeds when provider `status.json` and `final.json` are
  present and judge succeeds.
- judge-only retry refuses when one provider final is missing.
- judge-only retry refuses when one provider final is malformed for the work
  order type.
- judge-only retry refuses when one provider status is not successful.
- judge-only retry refuses when the source run has no failed judge attempt.
- judge-only retry refuses when the source judge completed successfully.
- judge-only retry writes a new manifest whose fingerprints include copied
  provider artifacts and new judge artifacts.
- existing source run remains unchanged after retry.
- retry `meta.json` records `source_run_id`, `source_run_dir`, and
  `rerun_mode="judge_only"`.
- code-review judge-only retry either runs auto-triage or preserves the
  existing `--no-triage` behavior.
- failed-judge providers-OK research exits with code 4 via
  `DecisionIncompleteError`, not exit 1.
- research JSON summaries for exit 4 report `status="decision_incomplete"`.

Parity coverage can come after the Go unit tests:

- failed judge plus OK providers produces a summary whose recommended next
  action is judge-only retry;
- judge-only retry produces the same decision shape as a normal successful run.
- compare and analyze judge-failure runs surface `judge_completed=false` and
  exit 4, not a generic tie/exit-1 launcher failure.

## Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| Provider artifacts are incomplete or hand-edited. | Require status and final JSON for every configured provider, validate final JSON with `workorder.ValidateWorkerResult`, then let `runs verify` validate the new ledger. |
| Fresh retry duplicates provider artifacts and consumes disk. | Provider research artifacts are small compared with rerunning providers; self-contained ledgers are worth the bytes. |
| Triage from the failed run becomes confusing. | Do not copy `triage/`; let the retry run create its own triage state from its new decision/report. |
| Build mode seems similar but is not. | Scope v1 to research only; build requires rehydrating baseline, verifier, patch, metric, and provider-run structures. |
| Reused provider outputs might be stale relative to web/codebase reality. | That is already true for any ledger replay. Make the note explicit: judge-only rerun reuses prior provider artifacts. |
| Command grows too much. | Keep it as one `rerun` flag, one rehydration helper, and shared finalization. Avoid adding attempt history or a new orchestration subsystem. |

## Acceptance Criteria

- A failed-judge, providers-OK research run can be recovered without rerunning
  providers.
- The source run remains byte-for-byte unchanged.
- The retry run is self-contained and passes `bakeoff runs verify <new-run-id>`.
- Human output clearly says provider artifacts were reused.
- The default post-failure recommendation points to judge-only retry first.

## Appendix: Adjacent Tightening Items (from run 2026-05-19-c1db investigation)

This appendix documents follow-on tightening items surfaced while investigating
run `2026-05-19-c1db`, where the judge subprocess died with
`API Error: The socket connection was closed unexpectedly` after both
providers (`claude`, `codex`) completed cleanly with valid `<final_json>`
envelopes (18 and 15 claims respectively). These items are scoped narrowly to
the failed-judge / providers-OK regime that motivates the main plan; they are
intentionally minimal and additive.

Items dropped from the appendix and the reason:

- **Item 4 (per-provider `final.json` as first-class artifact) — duplicate.**
  `providers/<id>/final.json` is already written by
  `internal/artifact/artifact.go` (writer at `artifact.go:86`, surfaced in the
  cited run for both `claude` and `codex`), and the main plan already requires
  it as a precondition for judge-only retry. No additional work needed.
- **Item 7 (heartbeats during failed judge) — no-op.** `judge/status.json` for
  the cited run shows `heartbeat_count=2`, `quiet_tick_count=1`,
  `wall_seconds=153.794`. The supervisor behaved correctly; nothing to change.

The remaining valid items follow.

### A1. `renderGather` Has No Judge-Failed Fallback

**Problem.** In `internal/report/report.go`, `renderGather()` switches only on
`decision_kind` values `both_failed` and `single_provider_only`, then falls
through to `judge["merged_claims"]` (and `judge["conflicts"]`,
`judge["unknowns_union"]`). When the judge process crashes after both providers
succeeded, the decision is still emitted as `structured_union` with
`judge_ran=true`, but `judgeResults["pass1"]` is the empty/failed judge result
and `merged_claims` is empty. The rendered `report.md` therefore shows empty
`## Findings`, `## Conflicts`, and `## Unknowns` sections even though each
provider's `final.json` contains a full claims array. This is exactly the shape
seen in `runs/2026-05-19-c1db/report.md`.

**Proposed change.**

- In `internal/report/report.go`, extend the `switch decision["decision_kind"]`
  in `renderGather` with a new case for the judge-failed-but-providers-OK
  regime (kind introduced in item A2 below; until that exists, dispatch on the
  combination `judge_ran=true && judge_completed=false` or the caveat marker).
  The new case must render one `### <providerID>` subsection per configured
  provider, each populated via `claimLines(jsonutil.ListValue(worker["claims"]),
  providerID, false)`, where `worker := jsonutil.FinalJSONMap(workerResults[id])`.
  It should also append `unknowns(worker)` per provider, and omit the
  `## Conflicts` / merged-`## Unknowns` blocks that depend on the judge.
- Mirror this case in `renderCompare` and `renderAnalyze` so the
  failed-judge-providers-OK regime is renderable for `compare` and `analyze`
  modes as well, even if the main plan only ships `gather` first. Use the same
  per-provider subsection shape; do not invent a "winner".
- Add a `report_test.go` case that constructs `decisionDoc` with
  `judge_ran=true` / `judge_completed=false` (per A2), two provider
  `workerResults` carrying non-empty `claims`, and an empty
  `judgeResults["pass1"]`, and asserts the rendered output contains both
  provider IDs and at least one claim line per provider.

**Acceptance criteria.**

- A `gather` run with both providers succeeding and the judge failing renders a
  `report.md` whose `## Findings` section contains both providers' claims under
  per-provider subsections.
- The empty `## Conflicts` and `## Unknowns` blocks no longer appear when the
  judge failed (their values come from the judge; surfacing empty bullets is
  misleading).
- Existing `structured_union` tests for successful gather runs continue to
  pass.

**Relation to judge-retry.** Independent. This is a pure rendering fix that
improves the immediate-failure UX before any retry happens. The main plan's
judge-only retry remains the right action for the user; this appendix item
makes the failure ledger usable even if the user chooses not to retry.

### A2. `decision_kind="structured_union"` Is Overloaded

**Problem.** `internal/decision/decision.go` defines
`GatherStructuredUnion(...)` which assigns
`decision_kind="structured_union"`, `judge_ran=true`, `judge_rationale=[]`,
and `canonical_winner=nil` on BOTH the success and the judge-failed paths;
only `caveats` differentiates them (success path: empty; failure path:
`["gather judge failed with <status>"]`). The compare/analyze judge-failed
branch in `runJudgePhase` has the same classification problem in another form:
it emits `decision_kind="tie"` and exit 1 even though the providers completed
and only the judge failed. Downstream renderers, the `/bakeoff:run` skill, and
any external dispatcher cannot distinguish "judge completed and found an
unresolved tie" from "judge crashed, here is the unmerged provider set". The
`judge_ran=true` / `judge_rationale=[]` pairing in the failure case is also
misleading: the judge launched but did not complete.

**Proposed change.**

- In `internal/decision/decision.go` `GatherStructuredUnion`, when
  `!artifact.ProviderSucceeded(judgeResult)`:
  - set `decision_kind` to a new value `"provider_union_only"` (not
    `"structured_union"`);
  - keep `judge_ran=true` for backward compatibility, AND additionally set
    `judge_attempted=true` and `judge_completed=false`; on the success path
    set `judge_attempted=true` and `judge_completed=true`;
  - keep `caveats` as today.
- In `internal/commands/researchcmd/run.go` `runJudgePhase`, when either
  compare/analyze judge pass fails:
  - set `decision_kind="judge_failed"` rather than `"tie"`;
  - set `judge_ran=true`, `judge_attempted=true`, `judge_completed=false`;
  - preserve `order_maps`, failed pass statuses, and caveats;
  - return exit code 4.
- On successful compare/analyze judge paths, set `judge_attempted=true` and
  `judge_completed=true` before finalization.
- Update `internal/report/report.go` `renderGather` (see A1) to dispatch on
  the new `provider_union_only` kind for the per-provider rendering. Update
  `renderCompare` / `renderAnalyze` to dispatch on `judge_failed` or
  `judge_completed=false` and render per-provider material without inventing a
  winner.
- Update `internal/manifest/manifest.go` to surface `judge_attempted` and
  `judge_completed` so external tools can read them without parsing caveat
  strings.
- Update `internal/triage/state.go` and `internal/prompt/prompt.go` test
  fixtures that currently mock `decision_kind="structured_union"` only if
  the production code in those packages now needs to handle the new kind;
  otherwise the new kind passes through their existing logic unchanged.
- Add a `decision_test.go` case asserting the new fields on the failure
  branch, and a `researchcmd/run_test.go` case asserting the gather
  judge-failed path produces `decision_kind="provider_union_only"` with
  `judge_completed=false`.
- Add `researchcmd/run_test.go` coverage for compare/analyze judge failures:
  they should produce `decision_kind="judge_failed"`,
  `judge_completed=false`, and exit 4.

**Acceptance criteria.**

- Successful gather judge → `decision_kind="structured_union"`,
  `judge_completed=true`.
- Failed gather judge with providers OK → `decision_kind="provider_union_only"`,
  `judge_completed=false`, caveat preserved.
- Failed compare/analyze judge with providers OK →
  `decision_kind="judge_failed"`, `judge_completed=false`, caveats preserved,
  exit 4.
- Renderers and skill prompts can dispatch on `decision_kind` alone without
  inspecting `caveats` text.
- `bakeoff show` / manifest surface `judge_attempted` and `judge_completed`.

**Relation to judge-retry.** Independent but enabling. The main plan's
judge-only retry detection in the `/bakeoff:run` skill becomes simpler and
more robust when it can dispatch on `decision_kind="provider_union_only"`
plus `judge_completed=false` instead of pattern-matching the caveat string.

### A3. Exit Code Semantics: Launcher Failure vs Judge Failure

**Problem.** `internal/cli/exit.go` defines `ExitRuntimeFailure=1` as the
catch-all non-success exit. `decision.GatherStructuredUnion` returns
exitCode=1 when the judge fails even though both providers succeeded and
their artifacts are durable. The `/bakeoff:run` skill currently treats exit
1 as "launcher failure, do not summarize," which is exactly wrong for the
failed-judge-providers-OK case demonstrated by `2026-05-19-c1db`.

**Proposed change.**

- In `internal/cli/exit.go`, add `ExitDecisionIncomplete = 4` (name
  preserves the "incomplete decision but artifacts usable" intent better
  than `ExitJudgeFailed` because it also covers post-retry exhaustion).
- In `internal/decision/decision.go` `GatherStructuredUnion`, return
  exitCode=4 (not 1) when the judge failed but providers succeeded. The
  research finalization helper extracted in the main plan's section 4 must
  forward this value.
- In `internal/commands/researchcmd/run.go`, return exitCode=4 for
  compare/analyze judge-pass failures with providers succeeded.
- In the (planned) main-plan judge-only retry path, after retries are
  exhausted, the same exit 4 should be returned — this keeps the semantic
  meaning "judge could not complete; provider evidence is durable; retry is
  the right next action".
- Add `apperror.DecisionIncompleteError` and map it to
  `ExitDecisionIncomplete` in `cli.ExitCode`. The research finalization helper
  must return this typed error for exit 4, otherwise the current generic error
  path will still map to exit 1.
- Update `internal/summary/summary.go` `CommandStatus` so exit 4 maps to
  `"decision_incomplete"` in JSON summaries.
- In `commands/run.md`, `skills/bakeoff/SKILL.md`, and `docs/cli-reference.md`,
  document exit 4 explicitly: "exit 4 — decision incomplete (judge failed
  or did not converge); provider artifacts are durable; rerun
  `--judge-only` is recommended."
- Update `internal/cli/exit_test.go` and any tests that assert exit codes
  for the gather-judge-failed path.

**Acceptance criteria.**

- A gather run with both providers OK and judge crashed exits with code 4,
  not 1.
- The skill recognizes exit 4 as the trigger to summarize using the durable
  provider `final.json` files and recommend `rerun --judge-only`.
- Existing exit-1 behavior for true launcher faults (binary missing, work
  order invalid, signal, etc.) is unchanged.

**Relation to judge-retry.** Blocks the `/bakeoff:run` skill update in the
main plan's section 6 ("Update Failure Recommendation UX"). The skill cannot
correctly recommend judge-only retry on the basis of exit code alone until
exit 4 exists. Ship A3 before, or in the same patch as, the skill change.

### A5. Promote Judge-Failure Status to a Top-Level Callout in `report.md`

**Problem.** `internal/report/report.go` `Render()` always appends
`caveats(decision)` last, after Findings/Conflicts/Unknowns. In a
failed-judge run the caveats block is the only signal that anything went
wrong, and it appears at the bottom of an otherwise mostly-empty report
(today) or a per-provider report (after A1). A human glancing at the file
sees empty sections first and the explanation last.

**Proposed change.**

- In `internal/report/report.go` `Render()`, when `judge_completed=false`
  (per A2) or the legacy caveat pattern matches, emit a `## Status` block
  immediately under the title (before `## Outcome`) with one bulleted line
  per caveat and an explicit call-to-action line such as
  `Action: judge failed; provider claims below; consider \`bakeoff rerun <id> --judge-only\`.`
- Keep the existing `## Caveats` section at the bottom so audit tools
  parsing the old layout still find the strings; do not duplicate the
  content — the bottom block can be omitted in the failed-judge case once
  the top block is rendered, or kept as-is (decide during implementation;
  the user-visible win comes from the top block).
- Add a `report_test.go` case asserting the failed-judge render contains
  `## Status` before `## Outcome` and that the action line references
  `rerun --judge-only`.

**Acceptance criteria.**

- `report.md` for a failed-judge-providers-OK run shows the failure status
  within the first ~10 lines.
- The action line surfaces the recommended next command.
- Successful runs render unchanged (no `## Status` block).

**Relation to judge-retry.** Depends on A2 for the cleanest dispatch
condition (`judge_completed=false`), and pairs with the main plan's section
6 skill update — together they ensure both the human report and the
plugin-driven recommendation point at judge-only retry.

### A6. Classify the Judge Failure Kind

**Problem.** `judge/status.json` for the cited run carries only
`status="exit_error"`. The stdout payload was the well-known transient
`API Error: The socket connection was closed unexpectedly. For more
information, pass \`verbose: true\` in the second argument to fetch()`. The
main plan's retry policy will want to be conditional: transient API errors
should retry aggressively; prompt-too-large should not retry without
truncation; nonzero-exit with non-transient stderr might need human review.
Without a classification field, retry policy must re-pattern-match stdout
each time, and the human-facing report cannot tell the user at a glance
whether retry is appropriate.

**Proposed change.**

- In `internal/runner/runner.go` (or a sibling `runner/classify.go`),
  introduce a `ClassifyJudgeError(status string, exitCode *int, stdout
  string, stderr string) string` returning one of:
  `"api_transient"`, `"prompt_too_large"`, `"timeout"`,
  `"output_cap"`, `"schema_error"`, `"nonzero_exit"`, `"parse_error"`,
  `"unknown"`. Pattern set (initial, expand later):
  - `api_transient`: stdout contains `"socket connection was closed
    unexpectedly"` OR `"Connection error"` OR HTTP 5xx markers from the
    Anthropic / OpenAI CLIs;
  - `prompt_too_large`: stderr/stdout contains `"context_length"`,
    `"prompt is too long"`, `"max_tokens_exceeded"`;
  - `timeout`: status equals `runner.StatusTimeout` or stdout/stderr match
    timeout markers;
  - `output_cap`: status equals `runner.StatusOutputCap`;
  - `schema_error`: status equals `runner.StatusSchemaError`;
  - `nonzero_exit`: exit code != 0 with no transient marker;
  - `parse_error`: judge ran to exit 0 but final_json parsing failed.
- In the judge writer (`internal/commands/researchcmd/run.go`
  `runSingleJudge` and its writer helpers), set
  `judgeStatus["judge_error_kind"] = ClassifyJudgeError(...)` whenever
  `!artifact.ProviderSucceeded(judgeResult)`. Persist into
  `judge/status.json`.
- Propagate the value into `decision.GatherStructuredUnion` so it appears
  on the `decision.json` document as `judge_error_kind` for renderers and
  the skill to consume without opening `judge/status.json`.
- Surface `judge_error_kind` in the `## Status` block from A5 (e.g.,
  `Judge error kind: api_transient`).
- The retry policy in the main plan can then be conditional: when
  `judge_error_kind=="api_transient"`, retry up to the configured count;
  when `judge_error_kind=="prompt_too_large"`, do not retry and recommend
  a human action; etc. Encode this in the retry policy code, not in this
  appendix item.
- Add unit tests in `runner/classify_test.go` covering each pattern, and
  a `researchcmd/run_test.go` case asserting the value flows into
  `decision.json`.

**Acceptance criteria.**

- `judge/status.json` includes `judge_error_kind` for every failed-judge
  run.
- `decision.json` mirrors `judge_error_kind` at the top level.
- The exact stdout from `runs/2026-05-19-c1db/judge/stdout.txt`
  classifies as `api_transient`.
- The skill / future retry policy can dispatch on `judge_error_kind`
  without opening `judge/stdout.txt`.

**Relation to judge-retry.** Enables conditional retry policy in the main
plan. The main plan can ship retry as unconditional (count-based) first
and then layer A6 to make policy smarter; A6 is not a hard blocker for the
initial retry implementation, but it is a near-term dependency for any
retry policy that distinguishes "should retry" from "should escalate".

## Appendix: Provider Status Projection Tightening Items (from run 2026-05-19-f4f5)

This appendix folds in validated follow-on items from the provider-status drift
investigation. They are not required to make judge-only retry work, but they
reduce output-contract drift in the same surfaces touched by this plan:
`manifest.json`, human reports, and plugin-facing summaries.

### B1. F-009 / F-010: Normalize Manifest Provider Status Without Breaking `status`

**Validation.** Confirmed. `internal/manifest/manifest.go:226-239` builds
`manifest.providers.<id>` with an inline map and currently assigns raw
`statusInfo["status"]` to `status`. `summary.CompactStatus` exists at
`internal/summary/summary.go:125-134`.

**Decision.** Use the F-010 compatibility shape, not the F-009 status flip:

- keep `manifest.providers.<id>.status` as the raw runner status;
- add `compact_status: summary.CompactStatus(statusInfo["status"])`;
- do not add redundant `raw_status` while `status` remains raw;
- copy these eight passthrough fields from `decision.provider_statuses.<id>`:
  `exit_code`, `output_bytes`, `stderr_truncated`, `stdout_truncated`,
  `stdout_observed_bytes`, `stderr_observed_bytes`, `scope_enforcement`,
  `stderr_path`;
- keep using `compactNilMap` to elide absent values.

This keeps existing consumers of `manifest.providers.<id>.status` stable while
still adding the compact status contract needed by summaries and downstream
automation.

**Tests.** Add or extend `internal/manifest/manifest_test.go` with a fixture
that asserts:

- `status` remains the raw runner status;
- `compact_status` is the value returned by `summary.CompactStatus`;
- the eight passthrough fields survive from `decision.provider_statuses`;
- shared fields match between manifest provider summaries and decision provider
  statuses.

### B2. T1: Console `basis=` vs Research `spine_tiebreak`

**Validation.** Confirmed. The console line in
`internal/commands/researchcmd/run.go:507` prints `basis=<value>`, while
research analyze decisions write `spine_tiebreak` at
`internal/decision/decision.go:165`. Build mode uses `selection_basis`, which is
a different concept and should not change.

**Change.** Rename the research console literal from `basis=` to
`spine_tiebreak=`. Do not add a `basis` alias to research `decision.json`.

### B3. T2: Manifest Passthrough Fields

**Validation.** Confirmed and subsumed by B1. The missing fields are
`exit_code`, `output_bytes`, `stderr_truncated`, `stdout_truncated`,
`stdout_observed_bytes`, `stderr_observed_bytes`, `scope_enforcement`, and
`stderr_path`.

**Change.** Ship these fields as part of the B1 manifest projection update, not
as a separate abstraction.

### B4. T3: `meta.facet` vs `manifest.facet_id`

**Validation.** Confirmed with adjustment. These fields are related but not the
same shape: `meta.facet` is the full facet object, while `manifest.facet_id` is
the hoisted id. `internal/commands/lscmd/ls.go:93` already reads
`row["facet_id"]`, so renaming would break existing consumers.

**Change.** Do not rename either field. Add a doc comment near the manifest
`facet_id` struct / projection stating that `facet_id` is the hoisted
`meta.facet.id`, and document the relationship in `docs/work-orders.md` if it
is not already clear there.

### B5. T4: Provider Status Report `Stderr` Column

**Validation.** Confirmed. `internal/report/report.go:157-209` renders the
provider status table. It currently puts retained `stderr_bytes` in the Stderr
column and places `stderr_observed_bytes` in Notes when the retained and
observed byte counts differ.

**Change.** Inline observed-byte context into the byte cell when truncation
occurred:

- for stderr, render `4.0 KB (obs 18.2 KB)` style text when
  `stderr_truncated=true` and observed bytes differ;
- apply the same formatting to stdout for symmetry;
- remove the corresponding `stdout observed ...` and `stderr observed ...`
  Notes entries once the cells carry the information;
- keep the `stdout truncated` / `stderr truncated` note only if it still adds
  value beyond the cell text. Prefer avoiding duplicate signal.

**Tests.** Update `internal/report/report_test.go` to assert the table contains
the inline observed-byte text and does not duplicate the same observed-byte
message in Notes.
