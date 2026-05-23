# Actionable items from 2026-05-23 reports - deduped plan

This plan extracts substantive implementation work from the actual bakeoff
reports and escalation reports referenced by
`docs/session-audits/2026-05-23-consolidated-plan.md`.

Relationship to the consolidated plan: these documents are complementary. The
consolidated plan intentionally dropped the substantive Go follow-ups at
`docs/session-audits/2026-05-23-consolidated-plan.md:289` because they are
feature/bug work on top of run outputs, not session-audit defects in the
bakeoff workflow. This document is the tracking plan for that dropped Go work;
it is not an alternative to the consolidated plan.

It intentionally excludes session-audit findings about the bakeoff CLI/plugin
itself unless the actual reports independently identified the same work.

## Source artifacts

Source reports:

- `runs/2026-05-23-e57e/report.md` - build orchestration compare
- `runs/2026-05-23-bb94/report.md` - provider failure artifact compare
- `runs/2026-05-23-db11/report.md` - supervisor hardening compare
- `runs/2026-05-23-871b/report.md` - supervisor hardening implementation plan
- `runs/2026-05-23-1792/report.md` - decision typing vs validators compare
- `runs/2026-05-23-fddc/report.md` - bakeoff robustness code-review gather

Escalation reports:

- `runs/2026-05-23-95b9/report.md` - dispute escalation for `e57e`
- `runs/2026-05-23-ee29/report.md` - dispute escalation for `bb94`
- `runs/2026-05-23-0aee/report.md` - dispute escalation for `871b`
- `runs/2026-05-23-276a/report.md` - witness escalation for `fddc`
- `runs/2026-05-23-b6f3/report.md` - dispute escalation for `fddc`

Triage artifacts:

- `runs/2026-05-23-fddc/triage/triage.md`
- `runs/2026-05-23-fddc/triage/final.json`
- `runs/2026-05-23-276a/triage/triage.md`
- `runs/2026-05-23-b6f3/triage/triage.md`

## Filtering decisions

Discarded as noise, non-actionable, or not ready for code:

- The `fddc` uppercase status-code classifier issue: false positive because the
  classifier lowercases before matching.
- Positive confirmations such as "required-scope enforcement exists."
- The original scope fallback/hard-fail language from old item 9: current
  `internal/scope/scope.go:116-117` already hard-fails required fallback, and
  `internal/scope/scope.go:151-152` already records `fallback_reason`.
- `fddc` `T-027`, collapsed into the broader "promote scope fallback caveats"
  item.
- The old kill-after-reap decision item, folded into runner lifecycle hardening
  with a chosen direction.
- The old failure schema breadth decision item, folded into the failure artifact
  item with a first-pass schema decision.
- `276a` witness escalation findings: supported the source report and added no
  new material.
- `276a` and `b6f3` triage outputs: both selected zero source findings, so they
  do not add implementation items beyond the escalation reports themselves.

Deferred due to behavior-risk or evidence gaps:

- Retry/backoff behavior changes are P2 until current retry behavior is
  reproduced and documented with tests or trace artifacts.
- Classifier tightening is P2 until representative live provider failure
  samples are collected and saved.
- Windows Job Object cleanup is demoted out of P0 because the handle ownership
  shape needs a deliberate platform-specific implementation pass.

Tracking note: this plan does not claim every item already has a bead/issue.
Create beads when scheduling an implementation batch, or keep this document as
the tracking artifact for unscheduled work.

## Priority 0 - concrete implementation work

### 1. Gate-first verifier execution

Implement gate-first build verifier execution.

Requirements:

- Run all `kind: "gate"` verifiers before `kind: "metric"` verifiers for each
  candidate.
- If a gate fails, skip remaining metric verifiers for that candidate.
- Preserve diagnostics by emitting explicit skipped-metric placeholders rather
  than silently omitting result entries.
- Keep judge inputs deterministic and ID-keyed.
- Update any status/schema/report expectations needed for a new skipped metric
  placeholder in the same change.

