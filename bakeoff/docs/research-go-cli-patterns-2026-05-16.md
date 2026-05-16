# Go CLI Patterns Research — for Bakeoff Go Side-By-Side

Date: 2026-05-16
Status: research catalog
Scope: concrete patterns from production Go CLIs we should consider adopting in
the Bakeoff Go implementation (see `go-side-by-side-parity-implementation-plan-2026-05-16.md`).

This is a pattern catalog, not a tutorial. Every pattern is sourced to a real
file in a real repo and mapped to a Bakeoff package the plan already names.
Sources fetched 2026-05-16 from the public default branches.

Patterns are ordered roughly by relevance to the Bakeoff plan. The top five
("must-lift") are flagged.

---

## 1. Thin `main`, fat package (MUST-LIFT)

**Where**
- `cli/cli` — `cmd/gh/main.go` (whole file, ~10 lines): just `os.Exit(int(ghcmd.Main()))`
- `cli/cli` — `internal/ghcmd/cmd.go` (`Main() exitCode`): builds streams, config, root cmd, runs, returns an integer code

**Problem**
`main()` is impossible to test. Anything that calls `os.Exit` inside cannot be
covered, and `defer`red cleanups silently don't run.

**Why it's good**
`Main()` returns an `exitCode` type (`type exitCode int` with named consts:
`exitOK`, `exitError`, `exitCancel`, `exitAuth`, `exitPending`). The actual
`os.Exit` happens in exactly one place (`cmd/gh/main.go`). Endorsed by Uber's
style guide: "exit once".

**Apply to Bakeoff**
- `cmd/bakeoff-go/main.go`: 5 lines, just `os.Exit(int(cli.Main()))`.
- `internal/cli/root.go` exposes `Main() ExitCode` returning the typed codes the
  plan already specifies (0/1/2/3/130). All `defer` and resource cleanup runs
  before `main` returns.

**Cost**
Trivial. No deps.

---

## 2. Typed error sentinels mapped to exit codes (MUST-LIFT)

**Where**
- `cli/cli` — `pkg/cmdutil/errors.go` lines 1–70:
  - `type FlagError struct { err error }` with `Unwrap()`
  - `var SilentError = errors.New("SilentError")` — exit 1 silently
  - `var CancelError = errors.New("CancelError")` — user cancellation
  - `var PendingError = errors.New("PendingError")` — exit code 8 in `gh`
  - `MutuallyExclusive(message string, conditions ...bool) error` helper
  - `NoResultsError` for "expected zero results" with custom message
- `cli/cli` — `internal/ghcmd/cmd.go` (`Main()`): `errors.As(err, &flagError)` and
  `strings.HasPrefix(err.Error(), "unknown command ")` both trigger
  printing usage and `exitError`/`exitCancel`.
- `dagger/dagger` — `cmd/dagger/main.go` end of file: same shape via
  `idtui.ExitError{OriginalCode: N}`; `errors.As(err, &exit)` to pull the code,
  `context.Canceled` / `ErrInterrupted` → exit 2, fallback exit 1.

**Problem**
Bakeoff has FIVE distinct exit codes (0/1/2/3/130). Without a typed-error
discipline, every command becomes peppered with `os.Exit` and the mapping is
invisible to tests.

**Why it's good**
- Commands return `error`; root maps to exit codes via `errors.As`/`errors.Is`.
- `SilentError` lets a command say "I already printed everything; just fail."
- Tests assert on error types (`errors.Is(err, MissingInputError)`) instead of
  scraping exit codes.

**Apply to Bakeoff**
Create `internal/cli/exit.go`:
- `var ErrUsage = errors.New("...")` → exit 2
- `var ErrJudgeDisagreement = errors.New("...")` → exit 3
- `var ErrInterrupted = errors.New("...")` → exit 130
- `type RuntimeError struct { Msg string; Cause error }` → exit 1
- `var ErrSilent = errors.New("silent")` → exit 1, no message
The Phase 1 "preserve Bakeoff exit-code semantics" requirement falls out of this
table naturally.

**Cost**
Tiny. Pure stdlib.

---

## 3. Factory + `NewCmd*` per command (MUST-LIFT)

**Where**
- `cli/cli` — `pkg/cmdutil/factory.go`: `type Factory struct { IOStreams, HttpClient, GitClient, ExtensionManager, Browser, Prompter, Config, BaseRepo, ... }` — bundled, but each field is a lazy func, not eager state.
- `cli/cli` — `pkg/cmd/factory/default.go` (`func New(...)`): wires everything; `f.GitClient = newGitClient(f); f.Remotes = remotesFunc(f); f.BaseRepo = BaseRepoFunc(f.Remotes)`. Explicit dependency comments inline.
- `cli/cli` — `pkg/cmd/repo/view/view.go` (`NewCmdView(f *cmdutil.Factory, runF func(*ViewOptions) error)`): each command exposes a constructor with the factory and an optional `runF` test seam.

