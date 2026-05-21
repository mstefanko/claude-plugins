# Failure Classification, Prompt Preflight, and REVIEW.md Guidance - Implementation Plan

Date: 2026-05-21
Status: proposed
Scope: provider failure diagnostics, prompt-size preflight diagnostics, and
explicit repo-local review guidance for research review runs

## Decision

Add the three low-bloat improvements in this order:

1. Expand failure classification for all provider-like calls.
2. Add prompt-size preflight diagnostics before expensive provider launches.
3. Add explicit `REVIEW.md` guidance capture for review-context runs.

These features should improve operator feedback and review consistency without
changing Bakeoff's core topology. A run remains one work order, two providers,
an optional judge phase, artifacts, report, and optional triage. The new behavior
is diagnostic and context-capture only. It must not dynamically choose provider
fleets, summarize or truncate tasks, skip files mechanically, or hide prompt
inputs from artifacts.

## Recommendation Rationale

The highest-value import from the overlapping plugin is stronger error
classification. Bakeoff already preserves raw stdout/stderr and compact status
artifacts, but a failed run often still asks users to infer whether the fix is
login, billing, prompt size, provider availability, or a malformed final JSON.
Adding stable `failure_kind` values makes retry and troubleshooting much faster.

Prompt-size preflight is second because it catches one of the most expensive
classes of preventable failure: large generated contexts or worker/judge prompts
that are clearly too big before any provider is launched. The implementation
must stay conservative. Bakeoff should warn and record diagnostics, and only
hard-fail for clear local/pathological limits. It should never auto-summarize or
truncate, because both providers must see the same task.

`REVIEW.md` guidance is third because it can improve review quality, but only if
it is explicit, bounded, and artifacted. Treat it as captured repo context, not a
configuration file. It may guide provider attention; it must not alter hidden
execution behavior.

## Current Code Research

### Failure Classification

- Current classifier is judge-only and narrow:
  `internal/runner/classify.go` exposes `ClassifyJudgeError(status, exitCode,
  stdout, stderr)` with kinds `api_transient`, `prompt_too_large`, `timeout`,
  `output_cap`, `schema_error`, `nonzero_exit`, `parse_error`, and `unknown`.
- Judge classification is attached only in research judge calls:
  `internal/commands/researchcmd/run.go` sets `judge_error_kind` after
  `runSingleJudge()` receives a failed result.
- `artifact.ResultMap()` already centralizes conversion from `runner.Result` to
  map artifacts and adds `stderr_kind`. This is the right place to add a generic
  `failure_kind`, because all provider, judge, doctor, and triage call sites
  pass through it.
- `artifact.StatusWithoutPayload()` already controls compact status artifacts.
  Adding `failure_kind` there lets `providers/<id>/status.json`,
  `judge/status*.json`, `triage/status.json`, `decision.provider_statuses`, and
  reports inherit the value with minimal call-site changes.
- `decision.Base()` and build decision helpers derive provider status maps from
  `StatusWithoutPayload()`, so most decision/report surfaces will pick up
  provider failure kinds automatically.
- `manifest.providerSummaries()` currently copies a fixed subset of provider
  status fields. It should be updated to include `failure_kind` so `ls --json`
  and manifest consumers can diagnose failures without opening provider
  directories.
- Build judge failures currently record `_failure` statuses but do not classify
  them with `judge_error_kind`. Generic `failure_kind` should be enough in the
  status artifacts; build report can surface it from status if needed.

### Prompt Size

- Worker prompts are generated in `prompt.BuildWorkerPromptWithRepoLayout()` and
  written to `providers/<id>/prompt.txt` immediately before launch in research
  and build provider paths.
- Judge prompts are generated in `prompt.BuildJudgePrompt()` /
  `prompt.BuildJudgePromptWithEvidence()` and written to `judge/prompt*.txt`
  immediately before launch.
- Triage prompts are generated in `prompt.BuildTriagePrompt()` and written to
  `triage/prompt.txt` before the triage provider call.
