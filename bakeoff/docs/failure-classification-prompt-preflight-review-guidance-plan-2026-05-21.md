# Failure Classification and Prompt Preflight - Trimmed Implementation Plan

Date: 2026-05-21
Status: revised after review
Scope: high-confidence provider failure diagnostics and a minimal prompt-size
preflight guard

## Decision

Split the original plan and ship only the small, high-confidence pieces:

1. Add optional `failure_kind` propagation for failed provider-like calls.
2. Add a pre-launch prompt byte guard in the existing runner path.
3. Defer `REVIEW.md` guidance entirely.

The goal is better operator feedback with minimal new surface area. This plan
does not add new artifact classes, prompt diagnostics schemas, provider
execution refactors, or repo-local guidance injection.

## Why This Shape

The review feedback is right: the original plan was about three times larger
than the evidence justified. Bakeoff already records raw stdout, stderr,
prompts, statuses, and reports. The highest value is turning common generic
failures into a small number of actionable labels. The second useful piece is
catching obviously oversized prompts before spending provider time.

Everything else was speculative or schema-heavy. `REVIEW.md` guidance may be
useful later, but users can paste guidance into `background` today, and the
feature brings real risks: hidden prompt behavior, `Skip` being mistaken for
enforcement, additional untrusted content, and scope creep.

## Current Code Research

### Failure Classification

- `internal/runner/classify.go` currently exposes `ClassifyJudgeError()`. It
  is judge-specific by name but already classifies generic subprocess output.
- `internal/commands/researchcmd/run.go` attaches `judge_error_kind` only for
  failed research judge calls.
- `internal/artifact/artifact.go` centralizes runner result conversion through
  `ResultMap()` and compact status projection through `StatusWithoutPayload()`.
  This is the smallest place to add generic failure metadata.
- `decision.Base()` and build decision helpers derive provider status maps from
  `StatusWithoutPayload()`, so provider status projections can inherit
  `failure_kind` without broad call-site changes.
- `internal/manifest/manifest.go` copies a fixed subset of provider status
  fields into `manifest.providers.<id>`. It needs one additive passthrough for
  `failure_kind`.
- `internal/report/report.go` already renders provider status notes and judge
  failure status. It can surface `failure_kind` without changing report shape.

### Prompt Preflight

- Every provider-like call passes through `runner.RunProvider()` or
  `runner.RunProviderWithFormatRetry()`, which call the shared `runProcess()`
  implementation in `internal/runner/runner.go`.
- Call sites already write `prompt.txt` before calling the runner:
  research providers, research judges, build providers, build judges, and
  triage all persist the prompt first.
- Putting the prompt byte guard in `runner.runProcess()` catches every
  provider-like invocation before `cmd.Start()` and avoids reordering the
  research worker goroutine setup.
- Existing `prompt.txt` plus failed `status.json`/`stderr.txt` is enough
  evidence. No `prompt-diagnostics.json`, manifest fingerprinting, or dry-run
  prompt diagnostic artifact is needed.

### REVIEW.md Guidance

- Review context capture is already explicit through `--base`, `--diff`, and
  `--changed-files`; it writes `source-work-order.json`,
  `review-context.md`, and `review-context.json`.
- Repo-wide guidance can already be pasted into the work-order `background`.
- No dogfood run or operator complaint cited `REVIEW.md` as an observed gap.
  Defer until there is evidence that repeated manual guidance is a real
  problem.

## Non-Goals

- No 17-kind classifier taxonomy.
- No classifier guesses for ambiguous stderr.
- No doctor auth-probe wording changes in this pass.
- No prompt diagnostics package.
- No `prompt-diagnostics.json` artifact.
- No manifest changes for prompt diagnostics.
- No prompt warning threshold in v1.
- No worker prompt generation reordering.
- No `REVIEW.md` parsing, flags, artifacts, or prompt injection.
- No automatic prompt summarization, truncation, compression, or retry.

## Workstream 1: Optional Failure Classification

### User Value

Users get a small number of actionable failure labels in existing status,
decision, manifest, and report surfaces:

- "try logging in again"
- "wait or retry later"
- "the prompt was too large"
- "the provider output did not satisfy the required final JSON contract"
- "the provider CLI is missing"

When the classifier is not confident, it should say nothing. No label is better
than a wrong label that sends the user down the wrong remediation path.

### Data Contract

Add an optional field to failed result maps and compact statuses:

```json
{
  "status": "exit_error",
  "failure_kind": "rate_limited"
}
```

Do not set `failure_kind` on successful results. Do not set
`failure_kind: "unknown"`. Absence means no high-confidence classification.

Keep `judge_error_kind` for compatibility, but derive it from `failure_kind`
when present.

### Trimmed Kind Set

Use this initial high-signal set:

