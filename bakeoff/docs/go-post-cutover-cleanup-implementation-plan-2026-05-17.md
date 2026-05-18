# Go Post-Cutover Cleanup Implementation Plan

Date: 2026-05-17
Status: Phase 1 post-cutover hardening implemented; follow-up cleanup queue remains
Scope: Go-only cleanup items discovered while dogfooding the Go CLI; defer
behavior-changing cleanup until follow-up commits unless a finding blocks safe
operation.

## Context

The Go port has moved to the public launcher path, and the legacy Python CLI
has been removed. This file now tracks Go-only cleanup for follow-up commits:
ledger contracts, manifest coverage, JSON summary surfaces, and internal
duplication.

Phase 1 implemented the stable ledger-evidence fingerprints, review-context
replay invariants, scope/status shape hardening, triage safety checks, and
focused regression coverage. The remaining sections preserve the original
dogfood findings as a follow-up queue rather than declaring cleanup complete.

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
- Provider and judge prompt artifacts are also outside the fingerprint set even
  though they define exactly what each provider or judge was asked to do:
  `providers/*/prompt.txt` and `judge/prompt*.txt`.

Risk:
- A run can pass `runs verify` even if important provider or judge evidence was
  changed, removed, or mismatched after the run.
- A run can pass `runs verify` even if the captured prompt was changed after
  execution, weakening the replayability of the ledger.
- This weakens the replay/audit value of the run ledger described in the
  README.

Notes:
- This mirrored the historical Python oracle, so it was not a Go-port parity
  bug.
- Treat this as a post-cutover contract tightening unless later dogfood shows
  it blocks safe operation.
- This is the useful small piece to borrow from heavier orchestration systems:
  trust the structured ledger only after verifying the stable evidence files.
  Do not turn this into event streaming, transcript databases, provenance
  services, or task orchestration state.

Possible implementation direction:
- Define a ledger artifact inventory that distinguishes required core files,
  optional review files, provider artifacts, judge artifacts, triage artifacts,
  and diagnostic/transient artifacts.
- Expand manifest fingerprinting to include stable provider and judge evidence:
  provider `prompt.txt`, `status.json`, successful `final.json`, and
  `last-message.txt` when present or when `final_json_source` says
  `last_message`; judge `prompt*.txt`, `status*.json`, successful
  `result*.json`, and `last-message*.txt` when present or used.
- Decide whether large or noisy outputs such as `stdout.txt`, `stderr.txt`, and
  repair artifacts should be fingerprinted, summarized, or explicitly excluded.
- Prefer conditional requirements derived from recorded status over broad file
  glob requirements; failed providers should not need `final.json`, and older
  ledgers should remain readable with clear legacy warnings.
- Add tests that mutate provider and judge artifacts and assert
  `runs verify` reports the mismatch.
- Add tests that mutate provider and judge prompts and assert `runs verify`
  reports the mismatch.

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
- This also mirrored the historical Python oracle, so it was not a Go-port
  parity bug.
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
  be documented and pinned before cleanup.

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
- Extend parity coverage only after deciding the intended combined
  timeout/output-cap contract.

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
  once the expected behavior is frozen.

### 5. Scope enforcement and provider argv boundaries need hardening

Priority: P2

Source: live Go dogfood run `scope-enforcement-provider-argv-20260516`

Files:
- `internal/scope/scope.go`
- `internal/provider/provider.go`
- `internal/commands/researchcmd/run.go`
- `internal/scope/scope_test.go`
- `internal/provider/provider_test.go`
- `tests/test_scope_enforcement.py`
- `scripts/parity-go.py`

Current behavior:
- The run succeeded through the Go CLI after provider auth/state/network access
  was allowed: both workers and both judge passes completed with `status: ok`,
  the final decision was `pick_winner`, and `runs verify --json` returned
  `status: ok`.
- The same run first failed under the surrounding Codex execution sandbox
  because provider CLIs could not use normal auth/state/network. Treat that as
  a dogfood environment issue, not evidence that the Go CLI failed.
- The required-scope run exercised a Claude codebase worker with
  `claude:disallowedTools=WebFetch,WebSearch` and a Codex web worker with
  `isolated_cwd` plus `codex:sandbox=read-only`; both recorded
  `fallback_reason: null`.
- The Codex web worker's temporary cwd was removed after the run, matching the
  expected cleanup contract.