Primary code anchors:

- `internal/buildverify/buildverify.go:114` currently iterates verifiers in
  declared order.
- `internal/buildverify/buildverify.go:140-149` handles metric parsing before
  later gate failure is known.
- `internal/buildverify/buildverify.go:164-167` marks a failed gate but does
  not stop later metric execution.
- `internal/buildverify/buildverify.go:310-317` and
  `internal/buildverify/buildverify.go:562-565` compare metrics by verifier ID,
  so gate/metric partitioning can preserve deterministic judge inputs.
- `internal/workorder/workorder.go:141-149` defines `VerifierSpec` without
  dependency, purity, or ordering fields.

Evidence:

- `runs/2026-05-23-e57e/report.md` - `F-001`, `F-003`, `F-011`
- `runs/2026-05-23-95b9/report.md` - `D-006`, `D-009`

Confidence: high.

### 2. Provider failure artifact

Add conditional `providers/<id>/failure.json` for failed providers.

First-pass schema decision:

- Use the broad structured schema already implied by the P0 requirements:
  provider ID, backend, model, prompt flavor when available, status, failure
  kind, exit code, truncation flags, cap flags, byte counts, stdout/stderr tail
  summaries, and raw artifact pointers.
- Defer exact duplicate-line collapsing. It can be added later as a display
  adjunct, but the first implementation should preserve raw tails and avoid
  lossy summarization.

Requirements:

- Generate from runner result and provider metadata, not by parsing provider
  output shape.
- Mirror `runner.ClassifyFailure` output rather than inventing a second failure
  classifier.
- Keep raw `stdout.txt`, `stderr.txt`, `last-message.txt`, and `final.json`
  behavior stable.
- Write `failure.json` only for failed provider runs; successful provider
  artifact shape should not grow unless downstream code explicitly requires it.

Primary code anchors:

- `internal/artifact/artifact.go:182-200` writes provider `stdout.txt`,
  `stderr.txt`, `status.json`, and successful `final.json`.
- `internal/runner/runner.go:628-646` and
  `internal/runner/runner.go:843-865` already preserve head/tail output for
  artifacts.
- `internal/runner/classify.go:16-60` contains the existing failure classifier
  to mirror into `failure.json`.
- `internal/artifact/artifact.go:90-105` shows current status metadata fields
  that should remain stable while `failure.json` adds structured access.
- `internal/commands/researchcmd/run.go:517-534` and
  `internal/commands/buildcmd/providers.go:119-135` call the provider artifact
  writer after provider execution.

Evidence:

- `runs/2026-05-23-bb94/report.md` - `F-001`, `F-003`, `F-004`,
  `F-007`, `F-009`, `F-011`, `F-012`
- `runs/2026-05-23-ee29/report.md` - `D-001`, `D-003`

Confidence: high for artifact need, medium-high for chosen schema breadth.

### 3. Failure artifact integration

Wire `failure.json` into downstream artifact consumers.

Requirements:

- Add `failure.json` to manifest provider evidence fingerprints.
- Include provider failure artifacts in triage input hashing/staleness checks.
- Surface provider failure summaries or paths in triage prompt payloads.
- Add `failure.json` to citation lookup so citations can point at structured
  failure artifacts.
- Add tests for manifest fingerprinting and triage staleness when
  `failure.json` changes.

Primary code anchors:

- `internal/manifest/manifest.go:418` currently enumerates provider evidence
  artifacts without `failure.json`.
- `internal/manifest/manifest.go:432` adds only those named provider evidence
  files into artifact paths.
- `internal/triage/state.go:24-41` hashes `decision.json`, `report.md`, and
  `work-order.json`, but not provider failure artifacts.
- `internal/commands/triagecmd/triage.go:169-189` builds the triage prompt
  payload without provider failure summaries.
- `internal/triage/citation.go:48-57` collects `providers/*/final.json` and
  judge results, but not `providers/*/failure.json`.