| Kind | Source | Meaning |
| --- | --- | --- |
| `missing_provider` | structural status | Provider executable or argv is missing. |
| `timeout` | structural status or clear timeout text | Harness or provider timed out. |
| `output_cap` | structural status | Harness output cap stopped or invalidated the run. |
| `prompt_too_large` | clear context/input-size text or runner prompt guard | Prompt/context/input exceeded a size limit. |
| `auth_required` | strict auth/permission text | Login, credentials, unauthorized, forbidden, or expired auth. |
| `rate_limited` | strict 429/quota/billing text | Rate limit, quota, credits, billing, or spend limit. |
| `api_transient` | clear network/5xx text | Provider/network transient failure. |
| `invalid_output` | structural schema error or clear final JSON parse text | Provider output did not satisfy the final JSON contract. |

Do not include in v1:

- `model_unavailable`
- `provider_rejection`
- `empty_output`
- `stderr_only`
- `stdin_closed`
- `nonzero_exit`
- `unknown`

Those can be added later if dogfood shows repeat failures with clear patterns.

### Matching Rules

Classify in this priority order:

1. Structural statuses: `missing_provider`, `timeout`, `output_cap`,
   `invalid_output`.
2. `prompt_too_large` text, including `context_length`, `maximum context`,
   `prompt is too long`, `input too large`, and the runner guard diagnostic.
3. Strict auth text, such as `unauthorized`, `forbidden`, `not authenticated`,
   `authentication expired`, `invalid api key`, or `login required`.
4. Strict rate/quota/billing text, such as `rate limit`, `429`, `quota`,
   `insufficient credits`, `billing`, or `spend limit`.
5. Clear transient text, such as `http 500`, `http 502`, `http 503`,
   `http 504`, `internal server error`, `bad gateway`, `service unavailable`,
   `gateway timeout`, `connection reset`, or `socket connection was closed`.
6. Clear final JSON parse text when structural status did not already classify.

If none match, return the empty string.

### Implementation Details

1. Replace the judge-specific classifier internals with a generic function:

   ```go
   func ClassifyFailure(status string, exitCode *int, stdout string, stderr string) string

   func ClassifyJudgeError(status string, exitCode *int, stdout string, stderr string) string {
       return ClassifyFailure(status, exitCode, stdout, stderr)
   }
   ```

   Keep `ClassifyJudgeError()` as a compatibility wrapper.

2. Make `ClassifyFailure()` return `""` when it lacks a high-confidence match.

3. In `artifact.ResultMap()`, add:

   ```go
   if !ProviderSucceeded(out) {
       if kind := runner.ClassifyFailure(...); kind != "" {
           out["failure_kind"] = kind
       }
   }
   ```

4. In `artifact.StatusWithoutPayload()`, copy `failure_kind`.

5. In research judge code, keep `judge_error_kind`, but set it from
   `failure_kind` if present. If no generic kind exists, leave
   `judge_error_kind` absent.

6. In `manifest.providerSummaries()`, pass through `failure_kind`.

7. In `report.renderProviderStatusTable()`, add `failure kind: <kind>` to
   provider notes when present. Keep existing judge failure rendering.

8. Leave doctor auth-probe wording alone. It will inherit `failure_kind` in raw
   status maps where those maps already flow through `artifact.ResultMap()`.
   Better human wording can be a later, separate UX pass.

### Tests

- Table-test `ClassifyFailure()` for the eight kinds and for ambiguous text that
  must return `""`.
- Keep or update `ClassifyJudgeError()` tests to prove the wrapper delegates.
- Test `artifact.ResultMap()` sets `failure_kind` only on failed results with a
  confident classification.
- Test `StatusWithoutPayload()` preserves `failure_kind`.
- Add a focused fake-provider research test proving:
  - provider `status.json` includes `failure_kind`;
  - `decision.json.provider_statuses` includes `failure_kind`;
  - `manifest.json.providers.<id>` includes `failure_kind`;
  - `report.md` mentions the failure kind.
- Add a judge-failure test proving `judge_error_kind` still appears when the
  failure is classified.

## Workstream 2: Minimal Prompt-Size Preflight

### User Value

Catch obviously oversized prompts before launching an expensive provider
process. The failure should point users at the existing `prompt.txt` artifact
and explain the byte size.

This gets most of the value without introducing a prompt diagnostics subsystem.

### Data Contract

No new artifact and no new status enum.

When the runner refuses to launch a provider because the prompt is too large,
return an existing failed runner result:

```json
{
  "status": "exit_error",
  "failure_kind": "prompt_too_large",
  "stderr": "prompt too large: 1049000 bytes exceeds 1000000 byte limit"
}
```

The already-written `prompt.txt` remains the source artifact for exact prompt
content and byte inspection.

### Policy

- Add one hard cap only.
- No warning threshold in v1.
- No model-specific context table.
- No estimated token field.
- No automatic prompt mutation.

Suggested initial cap:

```go
const MaxPromptBytes = 1000000
```

The cap is intentionally high. It should catch pathological prompts and obvious
context explosions, not second-guess normal large-model usage.

### Implementation Details