- `BuildExecution` currently owns scope defaulting, enforcement defaulting,
  frozen-capability-vs-registry resolution, provider-specific scope mechanism
  selection, web temporary cwd creation, scope metadata, and the call into
  `provider.BuildParticipantArgv`.
- `runWorkers` freezes scope capabilities once per backend and passes the
  backend snapshot into each worker's `BuildExecution` call.
- Provider capability probing is help-text based: `internal/provider` builds
  `claude -p --help` or `codex exec --help`, extracts long option tokens, and
  maps those tokens to semantic support keys.
- `ScopeCapabilitiesFromHelp` records Codex `output_last_message` support, but
  `scope.execution` also calls a separate
  `CodexExecSupportsOutputLastMessage` probe when constructing argv.
- Required enforcement fails only when `BuildExecution` accumulates fallback
  reasons. `mixed` scope records `mixed_scope_no_restriction`, reports
  `enforced`, and does not fail under `required`.
- `ScopeErrorResult` reports `policy.Enforcement` directly instead of applying
  the `best_effort` default that `BuildExecution` applies.
- `internal/scope/scope_test.go` currently covers only required Claude
  missing-controls failure and Codex codebase mechanisms. It does not cover web
  scope, mixed scope, caps-vs-registry precedence, `ScopeErrorResult`, or the
  cwd split between runner `cmd.Dir` and Codex `-C`.
- The removed Python suite had some of the missing contract coverage,
  including web temporary cwd behavior, so this is largely Go test-hardening
  work.

Risk:
- Scope policy logic is acceptably cohesive for the current two-backend v1, but
  it is coupled to provider support-key names, provider flag names, provider
  feature names, provider tool names, and temporary-cwd behavior.
- Adding a third backend or a new scope mode will expand the central
  `BuildExecution` switch unless provider-owned scope adapters are introduced.
- Required failure semantics can regress silently because successful required
  enforcement was dogfooded, but required `scope_error` artifact flow was not
  exercised by this live run.
- The `ScopeErrorResult` default-policy mismatch can produce inconsistent
  metadata when a caller passes an empty policy value.
- The duplicated Codex `--output-last-message` help parsing is a small
  maintainability smell and can make future capability cache changes harder to
  reason about.
- Cwd behavior is split across runner `CWD`, Codex `-C`, and Claude relying on
  the subprocess working directory; it worked in this run but should be pinned
  with tests so future argv changes do not break isolation.

Notes:
- Do not treat the provider-adapter refactor as a cutover blocker for the
  current Claude/Codex scope matrix. It is a boundary cleanup to do before
  adding providers or scope modes.
- The tests and the `ScopeErrorResult` metadata default are small enough to fix
  before or immediately after cutover, and they give the most confidence for the
  least churn.
- Codex stderr was truncated in the successful run while stdout/final-json
  remained valid. This is already represented in runner metadata and is not a
  separate scope failure.
- The report's duplicated caps-precedence findings are one item here:
  pre-fetched caps should explicitly win over registry probing, and that should
  be tested.

Possible implementation direction:
- Add Go scope tests for Claude web scope, Codex web scope, mixed scope under
  `required`, missing controls under `required`, and web temporary-cwd cleanup.
- Add a Go test where both `caps` and `registry` are provided to
  `BuildExecution`, asserting the frozen `caps` snapshot wins and the registry
  is not consulted.
- Add `ScopeErrorResult` tests for status shape, stderr/fallback reason,
  enforcement metadata, and defaulting an empty policy to `best_effort`.
- Add a command-level or focused integration test that forces a required
  `scope_error` worker and verifies research summaries, reports, manifest/meta
  data, and `runs verify` handle the synthesized provider result consistently.
- Add tests or assertions for cwd behavior: Claude should rely on `cmd.Dir`,
  Codex should receive both runner `CWD` and `-C`, and web scope should clean up
  its temp cwd after provider completion.
- Collapse Codex final-message support detection to one capability source, or
  document why scope capability reporting and argv support probing intentionally
  remain separate cache entries.
- When extending beyond the current two backends, move provider-specific scope
  mechanism construction behind provider-owned adapters so `internal/scope`
  owns policy orchestration and metadata while `internal/provider` owns flag
  details.

### 6. Triage payload and freshness contracts need typed boundaries

