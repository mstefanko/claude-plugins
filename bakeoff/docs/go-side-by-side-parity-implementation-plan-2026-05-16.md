# Go Side-By-Side Parity - Implementation Plan

Date: 2026-05-16
Status: proposed
Scope: side-by-side Go implementation of the Bakeoff CLI, using the existing
Python CLI as a frozen behavior oracle until the Go CLI reaches parity

## Decision

Build a Go Bakeoff CLI side-by-side with the current Python CLI in this same
`bakeoff/` repository and drive it to behavioral parity before considering a
cutover.

Do not do the full Python maintainability refactor first. Use
`docs/cli-maintainability-refactor-implementation-plan-2026-05-16.md` as the
domain map for the Go implementation instead:

- command modules become Go command packages
- `runner.py` becomes the Go provider runner package
- ledger, manifest, summaries, verification, decisions, prompts, scope, and
  artifacts become focused Go internal packages
- Python stays available as the canonical implementation while Go catches up

The point of this plan is to find out quickly whether Go gives Bakeoff a
cleaner, tighter CLI without paying for a full Python cleanup and then paying
again for a rewrite.

## Hard Rule

After the Python behavior-freeze phase, do not touch the Python CLI
implementation while building the Go version.

Frozen means no edits under these surfaces unless an explicit oracle-fix commit
is approved:

- `src/bakeoff/`
- `bin/bakeoff`
- Python command behavior, prompt text, artifact layout, status vocabulary, and
  exit-code semantics

Allowed after the freeze:

- parity fixtures
- parity harnesses
- Go implementation files
- documentation updates
- tests that observe Python behavior without changing it

If the Go work exposes a Python bug, record it as an oracle issue. Do not quietly
"fix" Python to make Go easier to match.

## Inputs

Use these documents as the source material for the rewrite shape and decision
criteria:

- `docs/cli-maintainability-refactor-implementation-plan-2026-05-16.md`
- `docs/research-cli-languages-2026-05-16.md`
- `docs/research-llm-languages-2026-05-16.md`
- `docs/research-go-cli-patterns-2026-05-16.md`
- `docs/research-go-idioms-and-antipatterns-2026-05-16.md`

The research consensus is:

- Python remains the best language for AI-assisted maintenance of the current
  implementation.
- Go is the strongest rewrite candidate for Bakeoff if the goal is a powerful,
  native, single-binary CLI with clean subprocess orchestration.
- Rust is attractive for typed schemas and future local analysis performance,
  but it is not the first rewrite candidate for this subprocess-heavy harness.
- TypeScript/Node is not a useful move for Bakeoff.

## Goals

- Build a Go CLI beside Python, not in place of Python.
- Reach parity for command behavior, artifacts, reports, status JSON, and exit
  codes.
- Hit the hard parts early: provider subprocess lifecycle, output caps,
  final-json extraction, process cleanup, and format retry.
- Keep the implementation portable where Go makes that cheap: use `filepath`,
  argv arrays, explicit environment handling, and build tags where needed. Do
  not make Windows runtime parity a trial gate unless the team later needs it.
- Keep Go idiomatic instead of line-porting Python.
- Preserve Bakeoff's run-ledger compatibility so old runs remain readable.
- Keep cutover optional until parity is boring.

## Non-Goals

- Do not refactor the Python CLI before the Go trial, beyond freeze tests and
  parity fixtures.
- Do not redesign provider topology, work-order schema, prompt contracts,
  judging semantics, triage policy, or artifact layout during the Go trial.
- Do not add config files, SQLite, dashboards, caches, pruning, streaming event
  protocols, or plugin systems.
- Do not switch the public `bakeoff` command until parity has been demonstrated.
- Do not chase perfect byte-for-byte parity for every human help screen before
  core command behavior is proven.
- Do not add structured logging libraries, metrics, telemetry, alternative
  output formats, Homebrew formulas, release artifacts, installers,
  Windows-specific runtime parity gates, or distribution packaging during the
  parity trial. Low-cost portability hygiene is still expected.

## Recommended Go Stack

Use Go, not Rust, for the side-by-side trial.

Recommended dependencies:

- `github.com/spf13/cobra` for command structure, help, subcommands, and future
  completion support.
- `golang.org/x/sync/errgroup` for owned goroutine fan-out in the provider
  runner.
- Standard library for JSON, subprocesses, paths, hashing, embedded templates,
  signals, and tests.
- Avoid Viper, logging frameworks, ORM layers, rich terminal dependencies, and
  config frameworks.

Rationale:

- Cobra matches mature Go CLIs such as GitHub CLI, Kubernetes tools, and Hugo.
- Go's `exec.CommandContext`, context cancellation, and `Cmd.WaitDelay` map well
  to Bakeoff provider deadlines and kill-grace behavior.
- `errgroup` directly addresses the runner's stdout/stderr/heartbeat goroutine
  lifetime risk.
- The Go standard library is enough for the rest of Bakeoff's current needs.
- If Windows distribution becomes a real requirement, add
  `golang.org/x/sys/windows` behind Windows build tags for Job Object based
  process-tree cleanup. Do not add it during the parity trial just to speculate.

Go module rules:

- Put `go.mod` in this `bakeoff/` directory, not at the plugin marketplace
  repository root.