1. Add a small helper in `internal/runner`, not a new package:

   ```go
   const MaxPromptBytes = 1000000

   func promptSizeError(prompt string) string {
       if len([]byte(prompt)) <= MaxPromptBytes {
           return ""
       }
       return fmt.Sprintf("prompt too large: %d bytes exceeds %d byte limit", len([]byte(prompt)), MaxPromptBytes)
   }
   ```

2. In `runner.runProcess()`, after budgets/state setup and before any
   `exec.CommandContext()` / `cmd.Start()` path, return a failed result when the
   helper reports an error:

   ```go
   if message := promptSizeError(opts.Prompt); message != "" {
       return state.status(StatusExitError, nil, "", message, nil, "")
   }
   ```

   `artifact.ResultMap()` will classify the stderr text as
   `failure_kind: "prompt_too_large"`.

3. Do not change `runWorkers()` to pre-generate both prompts. Each provider
   goroutine will still build and write its own prompt before the runner guard
   refuses launch. This avoids touching the research execution hot path.

4. Do not change build diagnostics. Build will still collect prompt sizes after
   the run through the existing `diagnostics.json.prompt_sizes` path.

5. Do not add prompt-size manifest entries. Existing prompt artifacts are
   already fingerprinted as provider and judge evidence where applicable.

6. Human-facing behavior:

   - Existing status/report/manifest surfaces should show
     `failure_kind: prompt_too_large` through Workstream 1.
   - Raw stderr contains the exact byte failure.
   - No extra console warning is needed.

### Tests

- Unit-test the runner prompt guard below, at, and above the cap.
- Test an oversized prompt does not execute the provider binary. Use a fake
  provider that writes a sentinel if invoked; the sentinel must not appear.
- Test the resulting `artifact.ResultMap()` classifies the guard as
  `prompt_too_large`.
- Add one research fake-provider test with oversized background proving the run
  records provider failure without launching that provider.

## Deferred: REVIEW.md Guidance

Do not implement `REVIEW.md` guidance in this pass.

Reasons:

- No observed dogfood failure or operator complaint requires it.
- Users can paste repo guidance into `background` today.
- It creates a new untrusted prompt-content surface.
- It risks hidden behavior unless every byte is explicitly surfaced.
- `Skip` guidance is easy to misread as enforcement.
- It invites follow-on scope creep around file filtering, policy, and review
  state.

Future reconsideration should require evidence, such as repeated review runs
where operators paste the same repo guidance and complain about the friction.
If revived later, it should be a separate plan with explicit flags and artifact
capture. It should not be bundled with failure diagnostics.

## Rejected From Original Plan

Rejected now:

- 17-kind classifier taxonomy.
- `internal/promptdiag` package.
- `prompt-diagnostics.json`.
- Prompt diagnostic manifest fingerprinting.
- Triage dry-run always writing prompt diagnostics.
- Generating both research worker prompts before launching either provider.
- Doctor auth-probe wording changes.
- `REVIEW.md` parser, CLI flags, and prompt injection.

These may be reconsidered one at a time if dogfood evidence appears.

## Implementation Order

1. Add `ClassifyFailure()` with the trimmed kind set and tests.
2. Wire `failure_kind` through `artifact.ResultMap()` and
   `StatusWithoutPayload()`.
3. Pass `failure_kind` through manifest provider summaries and report provider
   notes.
4. Preserve `judge_error_kind` by copying classified judge `failure_kind`.
5. Add the runner prompt byte guard and tests.
6. Run focused tests and one fake-provider smoke test.

## Compatibility

- `failure_kind` is additive and optional.
- Existing consumers that ignore unknown JSON keys continue to work.
- `judge_error_kind` remains for existing decision/report consumers.
- No work-order schema changes.
- No manifest schema bump.
- No new artifact required for old runs to verify.

## Risks and Mitigations

- **False-positive classification.** Keep the taxonomy small, use strict
  patterns, and omit `failure_kind` when ambiguous.
- **Prompt cap blocks a valid large-model run.** Set the cap high, document it
  in the error text, and keep it as a single constant that can be adjusted after
  dogfood.
- **Runner-level guard affects non-provider command use.** It only checks
  `opts.Prompt`; verifier and command paths with empty prompts are unaffected.
  Tests should cover `RunCommand()` with an empty prompt.
- **Reports overstate remediation.** Use neutral wording: `failure kind`, not
  "cause" or "root cause".

## Acceptance Criteria

- Failed provider-like calls include `failure_kind` only when classification is
  high-confidence.
- The kind set is limited to the eight entries listed above.
- Judge failures still expose `judge_error_kind` when classified.
- Provider status, decision status, manifest provider summary, and report notes
  can all surface `failure_kind`.
- Oversized prompts fail before provider process launch.
- Oversized prompt failures classify as `prompt_too_large`.
- No new prompt diagnostic artifacts or schemas are introduced.
- `REVIEW.md` guidance remains explicitly deferred.

## Validation Commands

Run focused tests:

```text
go test ./internal/runner ./internal/artifact ./internal/report ./internal/manifest
go test ./internal/commands/researchcmd
```

Then run the broader suite:

```text
go test ./...
```