Priority: P2

Source: live Go dogfood run
`triage-source-selection-citation-freshness-live-go`

Files:
- `internal/commands/triagecmd/triage.go`
- `internal/triage/state.go`
- `internal/triage/citation.go`
- `internal/triage/markdown.go`
- `internal/workorder/workorder.go`
- `internal/summary/summary.go`
- `internal/manifest/manifest.go`
- `internal/report/report.go`
- `internal/prompt/fixtures/triage.txt`
- `internal/verify/verify.go`

Current behavior:
- The run succeeded through the Go CLI after provider auth/state/network access
  was allowed: `research --json` completed with `decision_kind: pick_winner`,
  both workers completed, both judge passes completed, forced triage completed
  with `triage.state: yes`, and `runs verify --json` returned `status: ok`
  with no stale triage inputs.
- The same run first failed under the surrounding Codex execution sandbox
  because provider CLIs could not use normal auth/session/network. Treat that
  as a dogfood environment issue, not evidence that the Go CLI failed.
- `triagecmd.Run` builds the triage prompt payload as `map[string]any` and
  passes it to `prompt.BuildTriagePrompt`, so the required payload fields and
  their source types are not compiler-visible.
- Code-review facet runs already get the same generic triage prompt as other
  facet runs. The prompt tells triage to classify selected findings, verify
  citation semantics, and use the facet only as actionability context, but it
  does not explicitly say "judge against the stated acceptance criteria or
  changed-behavior contract" for review-style runs.
- `BuildFindingIndex` returns source findings as `map[string]string` entries
  with `id`, `text`, and optional `section`, while the prompt fixture and
  result schema describe `source_finding_id`. Runtime validation then maps
  result `source_finding_id` values back to selected finding `id` values.
- `SummarizeSourceFindingFilter` returns `map[string]int`; the same summary is
  written to `source_finding_filter.json`, `status.json`, and `final.json`, then
  read back by summary and markdown code as `map[string]any`. `markdown.go`
  carries bridge helpers such as `sourceFilterMap` and `intLike` for this JSON
  round trip.
- `ValidateTriageResult` validates the triage item shape and enum values, while
  the `triageValidator` closure performs source-finding referential integrity
  and mutates the final JSON with `run_id`, `input_hashes`,
  `triage_participant`, and `source_finding_filter`.
- `citation_check_ids` are validated only as strings. They are not checked
  against the generated `C-###` IDs from `citation_checks.json`.
- `citation.CheckCitations` emits map-shaped citation results. In this run,
  the citation artifact contained many successful checks, but also shorthand
  citations that resolved as `missing_file` and one `line_out_of_range` check;
  the triage result still succeeded because the actionable findings had enough
  full-path evidence.
- `triage --force` deletes the existing triage directory before invoking the
  provider. If the provider fails after deletion, the previous successful
  `final.json` and `triage.md` are gone and only failure artifacts remain.
- Triage states are plain strings (`no`, `dry_run`, `yes`, `stale`) flowing
  through `StateDetail`, `show`, `ls`, `summary`, `manifest`, and `verify`.
  `verify` has a `TriageStatus` wrapper, but the state inside it is still raw.
- `StateDetail` hashes `decision.json`, `report.md`, and `work-order.json`;
  it intentionally skips work-order freshness for older triage files that lack
  `work_order_sha256`, but that compatibility path is not directly tested.
- Report rendering and triage indexing both maintain actionable-section and
  skip-bullet constants. Report rendering also assigns `F-###` IDs, while
  triage indexing re-parses those IDs and synthesizes legacy IDs when needed.
- Triage classifications are duplicated between `triage.Classifications` and
  `workorder.triageClasses`; manifests count with one list and result
  validation uses the other.
- Manifest facet extraction falls back from `meta.facet.id` to
  `work-order.facet.id`, while triage source selection reads only
  `work-order.facet.id`; no reproduction currently proves those can diverge.
- Small helpers are duplicated across packages: `readJSON`, `fileExists`, and
  `stringValue` appear in several packages, and `triagecmd.stringsJoin`
  reimplements `strings.Join`.

Risk:
- Forced triage replacement can destroy a previously valid triage report before
  the replacement provider call succeeds.
- Source-finding key drift (`id` versus `source_finding_id`) can make prompt
  examples, runtime payloads, and validator logic harder to reason about.