- Build runs already collect prompt sizes after the run in
  `internal/commands/buildcmd/diagnostics.go` (`collectPromptSizes`). This is a
  useful existing artifact shape, but it arrives too late to prevent avoidable
  prompt-size failures.
- Review context capture already hard-fails oversized git sections before
  provider execution: diffstat and changed files are capped at 40 KB, patch at
  120 KB. Prompt preflight should reuse that philosophy: deterministic limits,
  clear diagnostics, no silent truncation.

### Review Context and Guidance

- Review context is already explicit. `reviewcontext.Build()` gathers git
  metadata and optional patch text. `reviewcontext.Apply()` appends a rendered
  block to the effective work order background. The original work order is
  preserved as `source-work-order.json`, and generated context is written as
  `review-context.md` and `review-context.json`.
- `review-context.md` already wraps diff content as evidence, not instructions,
  and escapes prompt sentinels such as `<final_json>` and
  `<generated_review_context>`.
- Manifest and triage freshness already treat review context artifacts as
  all-or-none. Adding guidance inside `review-context.md/json` keeps the
  artifact model simple and avoids a new optional artifact set.
- Current CLI flags are `--base`, `--diff`, and `--changed-files`; any one
  enables review-context capture. Guidance should only be available on this
  explicit review-context path.

## Non-Goals

- No automatic provider retry policy.
- No hidden provider fleet changes based on failure kind.
- No prompt summarization, truncation, compression, or provider-specific prompt
  rewriting.
- No exact model context-window registry that must be kept current with vendor
  releases.
- No use of `REVIEW.md` to enforce path filters, skip files, change scope
  policy, alter budgets, or suppress artifacts.
- No external PR state, review-delta tracking, or line-key matching in this
  pass.
- No redacted artifact export in this plan. Display-time redaction can be a
  separate safety pass.

## Workstream 1: Stronger Failure Classification

### User Value

- Users can distinguish "log in again" from "wait and retry", "prompt too
  large", "provider returned stderr only", "missing CLI", and "schema parse
  failed" without spelunking raw stderr.
- Reports and manifests become better handoff artifacts for long dogfood runs.
- Doctor/auth probes can give clearer readiness warnings.

### Data Contract

Add a generic status field:

```json
{
  "status": "exit_error",
  "failure_kind": "rate_limited"
}
```

Keep `judge_error_kind` for compatibility where it already exists, but derive it
from the same classifier for failed judge calls. Do not set `failure_kind` on
successful results.

Initial stable kinds:

| Kind | Meaning |
| --- | --- |
| `missing_provider` | Provider executable or argv is missing. |
| `cancelled` | Harness context was cancelled. |
| `timeout` | Wall-clock timeout or timeout wording in output. |
| `output_cap` | Harness output cap stopped or invalidated the run. |
| `schema_error` | Final JSON existed but failed schema validation. |
| `parse_error` | Final JSON block was missing or invalid after an otherwise successful exit. |
| `prompt_too_large` | Provider or harness indicates context/input size exceeded. |
| `auth_required` | Authentication missing, expired, invalid, or unauthorized. |
| `rate_limited` | 429, rate limit, quota, billing, or capacity quota failure. |
| `api_transient` | 5xx, gateway, connection reset, DNS/connectivity, overloaded service. |
| `model_unavailable` | Model not found, unsupported, unavailable, or denied for account. |
| `provider_rejection` | Provider refuses due to policy/safety/request rejection. |
| `empty_output` | Provider produced no stdout/stderr/final message. |
| `stderr_only` | Provider returned only stderr and no final JSON. |
| `stdin_closed` | Provider closed stdin before reading the prompt. |
| `nonzero_exit` | Nonzero exit with no more specific classification. |
| `unknown` | Failure did not match known patterns. |

Use conservative matching. Prefer a broader but accurate bucket, such as
`nonzero_exit`, over overclaiming `auth_required` from ambiguous text.

### Implementation Details

1. Replace `ClassifyJudgeError` internals with a generic classifier:

   ```go
   func ClassifyFailure(status string, exitCode *int, stdout string, stderr string) string
   func ClassifyJudgeError(status string, exitCode *int, stdout string, stderr string) string {
       return ClassifyFailure(status, exitCode, stdout, stderr)
   }
   ```

   Keep the wrapper to avoid churn at existing call sites while tests migrate.

