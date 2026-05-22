# Claude Timeout Salvage Implementation Plan

Date: 2026-05-22

Status: validated and scope-reduced after multi-agent review, recommendation
critique, telemetry audit, and bloat audit

Scope: preserve provider artifacts and actionable diagnostics when Claude
produces no stdout, especially when extended thinking exhausts model-side output
tokens before `<final_json>` reaches stdout.

## Decision

Ship a narrow artifact-salvage patch first:

1. Wire Claude support for `--output-last-message` wherever Bakeoff already
   creates `last-message.txt` for Codex.
2. Extract the existing final-JSON source selection into a testable salvage
   helper that can read stdout or `last-message.txt`.
3. Add one new non-success run status, `salvaged`.
4. Write a small `salvage.json` when a failed run recovers usable structured
   output from an artifact.
5. Split timeout diagnostics into `max_tokens`, `quiet_stdout`, and
   `wall_clock`, but do not add retry behavior in this pass. `max_tokens` is
   best-effort unless the marker appears in a Bakeoff-captured artifact.

Do not change signal handling, kill grace, concurrency behavior, JSONL
discovery, or retry policy in PR1.

## Why This Shape

The incident was not a normal stdout overflow. Claude hit the provider/model
output-token cap while spending all emitted API output on extended thinking.
Bakeoff saw zero stdout bytes and eventually recorded only a timeout. The bad
operator outcome was not merely that the provider failed; it was that the run
left no useful artifact or diagnosis in Bakeoff's normal surfaces.

The smallest useful fix is to make Claude produce the same side-channel final
message artifact that Codex already uses, then teach the runner to preserve and
label recovered output from that artifact without treating it as a normal
success.

This deliberately avoids the larger plan's speculative pieces:

- no provider-specific signal ladder;
- no global `WaitDelay` change;
- no new `events.jsonl` stream without a consumer;
- no filesystem walk through `~/.claude/projects` in PR1;
- no automatic retry with lower effort or thinking disabled.

## Validated Code Facts

### Claude `last-message.txt` Is Not Just Two Call Sites

The bloat audit was directionally right that the project already has
`last-message.txt` machinery, but its "two call sites only" claim is
under-scoped.

Current facts:

- `internal/provider/provider.go` appends `--output-last-message` only in the
  Codex branch of `BuildParticipantArgv`.
- `ScopeCapabilitiesFromHelp` detects `output_last_message` only for Codex.
- `internal/commands/researchcmd/run.go` sets `finalMessagePath` only when the
  participant or judge backend is Codex.
- `internal/commands/buildcmd/providers.go` and `internal/commands/buildcmd/judge.go`
  also wire `last-message.txt` only through the Codex capability path.

PR1 must therefore add Claude provider support and capability detection, then
enable the existing call sites for Claude when the flag is supported. It is not
only a call-site patch.

### Existing Salvage Hook Is Real

`internal/runner/runner.go` already has `finalJSONText(stdout,
finalMessagePath)`, which prefers `last-message.txt` when present and otherwise
uses stdout. This is the right starting point, but PR1 must change the ordering:
normal successful completions parse stdout first, and side-artifact fallback is
attempted only after a failed terminal status. Rename or extract the current
logic into clearer helpers such as:

```go
func finalJSONFromStdout(stdout string) (text string, source string, ok bool)
func salvageFinalJSON(stdout string, finalMessagePath string) (text string, source string, ok bool)
```

Keep the helper small and deterministic. It should not inspect Claude JSONL
sessions in PR1.

### Quiet Telemetry Already Exists

The runner already tracks:

- `Tick.LastStdoutAge`;
- `Result.IO.LastStdoutAge`;
- `quietTickCount`;
- last-stdout timing in the runner IO stats.

Do not add a new event writer in PR1. Use the existing result/tick fields to
drive classification and tests.

### Timeout Classification Needs Result Context

`internal/runner/classify.go` currently receives only `status`, `stdout`, and
`stderr`, so it cannot split timeouts by `LastStdoutAge` by itself.

Implement timeout subtyping in `internal/artifact.ResultMap`, using a small
private artifact helper if needed. `ResultMap` already receives the full
`runner.Result`, including `result.IO.LastStdoutAge`, raw stdout/stderr, status,
and byte counts. Keep `runner.ClassifyFailure` as the generic text/status
classifier and let `ResultMap` override structural `timeout` only when it has
enough result context to assign `max_tokens`, `quiet_stdout`, or `wall_clock`.

Do not extend the classifier signature in PR1.

### `max_tokens` Signal Is Not Currently Guaranteed

The observed incident had `stop_reason: max_tokens` in Claude's session JSONL
under `~/.claude/projects`, but Bakeoff does not currently discover or persist
that JSONL path. Code search found no existing runtime artifact that reliably
captures Claude `stop_reason`.

