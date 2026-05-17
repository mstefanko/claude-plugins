# Go Post-Cutover Cleanup Implementation Plan

Date: 2026-05-17
Status: collecting dogfood findings
Scope: Go-only cleanup items discovered while dogfooding `bakeoff-go`; defer
behavior-changing cleanup until after the Go cutover unless a finding blocks
parity or safe operation.

## Context

The Go port is currently being exercised through live dogfood runs. During the
parity period, Python remains the behavior oracle, so issues that mirror Python
should usually be recorded here instead of fixed immediately in Go. After
cutover, use this file to batch cleanup of ledger contracts, manifest coverage,
JSON summary surfaces, and internal duplication.

## Findings Collected

### 1. Verify skips provider and judge evidence

Priority: P2

Source: live Go dogfood run `ledger-manifest-summary-live-go`

Files:
- `internal/manifest/manifest.go`
- `internal/verify/verify.go`

Current behavior:
- `manifest.FingerprintArtifacts` fingerprints the core replay artifacts:
  `work-order.json`, optional review-context files, `decision.json`,
  `meta.json`, `report.md`, and selected triage outputs.
- `runs verify` validates `manifest.json`, checks `manifest.RequiredArtifacts`,
  and verifies only the entries present in `artifact_fingerprints`.
- Provider and judge evidence such as `providers/*/status.json`,
  `providers/*/final.json`, `providers/*/last-message.txt`,
  `judge/status.json`, and `judge/result.json` is not fingerprinted.

Risk:
- A run can pass `runs verify` even if important provider or judge evidence was
  changed, removed, or mismatched after the run.
- This weakens the replay/audit value of the run ledger described in the
  README.

Notes:
- This mirrors the Python oracle, so it is not a Go-port parity bug.
- Treat this as a post-cutover contract tightening unless later dogfood shows
  it blocks safe operation.

Possible implementation direction:
- Define a ledger artifact inventory that distinguishes required core files,
  optional review files, provider artifacts, judge artifacts, triage artifacts,
  and diagnostic/transient artifacts.
- Expand manifest fingerprinting to include stable provider and judge evidence.
- Decide whether large or noisy outputs such as `stdout.txt`, `stderr.txt`, and
  repair artifacts should be fingerprinted, summarized, or explicitly excluded.
- Add tests that mutate provider and judge artifacts and assert
  `runs verify` reports the mismatch.

### 2. Summary surfaces can drift independently

Priority: P3

Source: live Go dogfood run `ledger-manifest-summary-live-go`

Files:
- `internal/summary/summary.go`
- `internal/manifest/manifest.go`
- `internal/decision/decision.go`
- `internal/artifact/artifact.go`

Current behavior:
- `research --json` builds provider summaries from in-memory worker results.
- `manifest.json` builds provider summaries from `meta.resolved_models` and
  `decision.provider_statuses`.
- `decision.provider_statuses` is built from `artifact.StatusWithoutPayload`.
- These surfaces intentionally expose different fields today, but the field
  vocabulary is not centralized.

Risk:
- Future changes can update one summary surface while silently missing another.
- Contract fields such as status, raw status, byte counts, model metadata,
  scope, and final JSON source can diverge without a single obvious review
  point.

Notes:
- This also mirrors the Python oracle, so it is not a Go-port parity bug.
- The immediate issue is maintainability and contract clarity, not current run
  correctness.

Possible implementation direction:
- Create a small shared package or helper that owns provider status projection
  from raw runner/artifact state into the supported summary shapes.
- Keep intentionally different command and manifest schemas, but document those
  differences in code and tests.
- Add golden or table-driven tests for `research --json`, `manifest.json`,
  `ls --json`, and `runs verify --json` so schema drift is explicit.

### 3. Runner status vocabulary and edge-case artifacts need a single contract

Priority: P2

Source: live Go dogfood run `runner-lifecycle-status-live-go`

Files:
- `internal/runner/runner.go`
- `internal/scope/scope.go`
- `internal/commands/researchcmd/run.go`
- `internal/artifact/artifact.go`
- `internal/summary/summary.go`
- `scripts/parity-go.py`

Current behavior:
- `internal/runner` owns the main status constants: `ok`,
  `ok_after_format_retry`, `timeout`, `output_cap`, `missing_provider`,
  `exit_error`, `schema_error`, and `cancelled`.
- `scope_error` is produced by `internal/scope` rather than by the runner
  status vocabulary.
- `ScopeErrorResult` and `internalErrorResult` produce thinner provider result
  maps than normal runner results; they omit some observed-byte, truncation, and
  `io` metadata that successful or runner-produced failures carry.
- Cancellation and output-cap behavior is covered by parity cases, but the
  report did not find a direct unit test for `RunProvider` returning
  `StatusCancelled` from a canceled context.
- If stdout output cap and wall-clock timeout coincide, the current runner
  reports `output_cap`; that may be correct, but the combined precedence should
  be documented and pinned against the oracle before cleanup.