2. Normalize matching input once:

   - Lowercase combined stdout/stderr.
   - Also classify from structural status first for `missing_provider`,
     `cancelled`, `timeout`, `output_cap`, and `schema_error`.
   - Use `stdout`/`stderr` emptiness to detect `empty_output` and
     `stderr_only` only after higher-priority structural kinds.

3. Add pattern groups in priority order:

   - Status-derived harness kinds.
   - Prompt/context-size errors.
   - Auth errors.
   - Rate/quota/billing errors.
   - Transient API/network errors.
   - Model unavailable errors.
   - Provider rejection errors.
   - Format/parse errors.
   - Empty/stderr-only/nonzero fallback.

4. In `artifact.ResultMap()`, if `!ProviderSucceeded(out)`, set:

   ```go
   out["failure_kind"] = runner.ClassifyFailure(...)
   ```

   Then keep `stderr_kind` unchanged.

5. In `artifact.StatusWithoutPayload()`, add `failure_kind` to the copied
   scalar keys.

6. In research judge paths, continue writing `judge_error_kind`, but set it
   from `failure_kind` when available:

   ```go
   if kind := jsonutil.StringValue(result["failure_kind"]); kind != "" {
       result["judge_error_kind"] = kind
   }
   ```

7. In `manifest.providerSummaries()`, pass through `failure_kind` along with the
   other status fields.

8. Update report rendering:

   - Provider Status Notes should show `failure kind: <kind>` when present.
   - Judge failure status already shows `Judge error kind`; it should continue
     doing so.

9. Update doctor auth-probe warnings to prefer `failure_kind` over a raw generic
   reason when present.

### Tests

- Expand `internal/runner/classify_test.go` with table cases for every new
  kind, including representative Claude/Codex/OpenAI/Anthropic-style wording
  without depending on exact vendor strings.
- Add `artifact.ResultMap` / `StatusWithoutPayload` coverage proving failed
  results get `failure_kind` and successful results do not.
- Add one research-command fake-provider test proving `decision.json`,
  provider `status.json`, `manifest.json`, and report notes expose
  `failure_kind`.
- Add a judge failure test proving `judge_error_kind` remains present and equals
  the generic `failure_kind`.
- Add a doctor auth-probe unit or integration test for clearer warning text.

## Workstream 2: Prompt-Size Preflight Diagnostics

### User Value

- Users get a fast, local explanation when generated prompts are suspiciously
  large.
- Oversized review contexts fail before spending provider time.
- Prompt sizes become visible for research and triage, not just build
  diagnostics.

### Data Contract

Add prompt diagnostic records with a shared shape:

```json
{
  "schema_version": 1,
  "prompts": [
    {
      "path": "providers/claude/prompt.txt",
      "kind": "worker",
      "provider_id": "claude",
      "backend": "claude",
      "model": "claude-sonnet-4-5-20250929",
      "bytes": 84231,
      "estimated_tokens": 21058,
      "severity": "ok"
    }
  ]
}
```

Severity values:

- `ok`
- `warn`
- `fail`

Recommended artifact paths:

- Research: `prompt-diagnostics.json`
- Build: add the same records to existing `diagnostics.json.prompt_sizes`, or
  add `diagnostics.prompt_preflight` while keeping `prompt_sizes` for
  compatibility.
- Triage: `triage/prompt-diagnostics.json` or include diagnostics in
  `triage/status.json` for dry-run and live runs.

Prefer a shared diagnostic structure even if build stores it inside
`diagnostics.json`.

### Preflight Policy

Do not maintain exact model context-window tables in v1. They are unstable and
would make Bakeoff look more authoritative than it can be from local CLI code.

Use deterministic local thresholds:

- Estimate tokens as `ceil(bytes / 4)`. Name it `estimated_tokens`, not
  `tokens`.
- Warn above a conservative threshold, for example 120 KB or about 30k estimated
  tokens.