- Do not create a separate `bakeoff-go` repository, git submodule, nested Go
  workspace, or sibling checkout. The Go CLI lives beside the Python CLI in this
  repo.
- Start with module path `github.com/mstefanko/claude-plugins/bakeoff`, matching
  the current `origin` repository plus this subdirectory.
- Declare `go 1.22` or newer. The local development toolchain is currently
  Go 1.24.4; do not rely on 1.24-only APIs unless the module version is bumped
  deliberately.

## Project Setup Rules

Project setup is part of Phase 1 and must not be deferred until after command
behavior work starts:

- Keep one repository containing both implementations:
  - Python remains under `src/bakeoff/`, `tests/`, `pyproject.toml`, and
    `bin/bakeoff`.
  - Go is added under `go.mod`, `cmd/bakeoff-go/`, and `internal/...`.
- The Go binary name during the trial is `bakeoff-go`. The public Python
  launcher remains `bin/bakeoff` until the optional cutover phase.
- Commit `go.mod` and `go.sum` as soon as Cobra/errgroup are introduced.
- The first Go scaffold must be runnable with `go run ./cmd/bakeoff-go --help`
  and testable with `go test ./...` from this `bakeoff/` directory.
- Do not require installing the Python package to build or test the Go scaffold.
  Cross-language parity tests may invoke Python later, but ordinary Go package
  tests should stand on their own.

## Go Architecture Rules

Use these rules from the Go CLI pattern research as hard implementation
constraints, not taste preferences:

- `cmd/bakeoff-go/main.go` must be thin: build a signal-aware context, call
  `internal/cli.Main(ctx, os.Args[1:])`, and call `os.Exit` exactly once.
- `internal/cli` owns the Cobra root, command registration, factory
  construction, global error mapping, and exit code return.
- The `Factory` owns shared process-lifetime dependencies for one CLI
  invocation: output streams, provider executable lookup, provider/scope
  capability probes, build info, and clock/temp-path seams used by tests.
- Every command exposes `NewCmd<Foo>(f *Factory, runF func(context.Context, *FooOptions) error) *cobra.Command`.
- Every command has a `<Foo>Options` struct. Cobra fills options; command
  business logic runs from the options struct.
- Every command uses an `output.Streams` object. No direct `fmt.Println`,
  `os.Stdout`, or `os.Stderr` outside `internal/output`, `internal/cli`, and
  narrowly reviewed command rendering helpers.
- Cobra handlers must use `cmd.Context()` and pass it down. Do not call
  `context.Background()` in command code except for the explicitly documented
  short-bounded cleanup path after an interrupt.
- Every long-running function takes `ctx context.Context` as the first
  parameter. Never store `context.Context` in a struct.
- Functions that spawn goroutines use `errgroup` or an equivalent explicit
  wait/cancel structure. No fire-and-forget goroutines.
- Producers return concrete structs. Consumers may define narrow interfaces
  only when there is a real test seam or second implementation.
- Prompt and template text lives in embedded files via `embed.FS`, not large Go
  raw-string literals.
- Use typed sentinel errors and error structs with `%w` wrapping. Do not branch
  on error strings.
- Provider and tool invocations are argv arrays only. Do not use shell command
  strings, `sh -c`, `cmd.exe /C`, `CombinedOutput`, or global environment
  mutation to run providers.
- Avoid package-level mutable globals, side-effectful `init()`, `panic` for
  normal errors, and `utils` or `helpers` packages.
- Do not add structured logging during the parity trial. Human output and
  diagnostics go through `internal/output`; errors are returned and rendered
  once at the CLI boundary.

## Error, Exit, And Output Contract

Go must preserve Bakeoff's exit-code behavior through a typed error model:

| Exit code | Meaning | Go error route |
| --- | --- | --- |
| `0` | success | nil error |
| `1` | runtime or verification failure | `RuntimeError`, `SilentError`, or unclassified error |
| `2` | usage, config, validation, or missing-input error | `UsageError` or `ValidationError` |
| `3` | completed run with unresolved judge disagreement | `JudgeDisagreementError` |
| `130` | interrupted | `InterruptedError`, `context.Canceled` from signal context, or SIGINT/SIGTERM path |

Interrupt rules:

- `main()` creates exactly one signal-aware root context using
  `signal.NotifyContext`. Include `os.Interrupt` everywhere and SIGTERM on
  platforms where Go exposes it.
- The CLI error mapper classifies an error as interrupted when either the error
  wraps `InterruptedError`, or the error wraps `context.Canceled` and the root
  signal context was cancelled by a signal during unwind.
- `--json` does not change interrupt rendering. If interrupted before a command
  reaches its final summary printer, stdout remains empty and stderr is exactly
  `error: interrupted\n`, matching the Python `KeyboardInterrupt` path.
- Provider runner cancellation can still write provider status `cancelled` for
  artifacts, but command execution must propagate the interrupt to the CLI
  boundary so the process exits `130`, not `1`.
- Cleanup after an interrupt is best-effort and short-bounded. Process-tree
  termination and partial artifact salvage may use a detached context derived
  from `context.Background()` with a hard two-second deadline because the parent
  context is already cancelled. Cleanup failures must not replace the final
  interrupted exit code.