Evidence:

- `runs/2026-05-23-bb94/report.md` - `F-002`, `F-006`, `F-013`
- `runs/2026-05-23-ee29/report.md` - `D-004`, `D-007`

Confidence: high.

### 4. Incremental runner lifecycle hardening

Use targeted hardening rather than replacing the runner with a typed state
machine.

Requirements:

- Add `go.uber.org/goleak` and `TestMain` in `internal/runner/runner_test.go`.
- Add `context.AfterFunc` or an equivalent cancellation backstop in
  `runProcess` so cancellation bounds all errgroup goroutines.
- Fix `terminateAndWait` kill-after-reap behavior by deleting the post-reap
  kill path in the `case <-waitDone` branch. Do not add an atomic `reaped`
  guard unless implementation review finds a concrete platform-specific reason
  to keep a guarded call.
- Keep changes incremental and test-driven.

Primary code anchors:

- `internal/runner/runner.go:276-331` wires the process errgroup, copy
  goroutines, `waitDone`, and final `group.Wait`.
- `internal/runner/runner.go:735-750` currently kills again after receiving
  from `waitDone`.
- `internal/runner/runner_test.go:1-22` has no `TestMain` and no `goleak`.
- `go.mod` and `go.sum` currently have no `go.uber.org/goleak` dependency.

Evidence:

- `runs/2026-05-23-db11/report.md` - `F-002`, `F-005`, `F-006`
- `runs/2026-05-23-871b/report.md` - `R-008`, `R-009`, `R-010`,
  actionable `F-001`
- `runs/2026-05-23-0aee/report.md` - `D-001`, `D-003`

Confidence: high.

### 5. Runner race/leak test suite

Add targeted runner tests for the lifecycle risks surfaced by the reports.

Test coverage:

- cancel during stdout/stderr copy
- provider killed before exit
- stderr overflow during stop
- duplicate terminal status
- close-before-drain ordering
- `os/exec` `WaitDelay`
- `StdoutPipe`/`Wait` ordering contract

Primary code anchors:

- `internal/runner/runner.go:250` sets `cmd.WaitDelay`.
- `internal/runner/runner.go:256-287` uses `StdoutPipe`/`StderrPipe` and then
  calls `cmd.Wait` after copy goroutines finish.
- `internal/runner/runner.go:711-733` and
  `internal/runner/runner.go:735-750` contain the output-cap/timeout stop
  paths that need close/drain assertions.
- `internal/runner/runner.go:904-945` creates terminal results and salvage
  status.
- Existing nearby tests include cancellation and process-group coverage at
  `internal/runner/runner_test.go:394-429`, but not the full set above.

Evidence:

- `runs/2026-05-23-db11/report.md` - `F-007`, `F-009`, `F-010`, `F-013`
- `runs/2026-05-23-871b/report.md` - `R-011`, `R-012`, `R-013`

Confidence: high.

### 6. Capability cache invalidation

Fix capability cache invalidation and failed-probe poisoning.

Requirements:

- Re-probe cached `ProbeError` or `Available:false` entries.
- Add TTL, executable path/version stamp, or another invalidation mechanism.
- Prevent one transient failed probe from poisoning the registry for the
  factory lifetime.
- Avoid stale capability data breaking research and build scope enforcement.

Primary code anchors:

- `internal/provider/provider.go:244-253` returns cached scope capabilities to
  callers.
- `internal/provider/provider.go:256-274` stores probe results unconditionally.
- `internal/provider/provider.go:277-285` records probe failures as
  `Available:false` with `ProbeError`.
- `internal/cli/factory.go:20-28` and `internal/cli/factory.go:47-49` keep one
  registry on the command factory, so a poisoned entry can live for the factory
  lifetime.

Evidence:

- `runs/2026-05-23-fddc/report.md` - `F-001`, `F-012`, `F-016`, `F-018`,
  `F-020`
- `runs/2026-05-23-fddc/triage/triage.md` - `T-001`, `T-012`, `T-016`,
  `T-020`