- Hard-fail above a pathological threshold, for example 1 MB or about 250k
  estimated tokens.
- Record the thresholds used in the diagnostic artifact.

The exact constants should live in one package and have tests. If dogfood proves
the defaults too strict or too loose, adjust the constants in one place.

Hard-fail behavior should be validation-like for pre-provider research runs:

```text
prompt preflight failed: providers/claude/prompt.txt is 1.3MB
(estimated 340k tokens), above the hard cap 1.0MB; narrow the work order,
remove --diff, or split the task
```

For judge and triage prompts created after providers complete, write the prompt
and status artifact, then return a classified failure result with
`failure_kind: "prompt_too_large"` so the run remains inspectable.

### Implementation Details

1. Add a small package, for example `internal/promptdiag`:

   ```go
   type Role string // worker, judge, triage
   type Severity string // ok, warn, fail
   type Diagnostic struct { ... }

   func Analyze(path string, role Role, participant workorder.Participant, text string, limits Limits) Diagnostic
   func AnalyzeTextBytes(byteCount int, limits Limits) (severity Severity, estimatedTokens int)
   func ErrorFor(diags []Diagnostic) error
   ```

2. Keep thresholds and wording in the package:

   ```go
   const DefaultWarnBytes = 120000
   const DefaultFailBytes = 1000000
   ```

   Do not add work-order schema knobs in this pass.

3. Research worker integration:

   - Refactor worker setup so prompts for both providers are generated and
     written before provider goroutines launch.
   - Run preflight across both worker prompts.
   - If any severity is `fail`, write `prompt-diagnostics.json` and return a
     validation error before launching either provider.
   - If severity is `warn`, write diagnostics and print a concise warning, then
     launch normally.

4. Research judge integration:

   - After writing `judge/prompt*.txt`, analyze it.
   - If it fails, write a judge `status*.json` result with
     `status: "schema_error"` or a new local result status only if the existing
     status enum can absorb it cleanly. Prefer reusing `schema_error` plus
     `failure_kind: "prompt_too_large"` over adding a runner status.
   - Let existing decision logic produce `judge_failed`.

5. Triage integration:

   - `triage --dry-run` should always write prompt diagnostics.
   - Live triage should fail before provider launch when the triage prompt is
     over hard cap, preserving any previous triage when `--force` staged a new
     triage directory.

6. Build integration:

   - Reuse the same analyzer for worker and judge prompts.
   - Preserve existing `diagnostics.prompt_sizes` consumers by either enriching
     those records or adding a parallel `prompt_preflight` list.
   - If a build worker prompt fails preflight, mark that provider ineligible
     with `failure_kind: "prompt_too_large"` rather than launching it.
   - If a build judge prompt fails preflight, record judge failure and let
     verifier evidence decide as much as possible.

7. Manifest and summary:

   - Include prompt diagnostic artifacts in `manifest.artifacts` when present.
   - Fingerprint prompt diagnostic artifacts so run verification catches
     accidental edits.

8. CLI output:

   - Human output should show one line only when there is a warning or failure.
   - JSON output should include the diagnostics path, not dump the full prompt
     diagnostics payload inline unless summary code already has a natural
     location.

### Tests

- Pure tests for byte-to-estimated-token calculation, warn/fail thresholds, and
  message wording.
- Research test proving both worker prompts are preflighted before either fake
  provider is invoked.
- Research test proving a warning writes `prompt-diagnostics.json` but still
  launches providers.
- Research judge test proving an oversized judge prompt becomes
  `judge_failed` with `failure_kind: "prompt_too_large"`.
- Triage dry-run test proving prompt diagnostics are written.
- Build diagnostics test proving the existing prompt-size diagnostics remain
  present and compatible.
- Manifest verification test proving prompt diagnostics are fingerprinted.

## Workstream 3: Explicit REVIEW.md Guidance

### User Value

- Teams can encode lightweight review expectations once, then reuse them across
  Bakeoff review runs.
- Providers and judge see the same guidance, and users can inspect exactly what
  was captured.