- A model can reference nonexistent citation check IDs and still pass
  validation, weakening the audit value of `citation_checks.json`.
- Map-shaped payloads and filter summaries make summary, manifest, markdown,
  prompt, and validator schemas easy to change independently.
- Code-review triage can blur contract violations, evidence gaps, warnings,
  and style preferences unless the prompt makes the review contract explicit
  while still using the existing triage schema.
- Duplicate classification lists, state strings, section constants, and helper
  functions create small but real drift hazards across triage, report,
  manifest, summary, verify, and work-order validation.
- Stale detection behavior for legacy triage files and possible facet-ID
  divergence are currently policy-shaped but under-tested.

Notes:
- The live run itself succeeded. The Go CLI exercised `research --json`,
  `triage --dry-run --json`, dry-run-only `show --triage` rejection,
  `triage --force --json`, successful `show --triage`, `runs verify --json`,
  and `ls --triage-state yes`.
- The report's duplicate findings should be collapsed when implemented:
  F-014/F-015 fold into shared report-index constants, F-016/F-019 fold into
  source-finding key naming, F-017 folds into citation-check ID validation,
  F-018/F-020 fold into typed triage state, and F-021 folds into safe
  `--force` replacement.
- This is the other small useful borrowing from heavier orchestration systems:
  code-review verification should require concrete evidence against the stated
  work contract. Do not import binary PASS/FAIL gates, multi-reviewer design
  gates, coverage enforcement, per-DoD state machines, or PR shepherding into
  Bakeoff.
- F-013 needs a focused reproduction before changing behavior; it may turn out
  to be only a theoretical divergence between manifest and triage facet lookup.
- F-003 had one out-of-range `show.go` citation in the triage evidence, but the
  broader helper-duplication finding is still valid from the other cited
  packages.

Possible implementation direction:
- Introduce typed contracts for `TriagePayload`, `SourceFinding`,
  `SourceFindingFilter`, `CitationCheck`, `TriageParticipant`, and
  `TriageState`; keep JSON tags explicit so artifact schemas stay stable.
- Make source-finding key naming consistent across runtime payloads, prompt
  fixtures, and result validation. Either emit `source_finding_id` in payload
  entries or update the prompt/schema language to state that payload entries use
  `id` while result entries must echo that value as `source_finding_id`.
- For `facet.id == "code-review"`, add a tiny triage prompt block that says:
  verify each selected finding against the work-order goal/background,
  generated review context, acceptance criteria when present, and changed
  behavior; require file:line evidence for actionable defects; use existing
  `classification`, `severity`, `confidence`, and `recommended_action` fields
  to distinguish real defects from warnings, product decisions, evidence gaps,
  and style-only findings.
- Keep that review-contract language prompt-only and schema-neutral: no new
  verdict enum, no per-DoD checklist artifact, no new mode, and no orchestration
  gate.
- Add prompt fixture/golden tests that prove the code-review-specific triage
  block appears for `code-review` facet payloads and does not appear for generic
  or non-review facets.
- Validate `citation_check_ids` against the generated citation-check ID set,
  or explicitly document why those IDs are advisory-only.
- Split triage validation from enrichment: keep structural result validation,
  referential integrity checks, and final JSON metadata injection as separate,
  testable steps.
- Replace destructive `triage --force` replacement with stage-then-swap or a
  rollback path so a provider failure preserves the previous successful triage.
- Move triage classifications, actions/severities if useful, report actionable
  sections, skip bullets, and finding-ID parsing into shared typed helpers used
  by report rendering, triage selection, manifest summaries, and validation.
- Add tests for the legacy missing-`work_order_sha256` stale path, stale
  detection after each hashed input changes, dry-run-only `show --triage`,
  forced triage provider failure preserving previous results, source filter
  summary JSON surfaces, and citation-check ID referential integrity.
- Add a focused reproduction for manifest-vs-triage facet lookup divergence
  before changing either behavior.
- Consolidate repeated `readJSON`, `fileExists`, and `stringValue` helpers, and
  replace `triagecmd.stringsJoin` with `strings.Join`.

## Follow-Up Queue

- Continue adding dogfood findings here before making broad cleanup changes.
- After cutover, convert this collection into a scoped implementation sequence.
- Revisit whether behavior changes should first be represented in parity
  fixtures as intentional contract changes.