- `runs/2026-05-23-b6f3/report.md` - `D-002`

Confidence: high.

### 7. Panic-safe and bounded capability probing

Make `getOrProbe` panic-safe and waiter-bounded.

Requirements:

- Always close or resolve `ready`, even when probing panics.
- Store a recoverable error state instead of leaving waiters blocked forever.
- Respect `ctx.Done` while waiting on an existing in-flight probe.
- Prefer changing the registry API enough to pass waiter context explicitly
  over hiding cancellation in callers that cannot actually unblock `<-ready`.

Primary code anchors:

- `internal/provider/provider.go:256-261` waits on `entry.ready` without a
  context select.
- `internal/provider/provider.go:263-272` closes `entry.ready` only after
  `probe()` returns normally.

Evidence:

- `runs/2026-05-23-fddc/report.md` - `F-003`, `F-029`
- `runs/2026-05-23-fddc/triage/triage.md` - `T-003`, `T-029`
- `runs/2026-05-23-b6f3/report.md` - `D-003`

Confidence: high.

### 8. Build scope policy metadata

Tighten build-mode scope policy by documenting and encoding the actual strict
minimum controls, not by reimplementing general scope fallback behavior.

Chosen direction:

- Keep the stricter build-mode hard-fail behavior for controls that are
  prerequisites for a noninteractive build worker to edit safely.
- Make that strictness explicit in metadata and tests so it is not confused
  with ordinary `best_effort` fallback semantics.
- Do not relax build behavior in the first pass. If product direction later
  wants `best_effort` build runs to proceed under weaker controls, treat that as
  a separate user-facing policy change.

Requirements:

- Do not change `internal/scope/scope.go` fallback recording or required
  hard-fail behavior; it already exists.
- Add explicit build-scope policy metadata for hard-fail prerequisites, such as
  `minimum_controls` or a similarly concrete field, when
  `mustFailBuildScope` blocks a backend.
- Add tests showing that `best_effort` build hard-fails only for these build
  execution prerequisites, while ordinary fallback reasons remain partial under
  `best_effort` and fail under `required`.
- Update docs or report wording if needed so operators understand why
  `best_effort` can still fail a build provider that cannot satisfy minimum
  editing controls.

Primary code anchors:

- `internal/scope/scope.go:116-117` already hard-fails `required` fallback.
- `internal/scope/scope.go:151-152` already records `fallback_reason`.
- `internal/commands/buildcmd/scope.go:93-104` hard-fails when
  `mustFailBuildScope` is true, before checking `required` vs `best_effort`.
- `internal/commands/buildcmd/scope.go:116-123` handles ordinary fallback
  reasons under `required` vs `best_effort`.
- `internal/commands/buildcmd/scope.go:129-139` defines the backend-specific
  hard-fail prerequisites.

Evidence:

- `runs/2026-05-23-fddc/report.md` - narrowed reading of `F-025`
- `runs/2026-05-23-fddc/triage/triage.md` - narrowed reading of `T-025`

Confidence: high that the original fallback requirement was stale; medium-high
for the chosen metadata-first policy fix.

### 9. Scope fallback caveats

Promote scope fallback/degradation into top-level operator-facing output.

Requirements:

- Include degraded scope caveats in top-level decision caveats, `bakeoff show`
  summary, or both.
- Keep provider-row fallback details, but do not require operators to inspect
  table notes to know the run executed under partial/advisory scope.
- Deduplicate caveats so the same fallback reason does not appear repeatedly for
  every provider unless provider specificity matters.

Primary code anchors:

- `internal/report/report.go:482-487` already appends provider-row fallback
  notes.
- `internal/artifact/artifact.go:102-105` preserves `scope_enforcement` in
  provider status.
- `internal/decision/decision.go:27-41` builds base decisions without scope
  caveat promotion.
- `internal/decision/decision.go:425-439` currently promotes protected-path
  caveats, providing a nearby pattern for provider-status-derived caveats.