For PR1, classify `max_tokens` only from explicit text already captured in
stdout, stderr, `last-message.txt`, or a provider artifact that Bakeoff itself
writes. If that marker is absent, keep the better available subtype
(`quiet_stdout` or `wall_clock`) and let JSONL discovery remain a follow-up.

### Build Safety Already Has A Good Gate

`internal/artifact.ProviderSucceeded` currently returns true only for
`ok` and `ok_after_format_retry`. Keep `salvaged` outside that set. Build apply
and winner selection must continue to refuse salvaged provider output.

## Data Contract

### Status

Add one run status:

```json
{
  "status": "salvaged"
}
```

Meaning: the provider invocation failed or timed out, but Bakeoff recovered a
valid final JSON object from an artifact such as `last-message.txt`.

`salvaged` is never success. It is evidence preservation, not provider
corroboration.

Summary projection:

- `ok` and `ok_after_format_retry` remain compact `ok`;
- `salvaged` maps to compact `warn`;
- other failures keep compact `failed`.

Keep the raw status visible wherever summaries already include raw provider
status details.

### Failure Kind

Use a small first-pass taxonomy:

| Kind | Meaning | Retry in PR1 |
| --- | --- | --- |
| `max_tokens` | Provider/model exhausted output tokens before emitting usable stdout. | No |
| `quiet_stdout` | Process ran but produced no stdout for the relevant quiet window. | No |
| `wall_clock` | Bakeoff wall-clock timer ended the process. | No |

The earlier retry policy is intentionally deferred. It has cost and billing
implications and was not justified by one incident.

### Salvage Metadata

When salvage succeeds, write `salvage.json` next to the existing provider
artifacts:

```json
{
  "source": "last-message.txt",
  "stop_reason_hint": "max_tokens",
  "recovered_json_bytes": 1234,
  "recovered_at": "2026-05-22T15:04:05Z"
}
```

Field rules:

- `source` is the artifact used for recovery, initially `last-message.txt` or
  `stdout`.
- `stop_reason_hint` is best-effort and may be omitted when not known.
- `recovered_json_bytes` is the byte length of the recovered final JSON text.
- `recovered_at` is UTC RFC3339.

Do not include `jsonl_path`, confidence scoring, or Claude session discovery in
v1.

## Workstream 1: Claude `last-message.txt`

### User Value

When Claude does not print stdout, Bakeoff still has a structured provider-side
artifact to inspect and potentially salvage.

### Implementation Notes

1. Extend `provider.BuildParticipantArgv` so the Claude branch can append
   `--output-last-message <path>` when the capability is present and a final
   message path is supplied.
2. Extend `ScopeCapabilitiesFromHelp("claude", help)` to detect
   `--output-last-message`.
3. Replace Codex-only path assignment in research/build worker and judge call
   sites with capability-aware assignment for Codex or Claude.
4. Keep existing Codex behavior unchanged.
5. Add provider argument tests for Claude with and without the flag.

Include research and build providers and judges in PR1. Triage can follow the
same helper path if the code naturally supports it, but it is not required to
resolve the observed multi-lens failure.

## Workstream 2: Salvage Helper And Status

### User Value

A run that would have been "timeout with 0 stdout" can become "failed, but
structured output was recovered from `last-message.txt`." Operators get
something useful back without pretending the provider completed normally.

### Implementation Notes

1. Extract `finalJSONText` into a helper with an explicit boolean success
   return.
2. For normal zero-exit completions, parse stdout first and return `ok` only
   when stdout contains valid final JSON. Do not let `last-message.txt`
   override valid stdout on the normal success path.
3. In failed terminal states, attempt salvage after the process exits or times
   out. Prefer `last-message.txt` when present, then stdout as a secondary
   source for cases where a process failed after printing valid final JSON.
4. If final JSON extraction and schema validation succeed from the salvage
   source, return status `salvaged` and preserve the parsed JSON in the normal
   result payload fields.
5. If `last-message.txt` exists but final JSON extraction or schema validation
   fails, keep the original failure status and do not write `salvage.json`.
6. Keep normal `ok` behavior unchanged when stdout contains valid `<final_json>`.
7. Disambiguation: existing output-cap recovery can still return `ok` when
   Bakeoff captured valid final JSON before the cap ended collection. The new
   `salvaged` status is only for failed terminal runs recovered from a side
   artifact or from stdout after failure.

## Workstream 3: `salvage.json`

### User Value

The artifact directory explains how Bakeoff recovered evidence and why the run
is still not normal success.

### Implementation Notes