- Guidance reduces repeated background text without creating hidden behavior.

### User Surface

Add explicit research flags:

```text
bakeoff research review.work-order.json --base main --diff --review-guidance
bakeoff research review.work-order.json --base main --review-guidance-path docs/REVIEW.md
```

Semantics:

- `--review-guidance` reads `REVIEW.md` from the git root discovered by review
  context capture.
- `--review-guidance-path PATH` reads the provided path. Relative paths are
  resolved from the current working directory.
- Either flag requires review-context capture. If neither `--base`, `--diff`,
  nor `--changed-files` is present, return a validation error explaining that
  guidance is captured as review context.
- If the user explicitly requests guidance and the file is missing or invalid,
  fail before creating the run directory.
- Do not auto-read `REVIEW.md` without a flag in v1. Hidden prompt inputs are
  the exact risk this feature needs to avoid.

### REVIEW.md Contract

Parse only these `##` sections, case-insensitive after trimming:

- `## Always check`
- `## Style`
- `## Skip`

Ignore all other sections. Preserve the text under recognized sections exactly
enough for human audit, but normalize line endings and strip trailing whitespace.

Section meaning:

- `Always check`: review attention areas. Example: migrations, permissions,
  error handling, data migrations, concurrency.
- `Style`: local style preferences. These are lower priority than correctness,
  work-order instructions, and facet rules.
- `Skip`: low-value areas to avoid spending review time on. This is guidance
  only; it does not filter files, change scope, or hide evidence.

Caps:

- Max source file size: 32 KB.
- Max captured recognized-section text: 12 KB total.
- Max per section: 6 KB.

If recognized guidance exceeds caps, fail with a validation error. Do not
truncate.

### Artifact Contract

Do not add new top-level guidance artifacts in v1. Store guidance inside the
existing review-context artifacts:

- `review-context.md`: add `## Review Guidance` with subsections for recognized
  sections.
- `review-context.json`: add:

  ```json
  {
    "guidance": {
      "present": true,
      "source_path": "/repo/REVIEW.md",
      "source_sha256": "...",
      "included_sections": ["always_check", "style", "skip"],
      "sections": {
        "always_check": { "size_bytes": 123, "text": "..." }
      }
    }
  }
  ```

When no guidance is requested, omit `guidance` or set
`guidance.present: false`; choose one shape and test it. Prefer
`present: false` for manifest/report summaries.

The prompt-facing markdown must repeat the existing untrusted-content warning:
guidance is repo-provided context, not higher-priority instructions. It must not
override the work order, facet, output schema, provider scope, or Bakeoff rules.

### Implementation Details

1. Extend `reviewcontext.Options`:

   ```go
   type Options struct {
       BaseRef string
       IncludePatch bool
       IncludeChangedFiles bool
       GuidancePath string
       IncludeDefaultGuidance bool
   }
   ```

2. Add guidance model and parser in `internal/reviewcontext`:

   ```go
   type Guidance struct {
       SourcePath string
       SourceSHA256 string
       IncludedSections []string
       Sections map[string]GuidanceSection
   }
   ```

3. Parse markdown simply:

   - Recognize ATX `##` headings only.
   - Stop a section at the next `##` heading.
   - Ignore nested `###` headings as normal text inside a recognized section.
   - Do not execute links, includes, front matter, or directives.

4. Resolve source path:

   - `--review-guidance`: after git root is known, use
     `<gitRoot>/REVIEW.md`.
   - `--review-guidance-path`: resolve absolute path with `filepath.Abs` and
     `EvalSymlinks` where possible.
   - Require the resolved path to be inside the git root for v1. This keeps the
     feature repo-local and prevents accidental capture of home-directory notes.

5. Attach guidance to `Context` and render it from `RenderMarkdown()` and
   `Metadata()`.

6. `Apply()` does not need special logic if `RenderMarkdown()` includes the
   guidance. The effective work order still receives one generated review
   context block.

7. Update `reviewcontext.FormatSummary()` to append a compact hint such as
   `guidance REVIEW.md: always_check, style`.