Evidence:

- `runs/2026-05-23-fddc/report.md` - `F-026`, `F-027`
- `runs/2026-05-23-fddc/triage/triage.md` - `T-026`
- `runs/2026-05-23-b6f3/report.md` - `D-001`

Confidence: high.

## Priority 1 - decisions or design gates before implementation

### 10. Verifier concurrency model

Decision/design needed: design bounded verifier/candidate concurrency.

Known constraints:

- Provider-level concurrency already exists.
- Unconstrained per-verifier parallelism can collide through shared
  `providerCWD`.
- Any concurrency model needs a configurable limit and deterministic output.

Primary code anchors:

- `internal/commands/buildcmd/providers.go:28-35` already runs providers under
  an errgroup.
- `internal/commands/buildcmd/providers.go:184-186` invokes verifier execution
  with a shared provider CWD for that provider.

Evidence:

- `runs/2026-05-23-e57e/report.md` - `F-005`, `F-009`
- `runs/2026-05-23-95b9/report.md` - `D-002`, `D-007`, `D-010`

Confidence: high.

### 11. Windows Job Object cleanup

Add Windows Job Object support for provider process-tree cleanup, but do it as
a platform-specific design pass after the runner test baseline exists.

Chosen direction:

- Prefer a command-scoped process controller owned by `runProcess`, with a
  post-start attach step for Windows Job Objects.
- Avoid a package-level PID-to-job map unless the controller approach proves too
  invasive; global PID maps are easier to leak and harder to test.

Requirements:

- Use Windows Job Objects to terminate provider process trees, not just the
  direct child process.
- Preserve POSIX process-group behavior.
- Add build-tagged coverage and, if possible, run at least one Windows CI/manual
  validation before marking complete.
- Do not bundle this into the first POSIX runner hardening PR unless the handle
  ownership shape is already proven.

Primary code anchors:

- `internal/runner/process_windows.go:10` currently makes
  `configureProcessGroup` a no-op.
- `internal/runner/process_windows.go:12-24` only calls `process.Kill`.
- `internal/runner/process_unix.go:28-45` is the POSIX behavior that must stay
  stable.

Evidence:

- `runs/2026-05-23-db11/report.md` - `F-003`, `F-011`, `F-012`
- `runs/2026-05-23-871b/report.md` - `R-014`, actionable `F-003`
- `runs/2026-05-23-0aee/report.md` - `D-002`

Confidence: high on the gap, medium on implementation shape until design is
spiked.

### 12. Decision artifact validator surface

Keep `decision.json` map-based and add targeted validators rather than one
strict typed struct.

Chosen direction:

- Implement a minimal `ValidateDecision(kind, doc)` surface plus stronger
  `readRequiredJSON` checks at read boundaries.
- Defer a broad validator family across decision, manifest, triage, and
  artifact packages until repeated drift shows the smaller validator is
  insufficient.

Requirements:

- Validate required top-level fields for the decision kinds currently emitted.
- Keep compatibility with existing map-based decision construction.
- Add tests around malformed or incomplete `decision.json` inputs.
- Do not start a repo-wide artifact schema framework as part of this item.

Evidence:

- `runs/2026-05-23-1792/report.md` - `F-001`, `F-002`, `F-003`, `F-004`,
  `F-007`, `F-008`

Confidence: medium-high.

### 13. Scope product semantics

Decision/documentation needed after items 8 and 9 land:

- Default `best_effort` behavior.
- Why build mode can hard-fail minimum execution controls even under
  `best_effort`.
- Gemini/Copilot required codebase/web unsupported behavior.
- `isolated_cwd` is working-directory isolation, not a true filesystem sandbox.

Evidence:

- `runs/2026-05-23-fddc/report.md` - `F-009`, `F-014`, `F-015`
- `runs/2026-05-23-fddc/triage/triage.md` - `T-009`, `T-014`, `T-015`

Confidence: high for current behavior, medium for product direction.