**Problem**
Bakeoff's Python `cli.py` is 2,000 lines because every command pulls its deps
from module-globals. Replicating that in Go would produce the same problem
faster (since Go won't let you cheat with imports).

**Why it's good**
- No DI framework; just a struct of constructors.
- `runF` test seam: production passes `nil`, tests pass a capture function. See
  `view.go` line ~50 — `if runF != nil { return runF(&opts) }`.
- Factory lets `gh version` work even when config fails to load (lazy `Config func() (gh.Config, error)`).

**Apply to Bakeoff**
- `internal/cli/factory.go`:
  ```go
  type Factory struct {
      AppVersion string
      IO         *output.Streams
      Now        func() time.Time
      LedgerRoot func() (string, error)
      Runner     func() runner.Runner        // for provider subprocess
      Validator  func() validator.Validator
      // ... lazy funcs for the rest
  }
  ```
- Each subcommand has `NewCmdResearch(f *Factory, runF func(*ResearchOptions) error) *cobra.Command`.
- `runF` exists specifically so the parity harness can inspect resolved options
  without invoking real providers.

**Cost**
Modest discipline cost. No deps. This is the architectural backbone — get this
right in Phase 1.

---

## 4. `Options` struct per command (MUST-LIFT)

**Where**
- `cli/cli` — `pkg/cmd/repo/view/view.go`: `type ViewOptions struct { HttpClient ...; IO ...; BaseRepo ...; Exporter cmdutil.Exporter; RepoArg, Branch string; Web bool }`. Flags `BindVar` against fields of `opts`; `RunE` resolves positional args into `opts.RepoArg` and calls `viewRun(&opts)`.
- `cli/cli` — `pkg/cmd/run/view/view.go`: similar — Options carries `RunID`, `Verbose`, `LogFailed`, plus `Now func() time.Time` for test time control.

**Problem**
`func(cmd *cobra.Command, args []string) error` makes wide signatures and
tightly couples flag parsing to execution. Hard to test.

**Why it's good**
- Cobra layer only fills the struct; business logic takes the struct.
- Tests construct `ViewOptions{...}` literal and call `viewRun(&opts)`
  directly. No flag parsing needed.
- Plan §"Phase 5 — prefer small structs such as `RunOptions`, `RunContext`,
  `ResearchResult`" already calls for this. Pin the discipline.

**Apply to Bakeoff**
Standardize: every command gets a `<Cmd>Options` struct in
`internal/commands/<cmd>/options.go`. Field names match Python kwargs where
possible to keep parity-harness assertions readable.

**Cost**
Zero deps, pure code organization.

---

## 5. `IOStreams` abstraction (MUST-LIFT)

**Where**
- `cli/cli` — `pkg/iostreams/iostreams.go`: holds `In, Out, ErrOut` + TTY
  overrides + color + spinner + pager state. Constructor `iostreams.System()`
  for real, `iostreams.Test()` returns `(io, stdin, stdout, stderr *bytes.Buffer)`.
- `kubernetes/kubectl` — `pkg/cmd/cmd.go` `NewDefaultKubectlCommand`: uses
  `genericiooptions.IOStreams{In, Out, ErrOut}` — same shape, simpler.
- `tailscale/tailscale` — `cmd/tailscale/cli/cli.go` top of file:
  `var Stderr io.Writer = os.Stderr; var Stdout io.Writer = os.Stdout`. The
  minimum viable version: package-level vars that tests override.

**Problem**
Bakeoff already has a `--quiet` mode, JSON output, and heartbeat formatting in
Python `output.py`. Sprinkling `fmt.Println` everywhere in Go would defeat the
parity harness — tests need to capture per-stream output.

**Why it's good**
- Single seam for TTY detection (`s.IsStdoutTTY()`, `s.ColorEnabled()`).
- Tests get buffers; production gets `os.Stdout/os.Stderr`.
- Quiet/JSON modes flip state once on the streams, not per-call.

**Apply to Bakeoff**
The plan already creates `internal/output`. Make it own:
- `type Streams struct { In io.Reader; Out, ErrOut io.Writer; Quiet bool; JSON bool; ... }`
- `func System() *Streams`, `func Test() (*Streams, *bytes.Buffer, *bytes.Buffer)`
- Hide heartbeat formatting, notes, warnings behind methods on `*Streams`.

**Cost**
Internal package, no deps. The `gh` version is heavy (spinner, pager). Bakeoff
should ship the kubectl-shaped minimum.

---

## 6. `heredoc.Doc` for command Long/Example strings

**Where**
- `cli/cli` — `pkg/cmd/root/root.go` line ~70: `Example: heredoc.Doc(\`\n$ gh issue create\n...\`)`
- `cli/cli` — `pkg/cmd/repo/view/view.go` line ~50: `heredoc.Docf` with backtick-escaped flag references.
- Dep: `github.com/MakeNowJust/heredoc` — single tiny package, no transitive deps.

**Problem**
Multi-line Cobra `Long` / `Example` strings written as raw Go raw-strings either
get leading whitespace or are unreadable.

**Why it's good**
Strips common leading indentation; `Docf` does sprintf-style substitution while
keeping backticks readable.

**Apply to Bakeoff**
Use for every non-trivial Long/Example string. Saves the help output from
looking like it was generated by a YAML parser.

**Cost**
One tiny dep. Worth it.

---

## 7. JSON output flag pattern: `--json`, `--jq`, `--template` (MUST-LIFT for Bakeoff JSON modes)

**Where**
- `cli/cli` — `pkg/cmdutil/json_flags.go` (full file):
  - `AddJSONFlags(cmd, &opts.Exporter, fields)` — adds `--json fields`, `--jq`, `--template` in one call.
  - `JSONFlagError` carries the "Specify one or more fields" suggestion list.
  - Field-name completion is registered automatically.
  - Custom `FlagErrorFunc` intercepts "flag needs an argument: --json" and rewrites the message to list available fields.
- `cli/cli` — `pkg/cmd/repo/view/view_test.go` `TestJSONFields`: helper
  `jsonfieldstest.ExpectCommandToSupportJSONFields(t, NewCmdView, [...])` asserts
  every documented field is in fact exportable. Locks the contract.

**Problem**
The plan already requires `--json` for `research`, `triage`, `ls`, `runs verify`,
`doctor`. Implementing this ad-hoc per command guarantees drift and a parity
harness that has to ignore key order.

**Why it's good**
- One mechanism, applied per command: declare the field list once and the
  framework wires flag, error, completion, and a sortable allow-set.
- Sorted, deterministic JSON output → byte-for-byte parity-friendly. The
  `jsonExporter.Write` (search results) explicitly `encoder.SetEscapeHTML(false)`.
- `--jq` and `--template` mean Bakeoff users get scripting-friendly access
  without us writing `gh`-style sub-DSLs.

**Apply to Bakeoff**
- `internal/output/jsonflags.go` mirroring `cmdutil.AddJSONFlags` but
  narrower — Bakeoff JSON outputs are full objects, not selectable field
  subsets. So start with `--json` (boolean) and just emit canonical sorted
  JSON; add `--jq`/`--template` later if useful.
- Steal the test pattern: `jsonparity_test.go` asserts that for each
  `ls`/`research`/`doctor` JSON shape, the documented fields are present.

**Cost**
Stdlib + optional `github.com/cli/go-gh/v2/pkg/jq` (heavier). Probably start
without `--jq`.

---

## 8. Subprocess wrapper: `Command{*exec.Cmd}` with structured error type

**Where**
- `cli/cli` — `git/command.go`: wraps `*exec.Cmd` in `type Command struct { *exec.Cmd }`. `Run()` captures stderr to a buffer if the caller didn't set one, then on error returns `&GitError{ err, Stderr, ExitCode }`.
- `cli/cli` — `git/client.go`: `Client.Command(ctx, args...) (*Command, error)` is the only path; uses `exec.CommandContext`; `RepoDir` is prepended as `-C`; `GitPath` is resolved once and cached behind a mutex.
- `cli/cli` — `internal/run/run.go`: separate `Runnable` interface (`Output() ([]byte, error); Run() error`) with `PrepareCmd` indirection so tests stub subprocess invocation globally.
- `cli/cli` — `git/command.go` end: `CommandModifier` functional options — `WithStdin`, `WithStdout`, `WithStderr`, `WithRepoDir`. Lets one Command be specialized per call site without ballooning the constructor.

**Problem**
Bakeoff `runner.py` is the riskiest port (per the plan's Phase 3 stop-gate). It
needs: streaming stdout/stderr capture, output caps with grace, stderr
truncation, schema-error retry, process-group kill, missing-binary detection,
heartbeats. Raw `exec.Cmd` calls scattered through `internal/runner` will
relearn every mistake.

**Why it's good**
- `errWithExitCode` interface keeps test doubles compatible with real
  `*exec.ExitError`.
- Single capture point for stderr → single source for error formatting (`run.CmdError`).
- The `CommandModifier`/`WithStdin` functional-option set is exactly the
  vocabulary the provider runner needs (custom stdout sink, custom stderr cap,
  separate timeout per call).

**Apply to Bakeoff**
- `internal/runner/command.go`:
  ```go
  type Cmd struct{ *exec.Cmd }
  type CmdError struct{ Args []string; Err error; Stderr []byte; ExitCode int }
  func (c *Cmd) Run(ctx context.Context) error { ... }
  ```
- Functional options: `WithStdoutCap(n int)`, `WithStderrCap(n int)`, `WithHeartbeat(d time.Duration)`, `WithTimeout(d time.Duration)`.
- `internal/runner/runner.go` builds and runs these; provider-specific argv
  builders live in `internal/provider`.

**Cost**
Pure stdlib. The right shape is already proven in `gh`.

---

## 9. `exec.CommandContext` + `Cmd.WaitDelay` for kill-grace

**Where**
- `dagger/dagger` — `cmd/dagger/run.go`: `runCmd.Flags().DurationVar(&waitDelay, "cleanup-timeout", 10*time.Second, "max duration to wait between SIGTERM and SIGKILL on interrupt")`.
- `dagger/dagger` — `cmd/dagger/run.go`: `subCmd := exec.CommandContext(ctx, args[0], args[1:]...)` then `ensureChildProcessesAreKilled(subCmd)` — comment explicitly notes "`go run` lets its child process roam free when you interrupt it, so make sure they all get signalled."

**Problem**
The plan's Phase 3 calls out output-cap grace AND process-group termination as
the wall to hit early. Python's runner uses SIGTERM-then-SIGKILL grace
manually; Go has two overlapping mechanisms (`CommandContext` cancel +
`Cmd.WaitDelay`) plus platform-specific `Setpgid`.

**Why it's good**
- `exec.CommandContext` cancellation is enough for "kill if ctx done."
- `Cmd.WaitDelay` (Go 1.20+) provides the SIGTERM→SIGKILL window without a
  hand-rolled goroutine.
- Bakeoff's *output-cap grace* is a separate concept from process kill-grace
  (kill the process if it keeps writing past the cap). The plan correctly says
  "preserve Bakeoff's existing output-cap grace semantics separately" — keep
  them distinct, don't try to express both through `WaitDelay`.

**Apply to Bakeoff**
- `internal/runner/process_unix.go` with build tag `//go:build !windows`:
  sets `cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}` and provides
  `killGroup(cmd) error` using `syscall.Kill(-pgid, signal)`.
- `internal/runner/process_windows.go` (placeholder for trial):
  minimal `killGroup` calls `cmd.Process.Kill()`. Plan already notes Job Object
  work can wait.
- Heart of the runner: `cmd.WaitDelay = killGrace` and a separate goroutine
  watching output cap.

**Cost**
Stdlib only. Real risk is on Windows; plan already scopes that out for the trial.

---

## 10. `context.Context` propagation via `cmd.Context()` (MUST-LIFT)

**Where**
- `goreleaser/goreleaser` — `cmd/release.go`: `RunE: func(cmd *cobra.Command, _ []string) error { return releaseProject(cmd.Context(), root.opts) }`. Every command takes ctx from Cobra.
- `dagger/dagger` — `cmd/dagger/main.go`: `ctx, stop := signal.NotifyContext(ctx, os.Interrupt); rootCmd.ExecuteContext(ctx)`. Cancellation flows from signal to ctx to every subprocess via `exec.CommandContext(ctx, ...)`.
- `cobra` itself supports `cmd.Context()` via `ExecuteContext(ctx)` (see `command.go` ~line 700 of indexed content).

**Problem**
Python's runner manages cancellation via thread-locals and signal handlers.
Porting that 1:1 to Go is a rewrite invitation. The idiomatic answer: a single
ctx flows from `signal.NotifyContext` → root command → each handler → each
`exec.CommandContext`.

**Why it's good**
- One mechanism cancels every subprocess, every HTTP call, every long loop.
- `signal.NotifyContext` (Go 1.16+) is the entire signal handler — three lines
  replace the kubectl `interrupt.Handler` machinery for the simple case.
- Tests pass `context.Background()` or `context.WithTimeout(...)`.

**Apply to Bakeoff**
`internal/cli/root.go`:
```go
func Main() ExitCode {
    ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
    defer stop()
    err := root.ExecuteContext(ctx)
    return mapErr(err)  // returns 130 if ctx.Err() == Canceled
}
```
Every package signature: `func Foo(ctx context.Context, opts FooOptions) error`.

**Cost**
Zero. Stdlib.

---

## 11. `signal.NotifyContext` for the single-signal common case

**Where**
- `dagger/dagger` — `cmd/dagger/main.go`:
  ```go
  ctx := context.Background()
  ctx, stop := signal.NotifyContext(ctx, os.Interrupt)
  ```
- Compare with the heavier `kubernetes/kubectl/pkg/util/interrupt/interrupt.go`
  which uses an explicit `Handler` struct with `notify []func()`, `final func(os.Signal)`, `sync.Once`. Useful when nesting critical sections (e.g., kubectl's `port-forward` cleanup). Bakeoff doesn't have that need.

**Problem**
Bakeoff's only signal requirement is "Ctrl-C kills the run cleanly and writes
exit 130." kubectl-style handler chains are overkill.

**Why it's good**
- Three lines of stdlib.
- Pairs perfectly with `exec.CommandContext` (pattern #9).
- `defer stop()` releases the signal handler before main exits (avoids the
  goroutine leak that bites people).

**Apply to Bakeoff**
Use `signal.NotifyContext` directly in `Main()`. If a specific command later
needs nested cleanup, copy kubectl's `interrupt.Handler` — but not preemptively.

**Cost**
None. Stdlib.

---

## 12. `embed.FS` for prompts and templates

**Where**
- `goreleaser/goreleaser` — `cmd/init.go` lines 50–70: `static.GoExampleConfig`, `static.RustExampleConfig` etc. are `//go:embed`'d byte slices selected by a switch on `--language`.
- General Go pattern: `//go:embed prompts/*.tmpl` at package level → `var promptFS embed.FS`.

**Problem**
Bakeoff prompts are *product behavior* — the plan requires byte-for-byte parity
with Python's prompt text. If those are Go raw-string literals, every edit is a
diff in source code. If they're loose files at runtime, the single-binary
guarantee dies.

**Why it's good**
- `embed.FS` keeps prompt text in real files (good for diffs, code review, and
  parity fixtures) but ships them inside the binary.
- Same machinery for review templates, init templates, doctor probes.
- Parity harness can compare embedded bytes against the Python templates
  directly.

**Apply to Bakeoff**
- `internal/prompt/templates/` directory of `.tmpl` files.
- `internal/prompt/embed.go`:
  ```go
  //go:embed templates/*.tmpl
  var templatesFS embed.FS
  func Worker() string { b, _ := templatesFS.ReadFile("templates/worker.tmpl"); return string(b) }
  ```
- Same pattern for `internal/commands/initcmd/templates/`.

**Cost**
Pure stdlib. Big win in code-review readability.

---

## 13. Build info injection via `ldflags` + `debug.ReadBuildInfo` fallback

**Where**
- `cli/cli` — `internal/build/build.go`:
  ```go
  var Version = "DEV"
  var Date = ""  // YYYY-MM-DD
  func init() {
      if Version == "DEV" {
          if info, ok := debug.ReadBuildInfo(); ok && info.Main.Version != "(devel)" {
              Version = info.Main.Version
          }
      }
  }
  ```
- `charmbracelet/gum` — `main.go` top: `Version`, `CommitSHA` as ldflags vars,
  fallback to `debug.ReadBuildInfo().Main.Version`.
- `cli/cli` — `pkg/cmd/version/version.go`: `Format(version, buildDate)` builds the
  user-facing string; the command itself is `Hidden: true` because the version
  is also exposed via the `--version` flag and `versionInfo` annotation.

**Problem**
Bakeoff needs a version for `doctor`, for ledger `meta.json`, and for users.
Hardcoding it is wrong; reading a file at runtime breaks the single-binary
story.

**Why it's good**
- Real releases get a real `-ldflags="-X .../build.Version=v0.5.0 -X .../build.Date=2026-05-16"`.
- `go install` users get an automatic version from `debug.ReadBuildInfo()` (the
  module version embedded by the Go toolchain).
- `go run ./cmd/bakeoff-go` from a checkout falls back to `"DEV"`.

**Apply to Bakeoff**
`internal/build/build.go` with `Version`, `Date`, optionally `Commit`. The
Makefile/release script sets ldflags. `bakeoff doctor` reads from this. Ledger
`meta.json` includes it.

**Cost**
None. Stdlib + Makefile tweak.

---

## 14. Hidden, registered version command + `--version` annotation

**Where**
- `cli/cli` — `pkg/cmd/version/version.go`:
  ```go
  cmd := &cobra.Command{Use: "version", Hidden: true, RunE: ...}
  ```
- `cli/cli` — `pkg/cmd/root/root.go`:
  ```go
  Annotations: map[string]string{"versionInfo": versionCmd.Format(version, buildDate)},
  ```
- Goreleaser uses Cobra's built-in `cmd.Version` + `cmd.SetVersionTemplate("{{.Version}}")`.

**Problem**
Two surfaces want the version: `bakeoff --version` and `bakeoff version`. They
must agree. Bakeoff doctor also wants the version programmatically.

**Why it's good**
- One format function feeds both surfaces.
- Hiding the subcommand keeps `--help` clean while preserving discoverability.

**Apply to Bakeoff**
Same shape. Bakeoff doctor reads `build.Version` directly; the user-facing
format function lives once.

**Cost**
Trivial.

---

## 15. Cobra `SilenceUsage` / `SilenceErrors` to control message duplication

**Where**
- `goreleaser/goreleaser` — `cmd/release.go`: `SilenceUsage: true, SilenceErrors: true` on every command. The root then has a `fang.WithErrorHandler(errorHandler)` that prints the error once with structured fields.
- `charmbracelet/glow` — `main.go`: `SilenceErrors: false, SilenceUsage: true` — show usage suppression but print errors via Cobra.
- `dagger/dagger` — `cmd/dagger/run.go`: `SilenceUsage: true` so a runtime error doesn't drown the user in a usage screen.

**Problem**
Cobra's default is to print the usage *and* the error for any RunE failure.
That's wrong for runtime errors (no one wants the usage screen because their
provider timed out). It's right for flag errors.

**Why it's good**
- `SilenceUsage: true` everywhere; the root command's error handler decides
  whether to print usage (only for `FlagError`).
- The `gh` pattern in `ghcmd.Main`: `if errors.As(err, &flagError) || strings.HasPrefix(err.Error(), "unknown command ") { fmt.Fprintln(out, cmd.UsageString()) }`.

**Apply to Bakeoff**
Every subcommand: `SilenceUsage: true, SilenceErrors: true`. Root handles
formatting based on error type.

**Cost**
One line per command.

---

## 16. `cobra.NoFileCompletions` + per-flag completion registration

**Where**
- `goreleaser/goreleaser` — `cmd/release.go`:
  - `ValidArgsFunction: cobra.NoFileCompletions` — tells the shell not to complete file paths for positional args.
  - `cmd.MarkFlagFilename("config", "yaml", "yml")` — file completion scoped to extensions.
  - `cmd.MarkFlagFilename("release-notes", "md", "mkd", "markdown")`.
- `cli/cli` — `pkg/cmdutil/flags.go` `StringEnumFlag`: registers completion of the allowed enum values automatically.

**Problem**
Cobra completions exist but are easy to under-use; users complaint #1 is "tab
doesn't work."

**Why it's good**
- One-line additions per flag. Bakeoff already plans completion support.
- `MarkFlagFilename` with extensions means `bakeoff validate <Tab>` only
  surfaces `.json`/`.work-order.json` files.

**Apply to Bakeoff**
- `bakeoff validate`: `MarkFlagFilename` not applicable for positional, but a
  custom completion can suggest work-order files in CWD.
- `bakeoff show <run-id>`: register `ValidArgsFunction` that lists ledger run
  ids.
- `bakeoff init <facet>`: `cobra.OnlyValidArgs` with `ValidArgs: []string{"gather","compare","analyze","review"}`.

**Cost**
Marginal. Pure cobra surface.

---

## 17. Table-driven tests + `*Options` test seam

**Where**
- `cli/cli` — `pkg/cmd/repo/view/view_test.go` `TestNewCmdView`:
  ```go
  tests := []struct{ name string; cli string; wants ViewOptions; wantsErr bool }{...}
  for _, tt := range tests {
      t.Run(tt.name, func(t *testing.T) {
          io, _, _, _ := iostreams.Test()
          f := &cmdutil.Factory{IOStreams: io}
          argv, _ := shlex.Split(tt.cli)
          var gotOpts *ViewOptions
          cmd := NewCmdView(f, func(opts *ViewOptions) error { gotOpts = opts; return nil })
          cmd.SetArgs(argv)
          cmd.Execute()
          assert.Equal(t, tt.wants.RepoArg, gotOpts.RepoArg)
      })
  }
  ```
- The trick: the test passes a `runF` capture that records what `Options`
  Cobra produced, without ever running the real command logic.

**Problem**
Testing "flag X with value Y produces Options Z" without spinning up the whole
command is the bread and butter of CLI testing. The parity harness shells out;
unit tests must not.

**Why it's good**
- Tests run in microseconds.
- One pattern per command — `TestNewCmd<Foo>` for arg parsing, `Test<foo>Run`
  for business logic with an `Options{...}` literal.

**Apply to Bakeoff**
Mandatory pattern for every command in `internal/commands/<cmd>/<cmd>_test.go`.
The parity harness then only covers behavior; flag parsing is fully covered by
unit tests.

**Cost**
Zero (stdlib + `assert` if desired).

---

## 18. Golden-file testing pattern (with normalization)

**Where**
- Google Go Style guide (indexed): `golden := readFile(t, "testdata/golden-result.txt")`. Standard Go convention.
- The plan already calls for golden parity fixtures under `tests/parity/`.

**Problem**
Bakeoff outputs JSON, markdown, manifest, decision, report — bytes that must
match across runs. Inline `want := "..."` literals in tests become unreadable.

**Why it's good**
- Diffs are reviewable as file diffs.
- A `-update` flag (`go test ./... -update`) regenerates goldens. Convention:
  ```go
  var update = flag.Bool("update", false, "update golden files")
  if *update { os.WriteFile(goldenPath, got, 0644) }
  ```
- Pairs with the parity-harness normalization rules already in the plan
  (run id, timestamps, paths).

**Apply to Bakeoff**
- `internal/prompt/testdata/worker.tmpl.golden`
- `internal/decision/testdata/compare_winner.golden.json`
- `internal/report/testdata/research.golden.md`
- A shared `internal/parity/golden.go` helper for read/compare/update.

**Cost**
Stdlib only.

---

## 19. Cobra command groups for help organization

**Where**
- `dagger/dagger` — `cmd/dagger/main.go`: `execGroup = &cobra.Group{ID: "exec", Title: "Execution Commands"}` and per-command `GroupID: execGroup.ID`.
- `cli/cli` — `pkg/cmd/root/root.go`: comments organize child commands into "Core", "GitHub Actions", "Additional", "Targeted" sections — explicit groups via `AddGroup(...)`.

**Problem**
Bakeoff has ~10 subcommands of mixed weight (research is the headliner; doctor
is utility). Cobra's default alphabetical help screen buries the important
ones.

**Why it's good**
- Help screen segments by intent: "Workflow Commands: init, validate, research,
  triage, rerun" / "Inspection: ls, show, runs verify" / "Utility: doctor, version".
- Same mechanism Bakeoff Python uses informally in the README.

**Apply to Bakeoff**
Set `Groups` in `root.go`; every command sets `GroupID`. Plan §"do ensure
command names, flags, defaults, and aliases match Python" can extend to group
labels matching the README sections.

**Cost**
A few lines per command.

---

## 20. Avoid Viper for Bakeoff (anti-pattern note)

**Where**
- `charmbracelet/glow` — `main.go`: uses Viper, `viper.BindPFlag` for every flag. But glow has a config file, glow needs precedence (env → file → flag). Bakeoff *does not*.
- The plan explicitly says "Avoid Viper, logging frameworks, ORM layers, rich
  terminal dependencies, and config frameworks."

**Problem**
The temptation is real. Viper's "config layering" is genuinely useful for tools
with persistent user config. Adopting it for Bakeoff (which has none) imports
~15 transitive deps and a global singleton that breaks tests.

**Why it's correct to skip**
- Bakeoff has *zero* user-config files. Env vars are flat; flags are flat; defaults
  are flat. A 30-line `internal/config/env.go` with explicit `os.Getenv` calls
  covers everything.
- If Bakeoff ever needs config files later, swap in Viper or roll a 50-line
  YAML loader. Not now.

**Apply to Bakeoff**
Confirmed direction in the plan. Maintain discipline; reject the first PR that
adds Viper.

**Cost**
Negative — saves dep weight.

---

## 21. Subprocess test stub via package-level indirection

**Where**
- `cli/cli` — `internal/run/run.go`:
  ```go
  var PrepareCmd = func(cmd *exec.Cmd) Runnable { return &cmdWithStderr{cmd} }
  ```
  Production replaces nothing; tests do `oldPrepareCmd := run.PrepareCmd; run.PrepareCmd = func(c *exec.Cmd) run.Runnable { return fakeRunnable{...} }; defer func(){ run.PrepareCmd = oldPrepareCmd }()`.

**Problem**
Bakeoff parity tests need to run *fake* providers (Python uses deterministic
shell scripts under `tests/`). Go subprocess tests can do the same — but unit
tests for `internal/runner` need an in-process stub.

**Why it's good**
- One global indirection point.
- Tests don't need a fake-provider binary; they substitute a struct that
  implements `Runnable`.
- Matches the Python pattern of `runner._run = stub`.

**Apply to Bakeoff**
- `internal/runner/runner.go` exposes `var Prepare = realPrepare` (function var).
- Test files swap it for `runnerStub` per test.
- The Phase 3 parity-harness spike can use this to test status vocabulary
  (`output_capped`, `salvaged`, `format_error`, etc.) without spawning shells.

**Cost**
None. Stdlib pattern.

---

## 22. `cobra.SetInterspersed(false)` for "execute subcommand" semantics

**Where**
- `dagger/dagger` — `cmd/dagger/run.go`:
  ```go
  runCmd.Flags().SetInterspersed(false)
  // don't require -- to disambiguate subcommand flags
  ```

**Problem**
`bakeoff research --provider claude --base main -- ...` — once Bakeoff grows a
command that passes-through to provider CLIs, flags after the positional
shouldn't be eaten by Cobra.

**Why it's good**
One line turns off flag-parsing after the first positional. Users don't need
`--`.

**Apply to Bakeoff**
If `rerun` or `research` ever forwards args to a provider CLI, set this flag.
Probably not needed for parity but cheap to keep in mind.

**Cost**
Trivial.

---

## 23. Avoid Bubble Tea / Lipgloss for non-interactive Bakeoff

**Where**
- `charmbracelet/gum/main.go` uses Bubble Tea heavily (`lipgloss.SetColorProfile`, full TUI).
- Bakeoff has only heartbeat output + reports. Not a TUI.

**Problem**
Tempting to use lipgloss for "pretty" colored output. But Bubble Tea + lipgloss
pulls termenv, isatty, several reflow packages — and breaks every parity
snapshot the moment a TTY is detected.

**Why it's correct to skip**
- Bakeoff is non-interactive. Color can be done with raw ANSI escapes
  controlled by `IOStreams.ColorEnabled()`.
- The plan explicitly excludes "rich terminal dependencies."

**Apply to Bakeoff**
Skip. If color is needed later, do what kubectl does (none) or write 30 lines
in `internal/output/color.go`.

**Cost**
Saves transitive deps.

---

# Summary table

| # | Pattern | Bakeoff phase | Lift now? |
|---|---|---|---|
| 1 | Thin main, fat package | Phase 1 | YES |
| 2 | Typed error sentinels | Phase 1 | YES |
| 3 | Factory + NewCmd | Phase 1 | YES |
| 4 | Options struct | Phase 1 | YES |
| 5 | IOStreams | Phase 1–2 | YES |
| 6 | heredoc.Doc | Phase 1 | small |
| 7 | JSON flags pattern | Phase 5–6 | partial |
| 8 | Command wrapper + CmdError | Phase 3 | YES |
| 9 | exec.CommandContext + WaitDelay | Phase 3 | YES |
| 10 | context.Context propagation | Phase 1 onward | YES |
| 11 | signal.NotifyContext | Phase 1 | YES |
| 12 | embed.FS | Phase 2 | YES |
| 13 | Build info ldflags + ReadBuildInfo | Phase 1 | YES |
| 14 | Hidden version command + annotation | Phase 1 | small |
| 15 | SilenceUsage/SilenceErrors | Phase 1 | YES |
| 16 | Completion: NoFileCompletions, MarkFlagFilename | Phase 1 | small |
| 17 | Table-driven Options test seam | Phase 1 onward | YES |
| 18 | Golden-file testing | Phase 0–8 | YES |
| 19 | Cobra command groups | Phase 1 | small |
| 20 | (Skip) Viper | — | NO (skip) |
| 21 | Subprocess test stub via global func var | Phase 3 | YES |
| 22 | SetInterspersed(false) | Phase 5+ | maybe |
| 23 | (Skip) Bubble Tea / Lipgloss | — | NO (skip) |

# Plan-shape observations

Three places where this research suggests the current plan is approximately
right; one place where it might be wrong.

1. **Plan is right** to ban Viper, ORMs, logging frameworks, rich TUI deps.
   Every CLI we looked at that mattered (gh, dagger, goreleaser, kubectl)
   keeps the dep list tight; the ones that don't (glow) accept it as a tradeoff
   for genuine config-file complexity Bakeoff doesn't have.

2. **Plan is right** to put the runner spike in Phase 3 ahead of the research
   workflow. Every production runner we examined (gh's git client, dagger's
   run command) treats subprocess management as a separate package with its
   own error type. The plan's package decomposition matches.

3. **Plan is right** to keep `final_json` as `map[string]any` / `json.RawMessage`.
   gh's JSON Exporter pattern (#7) uses a fielded allow-set on top of arbitrary
   maps; the underlying object is preserved.

4. **Possible plan gap**: The plan says "Use Cobra command objects, but keep
   command handlers in internal packages" but doesn't pin the `Factory + NewCmd
   + Options + runF` pattern as the *enforcement mechanism*. Without that
   discipline written down, the first Phase-5 contributor will inline option
   parsing back into `RunE` and the parity tests will have to invoke flags
   instead of options. Recommend adding to the plan: "Every subcommand exposes
   `NewCmd<Name>(f *cli.Factory, runF func(*<Name>Options) error) *cobra.Command`."
   This pattern is the difference between `gh` (testable) and the old
   `kubectl/cmd` codebase (notoriously hard to unit-test).

# Sources

- `cli/cli` (GitHub `gh`) — trunk, fetched 2026-05-16:
  - `cmd/gh/main.go`
  - `internal/ghcmd/cmd.go`
  - `internal/run/run.go`
  - `internal/build/build.go`
  - `pkg/cmd/root/root.go`
  - `pkg/cmd/factory/default.go`
  - `pkg/cmd/version/version.go`
  - `pkg/cmd/repo/view/view.go` + `view_test.go`
  - `pkg/cmd/run/view/view.go`
  - `pkg/cmdutil/factory.go`, `errors.go`, `flags.go`, `json_flags.go`, `legacy.go`
  - `pkg/iostreams/iostreams.go`
  - `git/client.go`, `git/command.go`
- `goreleaser/goreleaser` v2 main, fetched 2026-05-16:
  - `cmd/root.go`, `cmd/release.go`, `cmd/init.go`
- `dagger/dagger` main, fetched 2026-05-16:
  - `cmd/dagger/main.go`, `cmd/dagger/run.go`
- `kubernetes/kubectl` master, fetched 2026-05-16:
  - `pkg/cmd/cmd.go`, `pkg/cmd/run/run.go`, `pkg/util/interrupt/interrupt.go`
- `tailscale/tailscale` main, fetched 2026-05-16:
  - `cmd/tailscale/tailscale.go`, `cmd/tailscale/cli/cli.go`
- `charmbracelet/gum` main, fetched 2026-05-16:
  - `main.go`
- `charmbracelet/glow` master, fetched 2026-05-16:
  - `main.go`
- `gohugoio/hugo` master, fetched 2026-05-16:
  - `commands/hugobuilder.go` (for sync/long-running-build patterns)
- `spf13/cobra` main, fetched 2026-05-16:
  - `command.go` (for command construction internals)
- Reference: Google Go Style Decisions and Uber Go Style Guide (indexed
  general guidance on `main`/`run` separation and table-driven test idioms).