Risk:
- Downstream summaries, reports, and manifest logic can accidentally treat
  runner, scope, and internal synthesized statuses differently.
- Some provider failure artifacts may not satisfy the same status metadata
  expectations as normal runner results.
- Future runner changes could regress cancellation or output-cap precedence
  without a small unit-level test catching the exact path.

Notes:
- The live run itself succeeded: both providers and judge completed with
  `status: ok`, Codex used `final_json_source: last_message`, and stderr
  truncation metadata was recorded.
- This is mostly post-cutover cleanup and test hardening, not evidence that the
  current Go port failed the dogfood run.

Possible implementation direction:
- Centralize Bakeoff status constants, including `scope_error`, in one package
  or document why `scope_error` intentionally lives outside the runner.
- Add a normalizer/helper for synthesized provider results so scope and
  internal errors include a consistent status artifact shape.
- Add unit tests for direct context cancellation and timeout-plus-output-cap
  precedence in `internal/runner`.
- Extend parity coverage only after confirming Python oracle behavior for the
  combined timeout/output-cap path.

### 4. Review-context and rerun replay invariants need tightening

Priority: P2

Source: live Go dogfood run `review-context-auto-triage-live-go`

Files:
- `internal/commands/researchcmd/run.go`
- `internal/commands/reruncmd/rerun.go`
- `internal/reviewcontext/reviewcontext.go`
- `internal/triage/state.go`
- `internal/manifest/manifest.go`
- `scripts/parity-go.py`

Current behavior:
- `research --base main --diff` writes `source-work-order.json`,
  `review-context.md`, `review-context.json`, and an effective
  `work-order.json`.
- Code-review facet runs auto-triage after a successful structured-union
  decision.
- `rerun` replays the source run's effective `work-order.json` and copies
  `source-work-order.json`, `review-context.md`, and `review-context.json` from
  the source run without recapturing git context.
- `copyReplayContextArtifacts` copies each review-context artifact independently
  and silently skips missing files.
- Manifest artifact paths and fingerprints also treat the review-context files
  independently when they are present.
- `runs verify` verifies review-context fingerprints when those entries are in
  `manifest.json`, but the files are not required as an all-or-none set for
  review-context runs.
- Triage freshness hashes only `decision.json`, `report.md`, and
  `work-order.json`; direct changes to copied `source-work-order.json`,
  `review-context.md`, or `review-context.json` do not make triage stale unless
  they also change the effective work order.
- With `--force`, `RunResearch` removes an existing target run directory before
  generated review context is captured, so a later capture failure can delete a
  previous ledger.
- Generated review-context git subprocesses do not accept the research command
  context; `RunResearch` calls `reviewcontext.Build` without `ctx`, and
  `reviewcontext` uses `exec.Command(...).Run()` for git commands.
- Code-review auto-triage suppresses `single_provider_only`, even though that
  can still be a successful research exit. Decide whether this should auto-run
  triage, only recommend triage, or be documented as an intentional exception.

Risk:
- A partial source run or interrupted copy can produce rerun ledgers with only a
  subset of review-context artifacts while still continuing.
- Review-context artifacts can drift independently from triage freshness.
- A failed forced recapture can destroy an existing run before the replacement
  is known to be capturable.
- The Go parity harness currently has ordinary rerun coverage, but it does not
  cover `research --base/--diff` or review-context copy replay.

Notes:
- The live run succeeded and exercised the happy path: generated review context
  was captured, auto-triage completed, `runs verify` checked 10 fingerprints,
  and `ls --json` reported `triage_state: yes`.
- Some report observations appear intentional or policy-shaped rather than
  cleanup requirements: review context for non-code-review facets currently
  proceeds with a note, manifest review-context summaries intentionally expose a
  small field allowlist, and detached `HEAD` still records `head_commit`.

Possible implementation direction:
- Treat `source-work-order.json`, `review-context.md`, and
  `review-context.json` as an all-or-none review-context artifact set in replay,
  manifest generation, and verification.
- Move destructive `--force` run-directory replacement until after generated
  review context has been captured and the replacement run can start safely, or
  write into a temporary run directory and swap into place.
- Decide whether triage freshness should include review-context artifact hashes
  for review-context runs.
- Add Go unit/integration tests for `research --base --diff` artifact writes,
  forced capture failure preserving an existing run, and rerun replay copying
  review-context artifacts without recapturing git.
- Thread `context.Context` through review-context capture and use
  context-aware git subprocesses.
- Clarify and test code-review auto-triage behavior for single-provider
  successful runs.
- Add parity cases for generated review context and review-context rerun replay
  once the oracle expectations are frozen.

## Follow-Up Queue

- Continue adding dogfood findings here before making broad cleanup changes.
- After cutover, convert this collection into a scoped implementation sequence.
- Revisit whether changes should be Go-only or should first be represented in
  parity fixtures as intentional oracle departures.
