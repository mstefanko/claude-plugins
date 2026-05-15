# Heartbeat Observability for Bakeoff - Implementation Plan

Date: 2026-05-15
Status: proposed
Scope: provider, judge, triage, and doctor provider-call progress reporting

## Decision

Improve Bakeoff's existing heartbeat lines by reporting richer process telemetry:
elapsed time, wall-clock budget, phase, output totals, output deltas, and
last-output age.

Do not try to report true model reasoning progress in v1. Bakeoff runs provider
CLIs as subprocesses, so it can observe timing and stdout/stderr movement, but it
cannot reliably know whether a provider is searching, reading, planning,
reasoning, or stuck unless the provider CLI emits that information.

Do not stream raw stdout snippets by default. Stdout may contain provider answer
text, scratchpad-like content, or the final schema payload. Printing excerpts to
the user's terminal risks leaking noisy intermediate content and making the CLI
harder to read.

## Current Behavior

Provider calls already emit compact heartbeat lines unless `--quiet` is passed:

```text
[provider=codex t=60s out=12.3KB quiet=14s]
```

This is implemented through:

- `budgets.heartbeat_seconds` validation and defaulting in
  `src/bakeoff/work_order.py`.
- `run_provider(..., on_tick=...)` in `src/bakeoff/runner.py`.
- `make_tick_printer()` in `src/bakeoff/cli.py`.
- `--quiet` on `research`, `rerun`, `triage`, and `doctor`.

The runner already tracks enough state to make the heartbeat more useful:

- elapsed wall time
- configured wall-clock budget
- retained stdout/stderr bytes
- observed stdout/stderr bytes
- last stdout/stderr/output age
- quiet/running phase
- heartbeat count and quiet tick count
- output cap metadata

## Goals

- Give users confidence that provider work is still moving.
- Make slow or quiet calls easier to distinguish from active output streaming.
- Keep heartbeat output compact enough for normal terminal use.
- Preserve the existing `--quiet` escape hatch.
- Avoid contaminating provider stdout artifacts or structured final JSON.
- Keep progress reporting honest about what Bakeoff can and cannot observe.

## Non-Goals

- No attempt to parse model chain-of-thought or infer semantic task progress.
- No prompt changes asking providers to self-report progress while working.
- No default printing of raw provider stdout or final JSON fragments.
- No terminal UI, spinner framework, curses view, or live dashboard in v1.
- No changes to run artifact schemas beyond already-recorded `io` metadata unless
  needed for a small, documented field.

## Proposed Output

Replace the current default heartbeat line with a compact, phase-aware line:

```text
[codex] running 01:00/15:00 out=12.3KB (+3.1KB) err=0.4KB last=14s
[claude] quiet 02:00/15:00 out=0.0KB err=0.0KB last=120s
[judge:gather] running 00:30/15:00 out=4.8KB (+4.8KB) err=0.0KB last=2s
```

Field meanings:

- `running` means there was recent stdout or stderr.
- `quiet` means no output has appeared for at least the quiet threshold.
- `01:00/15:00` is elapsed time against the configured wall-clock budget.
- `out` is retained stdout bytes formatted as KB.
- `(+3.1KB)` is stdout growth since the previous tick for this callback.
- `err` is retained stderr bytes formatted as KB.
- `last` is seconds since the most recent stdout or stderr.

If observed bytes exceed retained bytes because of truncation, prefer an explicit
marker rather than a confusing total:

```text
[codex] running 04:00/15:00 out=58.6KB observed=91.2KB err=0.0KB last=1s
```

## Implementation Plan

### 1. Add Formatting Helpers

Add small helpers in `src/bakeoff/cli.py`:

- `format_duration(seconds: int) -> str`
- `format_heartbeat_line(label: str, tick: dict[str, Any], previous: dict[str, int] | None) -> str`

Keep these helpers pure so they are easy to unit test without running provider
subprocesses.

### 2. Make `make_tick_printer()` Stateful

Update `make_tick_printer()` to keep the previous retained stdout/stderr byte
counts in the closure.

On every tick:

- read `elapsed`, `wall_seconds`, `phase`, `stdout_bytes`, `stderr_bytes`,
  `stdout_observed_bytes`, `stderr_observed_bytes`, and `last_output_age`
- compute stdout/stderr deltas from the previous tick
- print the formatted heartbeat line to stderr
- update the previous counters

This keeps runner behavior unchanged and avoids adding mutable presentation state
to `src/bakeoff/runner.py`.

### 3. Keep Runner Payload Stable Unless Needed

The current tick payload already includes the core fields needed by the printer.
Only change `src/bakeoff/runner.py` if a missing field is discovered during
implementation.

If runner changes are needed, prefer additive fields and keep them mirrored in
`result["io"]` when they describe final call state.

### 4. Update Tests

Add focused tests for formatting and callback state:

- duration formatting below and above one hour
- first heartbeat has no misleading delta
- later heartbeat reports stdout delta
- observed bytes are shown when observed and retained byte counts diverge
- quiet ticks still print `quiet`
- `quiet=True` still returns `None`

Existing runner tests should remain valid because the heartbeat callback payload
and stdout isolation behavior do not need to change.

### 5. Update Documentation

Update the README heartbeat section to mention:

- richer progress lines are emitted to stderr by default
- `--quiet` still suppresses them
- `budgets.heartbeat_seconds` controls frequency
- progress is subprocess telemetry, not semantic model progress

## Optional Follow-Up: Snippets

If users still want more visibility after richer telemetry, add an explicit
opt-in mode rather than enabling snippets by default.

Candidate flag:

```text
--heartbeat-detail compact|verbose|stderr-tail
```

Initial behavior:

- `compact`: the default line described above
- `verbose`: include stdout/stderr observed totals, quiet threshold, and output
  cap hints
- `stderr-tail`: include a sanitized single-line tail from provider stderr only

Do not add `stdout-tail` without a separate decision. Stdout is the structured
answer channel and may contain content that should remain in artifacts rather
than live terminal progress.

## Risks

- More detailed heartbeat lines can become visual noise if they are too wide.
- Byte deltas can look like progress even when the provider is emitting
  unhelpful chatter.
- Provider CLIs differ in how much stderr progress they expose, so snippet mode
  may be useful for one backend and empty for another.
- Any snippet mode needs sanitization and length limits to avoid leaking secrets,
  ANSI noise, or large terminal output.

## Acceptance Criteria

- Existing `--quiet` behavior is preserved.
- Heartbeats show elapsed time against the configured wall-clock budget.
- Heartbeats distinguish `running` from `quiet`.
- Heartbeats show stdout growth since the previous tick.
- Heartbeats still write only to stderr.
- Provider stdout artifacts and `<final_json>` extraction are unaffected.
- README describes the improved heartbeat behavior and its limits.