1. Write `salvage.json` only when salvage succeeds.
2. Keep it slim: `{source, stop_reason_hint, recovered_json_bytes, recovered_at}`.
3. Prefer structural hints from provider artifacts or stderr when available.
4. Do not block the run if writing `salvage.json` fails; record the write error
   in stderr/status details if the local pattern supports it.

## Workstream 4: Timeout Subtype

### User Value

Reports and decision artifacts distinguish "wall clock expired" from "provider
was silent" from "provider hit max tokens." This is the difference between a
useful postmortem and a black-box timeout.

### Implementation Notes

1. Implement subtyping in `internal/artifact.ResultMap`, not in
   `runner.ClassifyFailure`.
2. Preserve existing `failure_kind: timeout` behavior until the result-aware
   subtype can be assigned.
3. Add subtypes only where there is high-confidence evidence:
   `max_tokens`, `quiet_stdout`, `wall_clock`.
4. Use `result.IO.LastStdoutAge`, stdout byte counts, and runner terminal
   status for `quiet_stdout` and `wall_clock`.
5. Use explicit text markers such as `stop_reason: max_tokens` or equivalent
   provider artifact hints for `max_tokens`. Do not require `max_tokens` when
   the only known source is deferred Claude session JSONL.
6. Do not add auto-retry decisions in this workstream.

## Workstream 5: Summaries And Build Refusal

### User Value

Users see that a provider produced usable evidence but did not complete cleanly.
Build mode does not accidentally apply code from a salvaged run.

### Implementation Notes

1. Add `runstatus.Salvaged`.
2. Update compact summary mapping so `salvaged` becomes `warn`, not `ok`.
3. Keep `artifact.ProviderSucceeded` limited to `ok` and
   `ok_after_format_retry`.
4. Add tests proving `salvaged` does not count as build-apply eligible.
5. Audit every status consumer before landing the new status:
   `internal/runner` constants and tests, `internal/artifact` result maps and
   payload stripping, `internal/summary`, `internal/report`,
   `internal/manifest`, `internal/commands/buildcmd`, research/build decision
   projections, exit-code handling, and `internal/buildverify` status mapping.
   Any consumer that does not have special salvage behavior should treat
   `salvaged` as failed or warning, never success.
6. Add a short report note for partial multi-lens results when a peer provider
   timed out or was salvaged and the lens is therefore single-provider-only.

## Explicit Deferrals

- No `DefaultKillGrace` change from 1s to 15s. It is shared by multiple
  timeout/cancel paths, and this incident happened before a soft signal would
  have mattered.
- No provider-specific signal ladder. The SIGINT/SIGTERM flush claim is not
  verified enough to justify new process-control behavior.
- No first-byte or quiet-watchdog kill in PR1. The telemetry exists, but
  process preemption is a separate behavior change.
- No Claude JSONL discovery through `~/.claude/projects` in PR1. It is fragile
  and partially redundant once `last-message.txt` exists.
- No `events.jsonl` stream without a consumer. If a forensic trail is needed
  later, first consider dumping the existing tick stream.
- No concurrency serialization investigation. The evidence is N=1 and could be
  lazy session-file creation.
- No automatic retry. Retry policy changes billing, runtime, and evaluation
  semantics.

## Test Plan

Add or update focused tests:

1. Provider argv/capability tests for Claude `--output-last-message`.
2. Research/build call-site tests proving Claude receives `last-message.txt`
   when supported.
3. Runner unit tests for salvage from `last-message.txt` when stdout is empty.
4. Runner tests showing normal stdout success remains `ok`.
5. Summary tests for compact `warn` on `salvaged`.
6. Artifact/build tests proving `salvaged` is not provider success.
7. Classification tests for `max_tokens`, `quiet_stdout`, and `wall_clock`
   where result context is available.
8. Golden fixture updates only where schemas actually change, especially the
   timeout and output-cap salvage parity fixtures.

## Definition Of Done

Recreate the failure mode:

1. Claude invoked by Bakeoff supports `--output-last-message`.
2. Claude hits `max_tokens` during extended thinking and emits zero stdout.
3. Bakeoff records a non-empty `last-message.txt`.
4. Bakeoff recovers valid final JSON from that artifact when possible.
5. Provider status is `salvaged`, not `ok`.
6. `failure_kind` is `max_tokens` when the hint is present.
7. `salvage.json` records the recovery source and byte count.
8. Build mode refuses to apply salvaged output.
9. Reports/summaries show a warning/partial state instead of an opaque timeout.

If no captured artifact contains an explicit `max_tokens` marker, the DoD still
passes with `failure_kind: quiet_stdout` or `failure_kind: wall_clock`. The
important PR1 guarantee is artifact preservation and a non-success salvage
status; exact Claude API stop-reason recovery waits for the deferred JSONL work.

The practical bar: the next incident should leave enough local artifacts to
answer "what happened?" without manually spelunking provider internals.