Root command rules:

- Set `SilenceUsage: true` and `SilenceErrors: true` on the Cobra root and
  subcommands.
- The root error mapper decides when to print usage. Runtime errors must not
  dump usage.
- Commands return errors; command code must not call `os.Exit`.
- `main()` is the only place that calls `os.Exit`.

Output stream rules:

- Human command output goes to stdout.
- Notes, warnings, heartbeats, diagnostics, and errors go to stderr.
- `--json` emits one final pretty JSON object to stdout and suppresses ordinary
  human progress output and provider heartbeats.
- `--json` should include warnings in the JSON summary when Python does; it
  should not invent extra stderr lines.
- Validation/runtime errors in JSON mode may still render the top-level
  `error:` line to stderr if Python does.

JSON formatting rules:

- Artifact JSON written by shared IO follows Python `io.write_json_atomic`:
  two-space indent, sorted keys, trailing newline, LF line endings.
- Final command JSON summaries that use Python `print_json_summary` follow
  Python's current insertion order with two-space indent and no explicit
  `sort_keys=True`. This includes `research --json`, `triage --json`, and
  `runs verify --json`.
- Commands that currently call `json.dumps(..., sort_keys=True)` keep sorted
  object keys. This includes `doctor --json` and `ls --json`.
- The parity harness must treat this as an oracle distinction. Do not "fix"
  Python's command-summary ordering while building Go.
- In Go, model insertion-ordered command summaries as explicit structs or a
  small ordered-summary helper in `internal/summary`; do not use
  `map[string]any` for final stdout JSON where field order is part of the
  Python oracle. Nested objects with user/work-order-defined key order, such as
  provider summaries, must preserve that source order rather than relying on
  Go's sorted map encoding.
- Sorted artifact and report JSON may use maps when deterministic key sorting
  is desired.

Status vocabulary rules:

- Provider runner result statuses: `ok`, `ok_after_format_retry`, `timeout`,
  `output_cap`, `missing_provider`, `exit_error`, `schema_error`, `cancelled`.
- Command-created provider status: `scope_error`.
- Triage dry-run status: `dry_run`.
- Command JSON summary statuses: `ok`, `judge_disagreement`, `failed`.
- Summary-only status labels include `failed`, `not_run`, `missing_status`,
  and `invalid_status` where Python currently emits them.
- `format_retry` and `stderr_truncated` are metadata fields, not top-level
  provider status values.

Any new status string is a prompt/artifact contract change and must be approved
outside this parity plan.

## Provider Capability Probe Contract

Provider and scope capability probing must match Python's effective behavior
while avoiding package globals in Go:

- Python currently caches `detect_scope_capabilities(backend)` and
  `codex_exec_supports_output_last_message()` for the lifetime of the Python
  process. The Go rewrite should preserve the observable behavior with an
  explicit cache object, not package-level `sync.Once` globals.
- Construct a `provider.Capabilities` or equivalent registry in `internal/cli`
  and thread it through `Factory`. The registry memoizes probe results for the
  lifetime of one CLI invocation.
- Cache keys must include the probe kind and backend. Resolve executables
  through the same lookup path the command will use so tests can swap fake
  `claude` and `codex` binaries by constructing a fresh factory.
- Scope detection and Codex `--output-last-message` support detection both live
  in this registry. Concurrent first callers for the same key must share one
  probe and receive the same result.
- Probe failures are cached as failed capability results, matching Python's
  `available: false` and `probe_error` shape.
- Research freezes one capability snapshot per backend before launching workers
  and passes that snapshot through scope execution. Do not let one provider in
  the same run observe different help-text capabilities than another provider
  using the same backend.
- Do not add an on-disk capability cache, TTL, provider-version database, or
  cross-process cache during parity. Provider CLIs can change outside Bakeoff;
  process exit is the invalidation event.

## Resolved Policy Decisions

These questions came out of the Go CLI research and are now part of the plan:

- Command JSON order follows the Python oracle per command. Reject global
  key-order normalization because it would hide stream drift and change
  user-visible `--json` output without an approved oracle change.
- Capability probing uses an explicit per-invocation registry. Reject
  per-call reprobes because they waste subprocess calls and can observe
  mid-run drift; reject package globals and on-disk caches because they make
  tests and provider upgrades stale.
- Interrupts exit `130` from the CLI boundary even when provider cleanup writes
  `cancelled` status artifacts. Reject treating `cancelled` as an ordinary
  failed provider when the root signal context is the cause; reject mapping all
  `context.Canceled` errors to `130` because internal cancellations and
  deadlines must still produce their own statuses.
- Stream parity freezes stdout, stderr, and exit code for the mandatory cases
  above. Reject broad normalizers that erase extra stderr in `--json` mode,
  reorder summary fields, rename statuses, or tolerate missing progress lines.

## Initial File Layout

Add Go side-by-side in this same `bakeoff/` repository without replacing the
Python package:

```text
go.mod
cmd/bakeoff-go/main.go
internal/cli/
internal/commands/
internal/commands/initcmd/
internal/commands/validatecmd/
internal/commands/researchcmd/
internal/commands/triagecmd/
internal/commands/runscmd/
internal/commands/showcmd/
internal/commands/doctorcmd/
internal/buildinfo/
internal/output/
internal/hints/
internal/workorder/
internal/provider/
internal/scope/
internal/prompt/
internal/runner/
internal/ledger/
internal/manifest/
internal/artifact/
internal/summary/
internal/verify/
internal/decision/
internal/report/
internal/triage/
internal/reviewcontext/
internal/parity/
```

Use `cmd/bakeoff-go` until cutover. The public Python command remains
`bin/bakeoff`.

## Python Refactor Plan To Go Package Map

Use the Python refactor target map as the Go package map:

Important: most Python names in the left column are proposed modules from the
Python refactor plan, not files that exist today. The current Python command
surface is still largely concentrated in `src/bakeoff/cli.py`. The Go work must
perform that decomposition directly in Go instead of waiting for Python to be
split first.

| Python refactor target | Go target | Purpose |
| --- | --- | --- |
| `output.py` | `internal/output` | quiet/json output, notes, warnings, heartbeat formatting |
| `command_hints.py` | `internal/hints` | next-command rendering |
| `ledger.py` | `internal/ledger` | run ids, latest resolution, path safety, artifact paths |
| `summaries.py` | `internal/summary` | machine-readable command summaries |
| `verification.py` | `internal/verify` | `runs verify`, fingerprints, recovery hints |
| `decisions.py` | `internal/decision` | compare/analyze decision resolution and dedupe |
| `artifacts.py` | `internal/artifact` | provider/judge/triage artifact writers and status shaping |
| `prompts.py` | `internal/prompt` | worker, judge, triage prompts and runtime budget blocks |
| `scope.py` | `internal/scope` | scope capability probing and scope execution controls |
| `commands/` | `internal/commands/*` | user-facing subcommand implementations |
| `runner.py` | `internal/runner` | provider process lifecycle, output caps, retries |

Do not preserve Python module names just for familiarity. Preserve domain
boundaries and behavior.

## Data Modeling Rules

Use strong Go structs for stable Bakeoff-owned data:

- work orders
- providers and judge participants
- budgets
- scope policy
- provider status metadata
- command summaries
- manifests
- citation checks

Use `map[string]any` or `json.RawMessage` for model-produced `final_json` values
where preserving unknown fields matters.

Reason: full typed structs for every model response would look attractive, but
they can accidentally drop unknown fields or force schema cleanup before parity.
During parity, validators should check required fields and enums while preserving
the original JSON object for artifacts.

Later, after parity, Go can tighten selected model schemas.

## JSON And Artifact Rules

Implement shared artifact IO before command behavior:

- `WriteTextAtomic(path, text)`
- `WriteJSONAtomic(path, value)`
- `ReadOptionalJSON(path)`
- `ReadRequiredObject(path)`
- SHA-256 and size fingerprint helpers

Match Python's artifact expectations:

- UTF-8 text
- two-space indented JSON
- deterministic key order where maps are used
- trailing newline for JSON/text artifacts where Python currently writes one
- LF-only line endings
- same artifact paths under `runs/<run-id>/`

Semantic parity is required for all JSON artifacts. Byte-for-byte parity is
required for prompts unless a deliberate prompt contract change is separately
approved.

## Parity Strategy

Build a parity harness before implementing most Go behavior.

Recommended harness:

```text
scripts/parity-go.py
tests/parity/fakes/
tests/parity/fixtures/<workflow>/
```

The harness may be Python, but it must not import or modify `bakeoff` internals.
It should invoke both CLIs as black boxes:

```text
bin/bakeoff ...
go run ./cmd/bakeoff-go ...
```

Use deterministic fake providers, not real Claude or Codex calls.

The pass contract is strict: the harness exits `0` only when `diff_count == 0`
after approved normalization. It must emit a structured diff report when it
fails so each drift is attributable to a workflow, stream, artifact, and JSON
path.

Compare:

- exit code
- stdout/stderr after normalizing temp paths and run ids
- run ledger tree shape
- required artifacts
- provider prompt files
- provider/judge/triage status semantics
- `decision.json`
- `report.md`
- `meta.json` with dynamic fields normalized
- `manifest.json` structure and local fingerprint validity
- `bakeoff runs verify` success for both ledgers

Normalize these fields during comparison:

- run id when auto-generated
- absolute temp paths
- wall-clock seconds
- process output byte timings where fake providers make tiny differences
- `started_at` and `finished_at`
- provider CLI version strings in `meta.json`
- `bakeoff_version` while Python and Go intentionally report different build
  metadata during the trial
- manifest fingerprints when the underlying artifact bytes intentionally differ
  only because of normalized dynamic fields

Do not normalize status names, artifact names, prompt text, decision kinds,
triage states, exit codes, or report content.

Stream freeze cases. Rows for runner failures freeze the CLI stdout/stderr and
the corresponding provider stdout/stderr/status artifacts because Python captures
provider streams instead of forwarding them directly.