## Priority 2 - preconditioned or lower-confidence refinements

### 14. Retry/backoff and non-zero schema-error retry behavior

Do not implement retry policy changes yet. First verify and document current
behavior with tests or saved trace artifacts.

Preconditions:

- Prove the current behavior for transient failure classifications:
  `api_transient`, `rate_or_quota_limited`, and `timeout`.
- Prove the current behavior for non-zero `schema_error` results and format
  retry.
- Decide whether classifier output is intended to be annotation-only or retry
  policy input.

If later implementing retries:

- Add class-aware retry/backoff with jitter and caps.
- Keep format retry behavior separate from transient retry behavior.
- Apply consistently to workers and judge/triage provider calls, or document
  exceptions.

Primary code anchors:

- `internal/runner/runner.go:408-417` implements format retry after the first
  provider run.
- `internal/runner/classify.go:16-60` classifies transient and schema-like
  failures.
- `internal/commands/researchcmd/run.go:523-534`,
  `internal/commands/buildcmd/providers.go:123-135`, and
  `internal/commands/buildcmd/judge.go:130-160` call provider execution without
  a class-aware retry wrapper.

Evidence:

- `runs/2026-05-23-fddc/report.md` - `F-004`, `F-005`, `F-013`, `F-021`
- `runs/2026-05-23-fddc/triage/triage.md` - `T-004`, `T-005`, `T-013`,
  `T-021`

Confidence: medium until current behavior is reproduced in focused tests.

### 15. Classifier sample replay and heuristic cleanup

Tighten failure classifier heuristics only after replaying live provider
samples.

Precondition task:

- Collect representative live failure samples from the supported provider CLIs
  and save them as test fixtures or trace artifacts before changing heuristics.
- Include at least one sample each for auth/permission, quota/rate limit,
  timeout, transient API/server failure, billing/account failure if available,
  and benign text that should not classify as a failure kind.
- Record provider/backend and status context for each sample; avoid heuristic
  changes based only on synthetic strings.

Candidate changes after samples exist:

- Narrow `final_json` + `valid` matching.
- Avoid bare `auth` over-match.
- Avoid bare `429` and `timed out` over-match without provider-error framing.
- Add billing/account classes, or explicitly document why those remain generic.

Primary code anchors:

- `internal/runner/classify.go:42-60` handles auth/rate/transient/schema
  heuristics.
- `internal/runner/classify.go:178-192` contains the `clearFinalJSONError`
  helper whose broad `valid` matching needs sample-backed review.

Evidence:

- `runs/2026-05-23-fddc/report.md` - `F-007`, `F-008`, `F-022`, `F-023`,
  `F-030`
- `runs/2026-05-23-fddc/triage/triage.md` - `T-007`, `T-008`, `T-022`,
  `T-023`, `T-030`

Confidence: medium-low until live samples are checked.

## Suggested execution order

1. Runner lifecycle hardening and tests (`items 4, 5`).
2. Capability probe cache and panic/waiter safety (`items 6, 7`).
3. Scope build-policy metadata and caveat surfacing (`items 8, 9, 13`).
4. Failure artifact schema and integration (`items 2, 3`).
5. Gate-first verifier execution (`item 1`).
6. Verifier concurrency design (`item 10`).
7. Decision artifact validators (`item 12`).
8. Windows Job Object cleanup only after the runner test baseline and a Windows
   validation path exist (`item 11`).
9. Retry/backoff and classifier work only after their precondition artifacts
   exist (`items 14, 15`).

## Definition of done

- Each implementation PR references the relevant item number and preserves the
  report evidence links needed for verification.
- Priority 0 items add or update focused tests for the named behavior.
- Priority 1 items have their chosen direction, design note, or product decision
  recorded before code changes begin.
- Priority 2 items are not implemented until their explicit precondition
  artifacts exist.
- Artifact/schema changes update downstream consumers and staleness checks in
  the same implementation batch unless the plan explicitly splits them.