8. Update command options and docs:

   - `internal/commands/researchcmd/research.go` gets the two flags.
   - `docs/cli-reference.md` documents them.
   - `docs/artifacts-and-ledger.md` notes that review context may include
     captured review guidance.
   - README review examples can mention the explicit flag once, not as a new
     default.

### Tests

- Parser test for all three recognized sections.
- Parser test proving unrelated sections are ignored.
- Parser test for caps and validation errors.
- Test proving guidance requires review-context capture.
- Test proving missing explicit `REVIEW.md` fails before run creation.
- Test proving prompt sentinels in guidance are escaped in markdown/prompt
  rendering.
- End-to-end review context test proving `review-context.md`,
  `review-context.json`, effective `work-order.json`, and manifest
  fingerprints change when guidance is captured.

## Implementation Order

1. **Generic failure classification.** Lowest blast radius and immediate user
   value. Add classifier, status field propagation, report/manifest pass-through,
   docs, and focused tests.
2. **Prompt preflight package and research integration.** Start with research
   workers and judges because those are the highest-volume dogfood path. Add
   diagnostics artifact and manifest fingerprinting.
3. **Prompt preflight triage/build integration.** Reuse the same package across
   triage and build once the research contract is stable.
4. **REVIEW.md guidance parser and CLI flags.** Build on existing review context
   and keep all captured guidance in `review-context.md/json`.
5. **Docs and final audit.** Update CLI reference, artifacts docs, README review
   notes, and tests/parity fixtures if command output changes.

## Compatibility and Migration

- `failure_kind` is additive. Existing consumers that ignore unknown JSON keys
  keep working.
- `judge_error_kind` remains for existing report and decision consumers.
- Prompt diagnostics are additive artifacts. Existing runs without the artifact
  remain valid.
- Review guidance is opt-in. Existing review-context runs do not change unless
  the new flag is used.
- No work-order schema migration is required.

## Risks and Mitigations

- **Classifier false positives.** Mitigate with conservative pattern priority
  and tests. Unknown is acceptable when evidence is ambiguous.
- **Prompt preflight blocks valid large-context models.** Mitigate by making
  normal thresholds warnings and reserving hard-fail for clearly pathological
  prompts. Keep constants centralized.
- **Prompt diagnostics become another drift surface.** Mitigate by deriving all
  fields from prompt text and participant metadata at write time, then
  fingerprinting the artifact.
- **REVIEW.md becomes hidden behavior.** Mitigate with explicit flags, visible
  summary output, and artifacted captured sections.
- **`Skip` guidance is mistaken for enforcement.** Mitigate with wording in the
  prompt block and docs: it guides attention only.
- **Guidance injection.** Mitigate by reusing review-context sentinel escaping
  and untrusted-content wrapping.

## Acceptance Criteria

- Failed provider, judge, triage, and doctor probe statuses include a useful
  `failure_kind` when the failure matches known categories.
- Judge failures still include `judge_error_kind`.
- Reports and manifests surface provider failure kinds without requiring users
  to open raw stderr.
- Research worker prompts are analyzed before any provider process launches.
- Oversized prompts produce clear diagnostics naming prompt path, bytes,
  estimated tokens, threshold, and suggested remediation.
- Prompt diagnostics are written and fingerprinted.
- `--review-guidance` and `--review-guidance-path` capture only recognized
  sections, add them to review context artifacts, and inject them visibly into
  the effective work order.
- `REVIEW.md` guidance never changes providers, scopes, budgets, pathspecs, or
  hidden execution behavior.

## Validation Commands

Run focused tests as each workstream lands:

```text
go test ./internal/runner ./internal/artifact ./internal/report ./internal/manifest
go test ./internal/commands/researchcmd ./internal/commands/triagecmd
go test ./internal/commands/buildcmd ./internal/reviewcontext
go test ./...
```

After the three workstreams land, dogfood with:

```text
bakeoff research examples/review.work-order.json --base HEAD --changed-files --review-guidance --no-triage
```

Use a deliberately oversized generated context in a temporary work order to
verify the prompt preflight failure path before running live providers.