| Case | stdout contract | stderr contract | exit |
| --- | --- | --- | --- |
| `doctor --skip-auth-probe --json` with fake tools | one pretty JSON object with sorted keys and Python's current top-level fields | empty | `0` when fake tools and cwd checks pass, `1` for missing/unavailable tool fixture |
| `doctor --skip-auth-probe` with fake tools | human lines for header, tool paths/versions, defaults, scope policy, scope capabilities, cwd writable, and bias | empty unless Python emits warnings for the fixture | `0` or `1` |
| `doctor --json --quiet` with fake auth-probe failures | one sorted-key JSON object containing `warnings` and `auth_probes` details | empty | `0` when only auth probes fail, matching Python's warning-only behavior |
| `research --json` success | one insertion-ordered `print_json_summary` object and no human progress lines | empty; `--json` implies effective quiet | `0` |
| `research --json` both workers failed | one insertion-ordered summary with `status: "failed"` and provider raw statuses | empty except warnings Python emits in JSON mode | `1` |
| `research --json` judge disagreement | one insertion-ordered summary with `status: "judge_disagreement"` | empty except warnings Python emits in JSON mode | `3` |
| `research --json` interrupted | empty | exactly `error: interrupted\n` | `130` |
| `validate` failed work order | empty | exactly one `error: <ValidationError message>\n` line | `2` |
| `research --json` validation failure | empty | exactly one `error: <ValidationError message>\n` line | `2` |
| timeout fixture | summary or human provider line reports failed/timeout according to the command under test | CLI stderr is only heartbeat/final-tick output in human mode and empty in `--json`; provider stderr artifact is preserved | `1` for failed research |
| output-cap fixture | summary or human provider line reports failed/output_cap, with provider stdout artifact truncation marker preserved | CLI stderr follows quiet/human mode; provider stderr artifact plus Python's appended diagnostics are preserved | `1` for failed research |
| output-cap salvage fixture | summary reports provider `ok` with raw status `ok` and truncation metadata in artifacts when Python accepts a late retained final JSON | CLI stderr follows quiet/human mode; provider stream artifacts are preserved | command-specific |
| schema retry success | summary reports `ok_after_format_retry`, with repair artifacts present | CLI stderr follows quiet/human mode; repair-flow diagnostics are preserved in artifacts | command-specific success |
| schema retry terminal failure | summary reports failed provider with raw status `schema_error` | CLI stderr follows quiet/human mode; provider stderr artifact includes the validation message Python appended | command-specific failure |

The harness may normalize dynamic seconds, absolute temp paths, auto-generated
run ids, provider version strings, build metadata, and timestamp fields in these
fixtures. It must not normalize away extra stderr lines in `--json` mode, missing
or extra human progress lines, summary field order, provider status strings, or
exit-code drift.

Help output parity is content-level during the trial: command names, flags,
defaults, choices, exit-code documentation, and important examples should
match. Argparse and Cobra formatting, wrapping, and section order do not need
byte-for-byte parity until an explicit cutover review demands it.

## Phase 0: Python Oracle Freeze

Goal: make Python a stable reference implementation before Go work begins.

Files to add or update:

- parity fixtures under `tests/parity/fixtures/`
- standalone deterministic fake provider scripts under `tests/parity/fakes/`
- `scripts/parity-go.py`
- prompt fixture generation from Python for worker, judge, and triage prompts
- a CI job or local CI script that runs `pytest` and the Python-only parity
  harness now, then adds `go test ./...` once Phase 1 lands
- optional docs describing the frozen contract

Do not refactor Python implementation code in this phase.

The existing fake providers in `tests/test_modes_end_to_end.py` are generated
inside a pytest helper. They must be extracted or reproduced as executable
black-box fixtures before Phase 0 is complete so both Python and Go can spawn
the same fake `claude` and `codex` commands through `PATH`.

Fixture layout should be explicit:

```text
tests/parity/
  fakes/
    fake_provider.py
    claude
    codex
  fixtures/
    research_success/
      python/
        stdout.txt
        stderr.txt
        exit_code.txt
        runs/
      normalized.json
    ...
```

Prompt fixtures produced in this phase are required inputs for Phase 2. Do not
start Phase 2 until they exist.

Every workflow fixture must store stdout, stderr, and exit code before
normalization, plus the approved normalized comparison form. The stream freeze
cases above are mandatory Phase 0 fixtures, not nice-to-have regression tests.

Capture these workflows:

- root orientation and `--help`
- `init gather`, `init compare`, `init analyze`, `init review`
- `validate`
- `research` success with fake providers
- `research --json`
- both-providers-failed research
- single-provider-only research
- gather judge format retry
- compare position swap winner and tie
- analyze spine selection
- auto triage for code-review facet
- `triage --dry-run`, `triage --json`, `triage --force`
- `rerun`
- `ls`, `ls --json`, filters
- `show`, `show --judge`, `show --judge-prompt`, `show --triage`
- `runs verify`, `runs verify --json`
- `doctor --skip-auth-probe --json`
- timeout, output cap, stdout salvage, stderr truncation, missing provider
- JSONC comment edge cases, including `//` and `/* */` markers inside string
  literals
- provider status coverage for `ok`, `ok_after_format_retry`, `timeout`,
  `output_cap`, `missing_provider`, `exit_error`, `schema_error`, `cancelled`,
  and `scope_error`

Done criteria:

- Python tests pass.
- Parity harness can run the Python side alone and produce normalized snapshots.
- Prompt fixtures exist for Phase 2.
- Fake provider executables exist as standalone files.
- CI or a committed local CI script runs Python tests and Python-only parity.
- The freeze commit clearly states that Python CLI behavior is now the oracle.

Suggested commit message:

```text
Freeze Python CLI behavior for Go parity
```

## Phase 1: Go Project Setup, Scaffold, And Command Shell

Goal: set up the Go project in this repository and create a buildable
`bakeoff-go` CLI with the command tree, global error mapping, and no real
command behavior beyond placeholders.

Files to add:

- `go.mod`
- `go.sum`
- `cmd/bakeoff-go/main.go`
- `internal/cli/root.go`
- `internal/cli/factory.go`
- `internal/cli/exit.go`
- `internal/commands/...`
- `internal/output/...`
- `internal/buildinfo/...`

Implementation notes:

- Initialize the Go module in the existing `bakeoff/` directory, beside
  `pyproject.toml`. Do not create a separate repository or nested workspace.
- Add the initial dependencies in this phase: Cobra and errgroup. Keep all other
  dependencies out until a later phase proves they are needed.
- Use Cobra command objects, but keep command handlers in internal packages.
- Use `signal.NotifyContext` in `Main()` and pass the context through
  `ExecuteContext`.
- Add the typed error model and exit-code mapper before real command behavior.
- Add the `Factory`, `NewCmd<Foo>(f, runF)`, `<Foo>Options`, and
  `output.Streams` patterns before real command behavior.
- Set `SilenceUsage: true` and `SilenceErrors: true` on the root and
  subcommands; render usage only for typed usage/flag errors.
- Preserve Bakeoff exit-code semantics:
  - `0`: success
  - `1`: runtime or verification failure
  - `2`: usage, config, validation, or missing-input error
  - `3`: unresolved judge disagreement
  - `130`: interrupted
- Do not worry about byte-for-byte argparse help parity yet.
- Do ensure command names, flags, defaults, and aliases match Python.
- Add `internal/buildinfo` with `Version`, `Commit`, and `Date` values suitable
  for `-ldflags -X` injection. During parity, either pin Go to Python's
  `0.0.0` value or normalize `bakeoff_version` in the harness.
- Keep `bin/bakeoff` pointed at Python in this phase. Do not add a launcher
  switch or wrapper behavior until cutover planning.

Done criteria:

- `go test ./...` passes.
- `go run ./cmd/bakeoff-go --help` works.
- `go env GOMOD` from this directory points at this repo's `go.mod`.
- All subcommands exist and parse the expected flags.
- Each command has table tests proving CLI args become the expected options
  through the `runF` seam.
- Error mapping tests prove usage, runtime, judge-disagreement, and interrupt
  errors return the intended exit codes and streams.
- Unimplemented commands return a clear internal placeholder error and exit `1`.

Suggested commit message:

```text
Set up side-by-side Go Bakeoff CLI
```

## Phase 2: Work Orders, IO, Prompts, And Init/Validate

Goal: implement the static, low-risk contracts before process execution.

Packages:

- `internal/workorder`
- `internal/prompt`
- `internal/output`
- `internal/hints`

Implementation notes:

- Port JSONC comment stripping and validation behavior.
- Preserve init template output for all modes.
- Preserve review template behavior.
- Preserve exact prompt text generation from Python for worker, judge, and
  triage prompts.
- Store prompts and init templates as embedded files via `embed.FS` so the
  prompt contract is reviewable and still ships in one binary.
- Keep validators strict enough for parity, but preserve unknown fields in model
  JSON objects.
- Keep command JSON summary ordering aligned with Python's current insertion
  order; keep artifact JSON sorted.

Done criteria:

- `init` and `validate` match Python behavior.
- Prompt-generation tests compare Go prompts against Python-generated prompt
  fixtures byte-for-byte.
- Go unit tests cover valid and invalid work orders.
- Parity harness passes for `init` and `validate`.

Suggested commit message:

```text
Port work-order validation and prompt contracts to Go
```

## Phase 3: Provider Runner Spike

Goal: hit the riskiest Go conversion wall early.

Package:

- `internal/runner`

Implement:

- stdin prompt feeding
- stdout and stderr concurrent capture
- retained stdout head/tail behavior
- stdout cap
- output-cap grace window
- max overrun bytes
- stderr truncation
- heartbeat ticks
- timeout
- process-group termination
- missing provider handling
- final-message file preference
- `<final_json>...</final_json>` extraction
- validator callback
- zero-exit schema-error format retry
- repair artifact metadata

Implementation notes:

- Use `exec.CommandContext` for deadlines.
- Use `Cmd.WaitDelay` for kill grace where it fits, but preserve Bakeoff's
  existing output-cap grace semantics separately.
- Use `errgroup` for stdout capture, stderr capture, heartbeat, wait, and
  output-cap watcher goroutines. Every goroutine must observe cancellation and
  be joined before returning a result.
- Do not use bare `io.ReadAll` on provider pipes. Capture loops must be
  context-aware and cap-aware.
- Add build-tagged process cleanup helpers:
  - `process_unix.go` for process groups
  - optional `process_windows.go` compile stub only if needed to keep the
    package portable; full Windows Job Object cleanup is deferred until Windows
    distribution becomes a real requirement
- Do not shell out to `taskkill` as the primary Windows cleanup mechanism if
  Windows support is later added. Use Job Objects or an equivalently reliable
  process-tree kill mechanism.
- Match the Python status vocabulary exactly.

Done criteria:

- Go unit tests cover every status currently covered in `tests/test_runner.py`.
- Process cleanup tests pass on Unix, including a fake provider that spawns a
  child process and ignores ordinary termination.
- Fake provider scripts can trigger timeout, output cap, salvage, stderr
  truncation, missing provider, schema error, and format retry.
- Parity harness passes runner-level scenarios before the full research command
  exists.
- Output-cap grace and timeout tests are stable under repeated runs; any timing
  tolerance must be narrow and documented.

Stop gate:

- If process cleanup or output-cap salvage cannot be made reliable quickly,
  stop the Go trial and return to Python cleanup. This is the right place to hit
  the wall.

Suggested commit message:

```text
Implement Go provider runner parity spike
```

## Phase 4: Ledger, Artifacts, Manifest, And Verification

Goal: make Go able to write and verify Bakeoff run ledgers.

Packages:

- `internal/ledger`
- `internal/artifact`
- `internal/manifest`
- `internal/verify`
- `internal/summary`

Implement:

- run id generation and validation
- `latest` symlink/text fallback behavior
- path safety checks
- artifact path helpers
- provider, judge, triage artifact writers
- status-without-payload shaping
- `meta.json`
- `manifest.json`
- manifest-backed `ls` rows
- `runs verify`
- machine-readable JSON summaries

Done criteria:

- Go-written ledgers pass Go `runs verify`.
- Python `bakeoff runs verify --out <go-ledger>` passes for Go-written ledgers,
  or any differences are explicitly documented as cutover blockers.
- Go `runs verify`, `ls`, and `show` can inspect Python-written ledgers for the
  workflows implemented so far.
- Manifest fingerprints are computed over the exact file bytes and match the
  recorded SHA-256 and size values.
- Parity harness passes ledger and verification scenarios.

Suggested commit message:

```text
Port run ledger artifacts and verification to Go
```

## Phase 5A: Provider And Scope Parity

Goal: port provider-specific argv building and fragile help-text scope parsing
before wiring the full research workflow.

Packages:

- `internal/provider`
- `internal/scope`

Implement:

- provider argv construction for Claude and Codex
- version argv construction
- Codex final-message support detection
- scope help argv construction
- help option token parsing
- scope capability detection from CLI help text
- scope execution controls
- web-scope isolated cwd and cleanup metadata

Implementation notes:

- Keep provider argv builders free of command-package imports.
- Treat help-text parsing as a small parser with table tests copied from Python
  behavior.
- Use the factory-owned capability registry from the Provider Capability Probe
  Contract. Do not introduce package-level `sync.Once`, `lru` equivalents, or
  mutable globals for probes.
- Freeze one scope capability snapshot per backend for each research run and
  pass it into all worker scope executions for that backend.
- Do not invoke real provider auth probes in this phase.

Done criteria:

- Go unit tests match Python scope capability parsing fixtures.
- Go provider argv tests cover Claude, Codex, final-message support, and scope
  extras.
- Parity harness covers `doctor --skip-auth-probe --json` as far as provider
  discovery allows without spendful calls.

Suggested commit message:

```text
Port provider argv and scope controls to Go
```

## Phase 5B: Research Workflow Parity

Goal: implement the primary workflow end to end.

Packages:

- `internal/commands/researchcmd`
- `internal/decision`
- `internal/report`

Implement:

- worker launch and cleanup
- judge launch
- gather, compare, and analyze decision resolution
- report rendering
- `research --json`
- automatic triage trigger decision, but not full triage execution until Phase 6

Implementation notes:

- Keep research command orchestration readable. It should not become the Go
  version of the old 2,000-line `cli.py`.
- Prefer small structs such as `RunOptions`, `RunContext`, and `ResearchResult`
  over wide function signatures.
- Do not introduce interfaces until there are at least two real implementations
  or a test seam that cannot be handled with function parameters.

Done criteria:

- Fake-provider research runs complete in Go.
- Go `decision.json` and `report.md` match Python semantically, and byte-for-byte
  where dynamic fields are not involved.
- Parity harness passes gather, compare, analyze, failed provider, and JSON
  summary scenarios.

Suggested commit message:

```text
Port research workflow to Go
```

## Phase 6: Triage, Rerun, Review Context, Show, Ls, And Doctor

Goal: close the remaining command surface.

Packages:

- `internal/commands/triagecmd`
- `internal/triage`
- `internal/reviewcontext`
- `internal/commands/showcmd`
- `internal/commands/runscmd`
- `internal/commands/doctorcmd`

Implement:

- `triage`
- `triage --dry-run`
- `triage --json`
- stale triage detection
- source finding filter
- citation extraction and checks
- triage markdown rendering
- `rerun`
- review context capture for `research --base`, `--changed-files`, and `--diff`
- `show` artifact flags
- `ls` and filters
- `doctor --skip-auth-probe`
- auth probes only after non-spendful doctor behavior is stable

Done criteria:

- Parity harness passes every frozen workflow.
- Existing Python ledgers can be inspected by Go `show`, `ls`, and `runs verify`.
- Go ledgers can be inspected by Python `show`, `ls`, and `runs verify`, unless a
  documented incompatibility is explicitly accepted before cutover.

Suggested commit message:

```text
Port remaining Bakeoff commands to Go
```

## Phase 7: Parity Hardening And Cutover Decision

Goal: decide whether Go is cleaner enough to replace Python.

Run:

```text
go test ./...
pytest
python3 scripts/parity-go.py
```

Windows smoke testing is optional during the trial. If Windows distribution
becomes a real goal before cutover, add a separate Windows parity gate with the
same fake providers and document any Python oracle gaps.

Manual smoke checks:

```text
go run ./cmd/bakeoff-go --help
go run ./cmd/bakeoff-go init gather --force
go run ./cmd/bakeoff-go validate gather.work-order.json
go run ./cmd/bakeoff-go doctor --skip-auth-probe --json
go run ./cmd/bakeoff-go ls --json
```

Dogfood checks:

- one non-spendful fake-provider run
- one real `doctor --skip-auth-probe`
- one carefully chosen real provider run only after fake-provider parity is
  complete

Cutover criteria:

- Go implementation is smaller or clearly easier to navigate than cleaned-up
  Python would be.
- A reviewable maintainability scorecard is green: no command file grows into a
  new monolith, runner complexity is isolated, package dependencies are
  acyclic, and a reviewer can trace `research` from command options to artifact
  writes without jumping through unrelated packages.
- Provider runner behavior is at least as reliable as Python.
- Parity harness is green.
- Python and Go can read each other's run ledgers.
- No prompt-contract drift.
- No unexplained status or exit-code drift.
- The remaining Python advantage is mostly AI-editing comfort, not runtime
  behavior or architecture.

If those criteria are not met, stop and keep Python.

Suggested commit message if Go wins:

```text
Prepare Go Bakeoff CLI for cutover
```

## Phase 8: Optional Cutover

Do this only after Phase 7 passes.

Possible cutover shape:

- rename `cmd/bakeoff-go` to `cmd/bakeoff`
- update release/build scripts
- update `bin/bakeoff` to exec the Go binary in plugin contexts, or keep it as a
  compatibility launcher during transition
- preserve Python under a clearly named legacy path only if needed for rollback
- update README development instructions
- update plugin wrapper expectations

Do not remove Python in the same commit that first switches the default command.
Keep rollback cheap.

Done criteria:

- `bin/bakeoff --help` invokes the Go path intentionally, not accidentally.
- The full parity harness is still green through the new default entry point.
- `go test ./...`, `pytest`, and `python3 scripts/parity-go.py` pass.
- Rollback instructions are documented in the cutover commit or release notes.

## Risk Notes

- The provider runner is the real conversion risk. Put it early.
- Fake-provider extraction and prompt fixtures are Phase 0 blockers. Without
  them, Phase 2 and Phase 3 cannot prove parity.
- Error and stream discipline must be installed in Phase 1. If every command
  invents its own Cobra error handling or prints directly, the parity harness
  will spend the rest of the project fighting drift.
- Process-tree termination is platform-sensitive. Unix process-group cleanup is
  required during this trial because the team runs on Macs. Keep path handling
  and command invocation portable, but defer Windows Job Object support until
  Windows distribution becomes a real requirement.
- Interrupt handling has two visible surfaces: provider artifacts may say
  `cancelled`, while the CLI exits `130` and prints exactly
  `error: interrupted`. Do not let cleanup errors or cancelled provider results
  collapse this into generic exit `1`.
- Cobra help output will not match argparse byte-for-byte. Treat help parity as
  command/flag/content parity unless a later cutover requires exact formatting.
- Go structs can accidentally drop unknown model output fields. Preserve
  raw/dynamic final JSON until parity is complete.
- Go maps sort keys during JSON encoding. This is useful for artifacts and
  Python-sorted command reports, but it will break insertion-ordered command
  summaries unless `internal/summary` owns the order explicitly.
- Capability probe caching must be explicit and injectable. Package-level
  globals will leak fake PATH and help-text fixtures across tests.
- Prompt text is product behavior. Port prompt templates with byte-for-byte
  tests before changing any wording.
- Manifest fingerprints make tiny artifact changes visible. Use this as a
  feature, not an annoyance.
- If the parity harness becomes full of broad normalizers, Go is drifting rather
  than matching. Tighten the implementation instead.
- The package layout can become over-modular. Command packages may depend on
  domain packages; domain packages must not import command packages.

## Build Order Summary

1. Freeze Python behavior and add black-box parity harness.
2. Scaffold Go command tree.
3. Port work-order validation, IO, and prompt contracts.
4. Implement provider runner spike.
5. Port ledger, artifacts, manifest, verification, and summaries.
6. Port provider argv and scope controls.
7. Port research workflow.
8. Port triage, rerun, review context, show, ls, and doctor.
9. Run full parity and decide whether Go replaces Python.
10. Cut over only after parity is boring.

## Principle

Python is the oracle. Go is the candidate. The trial succeeds only if Go reaches
parity while making the implementation feel simpler, tighter, and more durable.
