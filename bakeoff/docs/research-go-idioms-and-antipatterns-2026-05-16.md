# Go Idioms and Antipatterns — Curated Reference

Date: 2026-05-16
Scope: opinionated coding-standards reference for the Go side-by-side rewrite of
the Bakeoff CLI. Companion to
`docs/go-side-by-side-parity-implementation-plan-2026-05-16.md`. Intended to
prevent re-litigation of routine style decisions during implementation.

Sources cited inline. Primary authorities, in order of weight:

- Google Go Style Guide — Guide / Decisions / Best Practices
  (https://google.github.io/styleguide/go/{guide,decisions,best-practices})
- Go Code Review Comments (https://go.dev/wiki/CodeReviewComments)
- Effective Go (https://go.dev/doc/effective_go)
- Go Proverbs (https://go-proverbs.github.io/)
- Dave Cheney — Practical Go and "Don't just check errors, handle them
  gracefully" (dave.cheney.net)
- Uber Go Style Guide (github.com/uber-go/guide)

---

## Patterns To Follow

### P1 — Project layout: `cmd/<binary>` + `internal/...`, skip `pkg/`

```text
go.mod
cmd/bakeoff-go/main.go          // package main, ~30 lines, parses argv,
                                 // wires deps, calls cli.Run(ctx)
internal/cli/root.go            // cobra root + subcommand wiring
internal/commands/researchcmd/  // one package per subcommand
internal/runner/                // provider subprocess lifecycle
internal/ledger/                // run ids, paths, latest resolution
```

**Why.** The Go toolchain enforces `internal/` visibility: a package at
`<root>/internal/foo` can only be imported by code under `<root>/...`. That
gives you a real, compiler-enforced API boundary without exporting anything
(Practical Go §5.1.3). `cmd/<name>` is the conventional location for binary
entrypoints and is the layout used by `gh`, `kubectl`, `hugo`, `goreleaser`.

Skip `pkg/` unless you are publishing a library people will `go get` outside
this repository. For Bakeoff the answer is no — everything is internal to the
CLI. The Bakeoff plan correctly omits `pkg/`. Keep `package main` small
(Practical Go §5.2): the binary stub just calls into `internal/cli`.

**Citations.** Practical Go §5.1 "Consider fewer, larger packages", §5.1.3
"Use internal packages to reduce your public API surface", §5.2 "Keep package
main as small as possible".

---

### P2 — Package naming: short, singular, lowercase, no underscores

```go
// Good:
package ledger   // not "ledgers", not "ledgerpkg", not "ledger_util"
package runner
package workorder

// Caller reads naturally:
l := ledger.New(root)
mf, err := manifest.Load(path)
```

**Why.** Package names are the noun callers see at every callsite. Google's
guide: "concise and use only lowercase letters and numbers... should not have
underscores" (Decisions §Naming/Package names). Effective Go: "By convention,
packages are given lower case, single-word names; there should be no need for
underscores or mixedCaps." Pick the name so the *callsite* reads well —
`bytes.Buffer`, `http.Client`, not `bytesutil.Buffer`.

Avoid names that shadow common locals (`count`, `time`, `path`). The Bakeoff
package map already follows this — `output`, `hints`, `workorder`, `runner` are
all good. Do not rename them to `outputs` or `hintspkg`.

**Citations.** Google Go Decisions §Package names; Effective Go §Names; Go Code
Review Comments §Package Names.

---

### P3 — Error handling: wrap with `%w`, sentinels via `errors.Is`, types via `errors.As`

```go
// Sentinel — for stable, documented "this happened" signals.
var ErrTimeout = errors.New("runner: provider timed out")

// Custom type — when callers need structured data off the error.
type SchemaError struct {
    Path   string
    Field  string
    Reason string
}
func (e *SchemaError) Error() string {
    return fmt.Sprintf("schema %s: %s: %s", e.Path, e.Field, e.Reason)
}

// Wrap with %w to preserve the chain.
if err := json.Unmarshal(buf, &v); err != nil {
    return fmt.Errorf("decode work order %s: %w", path, err)
}

// Inspect:
if errors.Is(err, ErrTimeout) { ... }
var se *SchemaError
if errors.As(err, &se) { log.Warn("bad schema", "field", se.Field) }
```

**Why.** `%w` makes the wrapped error part of a chain that `errors.Is` and
`errors.As` can walk; `%v` flattens to a string and breaks that. Sentinels are
the right tool for stable, comparable signals (`io.EOF` style); error types are
the right tool when callers need structured fields. Both are vastly preferable
to string-matching `err.Error()`, which Dave Cheney calls a code smell.
Per Cheney: an error string is "for humans, not code."

Place `%w` at the end of the format string for newest→oldest readability
(Google Best Practices §Placement of %w).

**Citations.** Cheney, "Don't just check errors, handle them gracefully"
§Sentinel errors / Error types; Google Best Practices §Adding information to
errors, §Placement of %w; Go Proverbs "Errors are values."

---

### P4 — `context.Context` as the first parameter; never in a struct

```go
// Good:
func (r *Runner) Run(ctx context.Context, p Plan) (Result, error) { ... }

// Bad — stores context in struct, ages poorly, defeats cancellation:
type Runner struct {
    ctx context.Context  // NO
}
```

**Why.** Contexts carry deadlines, cancellation, and request-scoped values
across API boundaries. The convention is universal: first parameter, named
`ctx`. Don't add a `Context` member to a struct — pass it through method calls
instead (Go Code Review Comments §Contexts). For a CLI subprocess runner this
matters concretely: `exec.CommandContext(ctx, ...)` kills the child when `ctx`
is cancelled, which is exactly the deadline behavior Bakeoff's runner needs.

If you don't have one, use `context.Background()` at the top of `main` and
`signal.NotifyContext` to wire SIGINT/SIGTERM into it (see P12).

**Citations.** Go Code Review Comments §Contexts; Google Decisions §Contexts.

---

### P5 — Accept interfaces, return structs; define interfaces at the consumer

```go
// internal/runner/runner.go — producer returns a concrete *Runner.
func New(opts Options) *Runner { ... }
func (r *Runner) Run(ctx context.Context, p Plan) (Result, error) { ... }

// internal/commands/researchcmd/research.go — consumer defines its narrow seam.
type providerRunner interface {
    Run(ctx context.Context, p runner.Plan) (runner.Result, error)
}

func runResearch(ctx context.Context, pr providerRunner, ...) error { ... }
```

**Why.** Returning a concrete type lets the producer add methods later without
breaking callers. Defining the interface at the consumer keeps the interface
small (only the methods *that* caller uses), and removes the "interface defined
for mocking" antipattern. Both Google and the Code Review wiki are explicit:
"interfaces generally belong in the package that uses them, not the package
that implements them." Bigger interfaces are weaker abstractions (Go Proverb).

Do not write an interface until there are two implementations or a test seam
that cannot be served by a function parameter. The Bakeoff plan already calls
this out in Phase 5; honor it across all packages.

**Citations.** Go Code Review Comments §Interfaces; Google Decisions §Interfaces;
Google Best Practices §Interface ownership and visibility; Go Proverbs "The
bigger the interface, the weaker the abstraction."

---

### P6 — Concurrency: own the goroutine lifetime; prefer `errgroup`

```go
import "golang.org/x/sync/errgroup"

func (r *Runner) capture(ctx context.Context, cmd *exec.Cmd) (out, errOut []byte, err error) {
    g, ctx := errgroup.WithContext(ctx)
    var stdout, stderr bytes.Buffer

    g.Go(func() error { return copyCapped(ctx, &stdout, cmd.StdoutPipe) })
    g.Go(func() error { return copyCapped(ctx, &stderr, cmd.StderrPipe) })

    if err := g.Wait(); err != nil { return nil, nil, err }
    return stdout.Bytes(), stderr.Bytes(), nil
}
```

**Why.** Every goroutine must have a known stop condition and a way for the
caller to block until it's done (Uber §Don't fire-and-forget goroutines; Code
Review §Goroutine Lifetimes). `errgroup` gives you both: cancellation
propagates via the derived `ctx`, and `Wait` blocks until all goroutines exit
and returns the first error. For Bakeoff's provider runner, which fans out
stdout/stderr capture + heartbeat + timeout, `errgroup` is the right primitive.

Specify channel direction (`<-chan T`, `chan<- T`) at boundaries; the compiler
catches misuse and the type documents ownership (Google Best Practices
§Channel direction). The sender owns close; receivers never close.

**Citations.** Code Review §Goroutine Lifetimes; Uber §Don't fire-and-forget
goroutines; Google Best Practices §Channel direction; Go Proverbs "Channels
orchestrate; mutexes serialize."

---

### P7 — Testing: table tests, `t.Parallel`, `testdata/`, golden files

```go
func TestExtractFinalJSON(t *testing.T) {
    cases := []struct {
        name    string
        in      string
        want    string
        wantErr bool
    }{
        {"simple", "<final_json>{\"k\":1}</final_json>", `{"k":1}`, false},
        {"trailing", "noise <final_json>{}</final_json> tail", `{}`, false},
        {"missing", "no marker", "", true},
    }
    for _, tc := range cases {
        tc := tc  // capture for t.Parallel
        t.Run(tc.name, func(t *testing.T) {
            t.Parallel()
            got, err := ExtractFinalJSON(tc.in)
            if (err != nil) != tc.wantErr { t.Fatalf("err = %v", err) }
            if got != tc.want { t.Errorf("got %q, want %q", got, tc.want) }
        })
    }
}
```

For larger fixtures, put bytes under `testdata/` (the Go tool ignores it) and
use `-update` flag conventions for golden files. Stick with the standard
`testing` package; reach for `cmp.Diff` (go-cmp) only when you need structured
diffs.

**Why.** Table tests scale; `t.Parallel` finds data races; `testdata/` is a
toolchain-blessed convention. Don't reach for `testify` by default — it adds
a dependency for `assert.Equal` you can write with three lines of stdlib, and
its `assert.*` (vs `require.*`) split is a common source of misleading failure
output.

**Citations.** Google Decisions §Test structure / Table-driven tests; Uber
§Test Tables / Parallel Tests.

---

### P8 — Dependency injection via constructors and functional options

```go
type Options struct {
    Logger     *slog.Logger
    Now        func() time.Time
    HTTPClient *http.Client
}

type Option func(*Options)

func WithLogger(l *slog.Logger) Option     { return func(o *Options) { o.Logger = l } }
func WithClock(now func() time.Time) Option { return func(o *Options) { o.Now = now } }

func New(root string, opts ...Option) *Ledger {
    o := Options{Logger: slog.Default(), Now: time.Now}
    for _, fn := range opts { fn(&o) }
    return &Ledger{root: root, opts: o}
}
```

For 1–2 required + 0–2 optional args, plain constructor parameters are fine.
Reach for functional options when you have 3+ optional knobs or expect the set
to grow. For dense argument lists, an `Options` struct passed as the last arg
is the Google-style alternative.

**Why.** No framework needed; testing seams come for free (`WithClock` lets you
freeze time in tests); APIs grow without breaking callers (Uber §Functional
Options; Google Best Practices §Option structure).

**Citations.** Uber §Functional Options; Google Best Practices §Option
structure / Function argument lists.

---

### P9 — Logging: `log/slog`, structured, key-value

```go
import "log/slog"

logger := slog.New(slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{
    Level: slog.LevelInfo,
}))

logger.Info("runner: start", "run_id", runID, "provider", "claude")
logger.Warn("runner: stdout cap exceeded", "cap_bytes", cap, "kept_bytes", n)
```

Use `slog` (stdlib since 1.21). Reserve `Error` for genuine errors; the runner
should log status transitions at `Info` and noise at `Debug`. Inject the
logger via the Options pattern (P8) so tests can swap it for
`slog.New(slog.NewTextHandler(io.Discard, ...))`.

**Why.** Structured logs are queryable; printf logs are not. `slog` is
stdlib, so no dependency. Keep keys snake_case and stable — they become
the de facto event schema.

**Citations.** stdlib `log/slog` package docs; Google Best Practices §Logging
errors (Cheney guidance on log-or-return: see A11).

---

### P10 — Configuration precedence: defaults → file → env → flags

```go
// Highest precedence wins, applied last.
cfg := defaultConfig()                       // 1. compiled-in defaults
if path := configPath(); path != "" {        // 2. file (if present)
    if err := loadFile(path, &cfg); err != nil { return err }
}
applyEnv(&cfg)                               // 3. BAKEOFF_* environment vars
if err := bindFlags(cmd.Flags(), &cfg); err != nil { return err }  // 4. CLI flags
```

**Why.** This precedence is the convention users expect (12-factor, kubectl,
docker, gh all behave this way). Implement it without Viper — the standard
`flag` (or `cobra.Flags()`), `os.Getenv`, and `encoding/json` handle this with
~30 lines. Flags must only be defined in `package main` or the command package
(Google Decisions §Flags); never let an imported library register flags as a
side effect.

The Bakeoff plan explicitly says "no config files" for the trial — so for now
this collapses to defaults + env + flags. Keep the order ready for when a
config file is added.

**Citations.** Google Decisions §Flags; 12-factor.net.

---

### P11 — Build/version metadata via `-ldflags`

```go
// internal/buildinfo/buildinfo.go
package buildinfo

var (
    Version = "dev"     // set via -ldflags
    Commit  = "unknown"
    Date    = "unknown"
)
```

```sh
# In build script / Makefile:
go build -trimpath \
  -ldflags "-s -w \
    -X github.com/mstefanko/.../internal/buildinfo.Version=${VERSION} \
    -X github.com/mstefanko/.../internal/buildinfo.Commit=$(git rev-parse --short HEAD) \
    -X github.com/mstefanko/.../internal/buildinfo.Date=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -o bin/bakeoff-go ./cmd/bakeoff-go
```

**Why.** `-trimpath` makes builds reproducible; `-s -w` strips the symbol
table and DWARF; `-X` injects values at link time without source edits. The
variables must be package-level strings (not constants) and not initialized
via expressions. `runtime/debug.ReadBuildInfo()` covers module-level VCS info
on Go 1.18+ but `-X` remains the standard way to inject a release version.

**Citations.** Go cmd/link docs `-X`; cmd/go `-trimpath`; widespread practice
(gum, goreleaser, gh).

---

### P12 — `embed.FS` for static assets; `signal.NotifyContext` for shutdown

```go
//go:embed templates/*.tmpl prompts/*.txt
var assets embed.FS

func loadPrompt(name string) (string, error) {
    b, err := assets.ReadFile("prompts/" + name + ".txt")
    if err != nil { return "", fmt.Errorf("load prompt %s: %w", name, err) }
    return string(b), nil
}

func main() {
    ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
    defer stop()
    if err := cli.Run(ctx, os.Args[1:]); err != nil {
        fmt.Fprintln(os.Stderr, "bakeoff:", err)
        os.Exit(exitCodeFor(err))
    }
}
```

**Why.** `embed.FS` (Go 1.16+) bakes prompt templates and report templates
into the binary so the released artifact is a single file — no
`os.Executable()`+filepath dance. `signal.NotifyContext` (Go 1.16+) returns a
context cancelled on signal; pair with `errgroup` so every goroutine sees
cancellation. The exit-code mapping lives in `main`, not deep in the call
stack (Uber §Exit in Main).

**Citations.** stdlib `embed` and `os/signal` docs; Uber §Exit in Main /
Exit Once.

---

## Antipatterns To Avoid

### A1 — `any`/`interface{}` as a parameter type

```go
// Bad — caller has to type-assert; signature documents nothing.
func Process(v any) error { ... }

// Good — concrete type or a small interface stating what you need.
func Process(wo *workorder.WorkOrder) error { ... }
```

**Why.** Go Proverb: "`interface{}` says nothing." `any` is an alias for
`interface{}`; the noise is the same. Reserve it for serialization edges
(`json.Unmarshal` into `map[string]any`) and generic containers — never as a
top-level API parameter when the type is actually known. The plan's
preservation of `map[string]any`/`json.RawMessage` for *model-produced JSON*
is correct; do not let that leak into Bakeoff-owned data structures.

**Citations.** Go Proverbs "interface{} says nothing"; Google Decisions §Use
any (use the alias when it's genuinely needed, but think first).

---

### A2 — `init()` for anything but registration

```go
// Bad — init runs at import time, reads env, opens files, swallows errors.
func init() {
    cfg = loadConfig()
    db = mustOpen(os.Getenv("DB"))
}

// Good — init only for genuine registration (rare).
func init() { encoding.RegisterCodec(myCodec{}) }
// Everything else: explicit constructors called from main.
```

**Why.** `init()` runs before `main`, in undefined order across packages, with
no way to handle errors except `panic`. It defeats testing, makes import order
load-bearing, and breaks tools that import a package for analysis. Uber bans
it outright for anything beyond static registration; Google's guide treats
package-level state with `init` initialization as a litmus-test antipattern.

**Citations.** Uber §Avoid init(); Google Best Practices §Global state /
Litmus tests.

---

### A3 — Package-level mutable globals

```go
// Bad — every test interacts; impossible to parallelize.
var cache = map[string]*Result{}

// Good — state lives on a struct constructed in main.
type Cache struct { mu sync.Mutex; m map[string]*Result }
func NewCache() *Cache { return &Cache{m: map[string]*Result{}} }
```

**Why.** "Mutable global state introduces tight coupling... global variables
become an invisible parameter to every function in your program" (Practical Go
§4.5). Once Bakeoff has globals, parallel tests start sharing them and parity
runs become flaky. Hoist state onto a struct; pass the struct.

**Citations.** Practical Go §4.5; Uber §Avoid Mutable Globals; Google Best
Practices §Global state.

---

### A4 — Naked returns in non-trivial functions

```go
// Bad — what does "return" return? Reader has to walk back up.
func Parse(b []byte) (wo *WorkOrder, err error) {
    wo, err = decode(b)
    if err != nil { return }   // implicit; brittle
    err = validate(wo)
    return
}

// Good — explicit.
func Parse(b []byte) (*WorkOrder, error) {
    wo, err := decode(b)
    if err != nil { return nil, fmt.Errorf("decode: %w", err) }
    if err := validate(wo); err != nil { return nil, fmt.Errorf("validate: %w", err) }
    return wo, nil
}
```

**Why.** Code Review Comments: "Naked returns are okay if the function is a
handful of lines. Once it's a medium sized function, be explicit." Named
returns are sometimes useful for godoc clarity or for deferred mutation, but
they tempt naked returns and obscure the data flow.

**Citations.** Code Review §Naked Returns / Named Result Parameters.

---

### A5 — `panic` for normal error paths

```go
// Bad
func mustReadConfig(p string) []byte {
    b, err := os.ReadFile(p)
    if err != nil { panic(err) }
    return b
}

// Good
func readConfig(p string) ([]byte, error) {
    b, err := os.ReadFile(p)
    if err != nil { return nil, fmt.Errorf("read config %s: %w", p, err) }
    return b, nil
}
```

**Why.** "Don't panic" is a proverb. Panics produce stack traces, not
diagnostics; they cascade through goroutines; they cannot be recovered from
in a way that preserves invariants. Reserve them for genuinely unrecoverable
states (nil dereference, programmer error) and for static program-startup
assertions like `template.Must` (Uber §Don't Panic).

The Bakeoff CLI has a specific exit-code contract — `0/1/2/3/130`. A panic
exits with `2` and a runtime stack, which is wrong for every one of those
codes. Always `return error`, map to exit code in `main`.

**Citations.** Go Proverbs "Don't panic"; Code Review §Don't Panic; Uber
§Don't Panic.

---

### A6 — `utils`/`helpers`/`common` packages

```go
// Bad — package name describes nothing; callsite gives no clue.
package util
func StringIn(s string, ss []string) bool { ... }
func RandHex(n int) string { ... }

// Good — split by purpose; name by what each provides.
package slicesx     // or fold into the one caller
func ContainsString(s string, ss []string) bool { ... }
```

**Why.** "Utility packages" are where unrelated functions congeal; the name
describes containment, not purpose. Practical Go §4.2: prefer duplicating a
small helper to creating a `util` import dependency. If the same helper truly
spans many callers, split into focused packages named for what they do
(`slicesx`, `pathsafe`, `jsonx`) — but try inlining first.

**Citations.** Practical Go §4.2; Google Best Practices §Util packages.

---

### A7 — Goroutine leaks (no cancel, no wait)

```go
// Bad — caller has no way to stop, no way to know when it stopped.
go func() {
    for { tick(); time.Sleep(time.Second) }
}()

// Good — owned lifetime via context + WaitGroup (or errgroup).
func (r *Runner) heartbeat(ctx context.Context, wg *sync.WaitGroup) {
    defer wg.Done()
    t := time.NewTicker(time.Second); defer t.Stop()
    for {
        select {
        case <-ctx.Done(): return
        case <-t.C: r.emitHeartbeat()
        }
    }
}
```

**Why.** Bakeoff's runner has heartbeat ticks, stdout capture, stderr
capture, and a timeout, all on goroutines. Each must be cancellable and
joinable, or the parity harness will see ghost output and exit-code drift.
See P6. Uber suggests `go.uber.org/goleak` for tests that exercise goroutine
spawning.

**Citations.** Code Review §Goroutine Lifetimes; Uber §Don't fire-and-forget
goroutines.

---

### A8 — Premature interface for a single implementation

```go
// Bad — one impl, no real seam, just abstraction tax.
type LedgerStore interface {
    Write(run.ID, Manifest) error
    Read(run.ID) (Manifest, error)
}
type fileLedger struct{ root string }
func NewLedger(root string) LedgerStore { return &fileLedger{root} }

// Good — concrete type; introduce an interface when there are two impls
// or a test seam that function parameters can't cover.
type Ledger struct{ root string }
func NewLedger(root string) *Ledger { return &Ledger{root: root} }
```

**Why.** Returning `LedgerStore` locks the producer into the current method
set, hides the concrete type from godoc, and gives nothing in return. Code
Review Comments are explicit: "Do not define interfaces before they are
used." Add the interface at the consumer the day a second implementation
appears. The Bakeoff plan already says this for Phase 5 — apply it
everywhere.

**Citations.** Code Review §Interfaces; Google Decisions §Interfaces.

---

### A9 — Reimplementing `errors.Is` / `errors.As` / `errors.Join`

```go
// Bad — string match, fragile, breaks under wrapping.
if strings.Contains(err.Error(), "timeout") { ... }

// Bad — manual unwrap loop.
for cur := err; cur != nil; cur = unwrap(cur) {
    if tgt, ok := cur.(*SchemaError); ok { ... }
}

// Good
if errors.Is(err, ErrTimeout) { ... }
var se *SchemaError
if errors.As(err, &se) { ... }

// Multiple errors (Go 1.20+):
return errors.Join(closeErr, flushErr)
```

**Why.** `errors.Is`/`As` walk the wrap chain; string-matching does not. As
soon as a caller adds context with `%w`, the string check breaks. `errors.Join`
replaces hand-rolled multi-error types for cases like "close two files, return
both errors."

**Citations.** Cheney §Sentinel errors / Error types; stdlib `errors` package.

---

### A10 — Building flag parsing by hand

```go
// Bad — argv walk, hand-rolled, no help, no completion.
for i := 0; i < len(args); i++ {
    if args[i] == "--json" { jsonOut = true }
    // ...
}

// Good — Cobra (per the plan).
var cmd = &cobra.Command{
    Use:   "research",
    Short: "Run a research bakeoff with two providers",
    RunE:  runResearch,
}
cmd.Flags().Bool("json", false, "Emit machine-readable JSON to stdout")
```

**Why.** Bakeoff needs subcommands, help text, completion, exit-code
discipline, and consistent flag parsing across ~10 commands. Cobra is the
ecosystem default (gh, kubectl, hugo). The plan calls for Cobra explicitly;
do not regress to the standard `flag` package for the root command tree.
(Standard `flag` is fine for the smallest single-purpose helpers.)

**Citations.** Plan §Recommended Go Stack; Google Decisions §Flags (for flag
naming once you have Cobra: snake_case flag names, mixedCaps variables).

---

### A11 — Log *and* return the same error (double-reporting)

```go
// Bad — every caller logs again; the log file becomes a swamp.
if err := writer.Write(b); err != nil {
    log.Printf("write failed: %v", err)
    return err
}

// Good — wrap with context and return; let the top of the program log once.
if _, err := writer.Write(b); err != nil {
    return fmt.Errorf("write artifact %s: %w", path, err)
}
```

**Why.** Cheney's "Only handle an error once" rule: an error handled means a
*single* decision. Log-and-return is two decisions for one error, and the log
loses caller context while the return value loses the log message. Decide at
the top of `main` (or the top of a goroutine) whether to log or to render to
stderr; everywhere else, wrap and return.

**Citations.** Cheney §Only handle errors once; Practical Go §7.2; Uber
§Handle Errors Once.

---

### A12 — Ignoring `ctx.Done()` in long-running ops

```go
// Bad — reads forever; ctx cancellation is invisible.
func readAll(r io.Reader) ([]byte, error) {
    return io.ReadAll(r)
}

// Good — respect the context.
func readWithCtx(ctx context.Context, r io.Reader) ([]byte, error) {
    done := make(chan struct{})
    var b []byte; var err error
    go func() { defer close(done); b, err = io.ReadAll(r) }()
    select {
    case <-done: return b, err
    case <-ctx.Done():
        if c, ok := r.(io.Closer); ok { _ = c.Close() }
        return nil, ctx.Err()
    }
}
```

**Why.** Bakeoff's runner has hard timeouts and SIGINT semantics. Anything
that holds the goroutine in a blocking syscall without honoring `ctx.Done()`
defeats the timeout. Prefer `exec.CommandContext` over `exec.Command`; prefer
`net.Dialer{Timeout: ...}.DialContext` over `net.Dial`. The default in a CLI
is: every API that takes a context must observe its cancellation.

**Citations.** Google Decisions §Contexts; stdlib `os/exec`, `net` docs.

---

### A13 — Returning interfaces from constructors (interface pollution)

```go
// Bad — caller never gets to use *Runner's helpful concrete methods.
type Runner interface{ Run(context.Context, Plan) (Result, error) }
type runner struct{ ... }
func New() Runner { return &runner{} }

// Good
type Runner struct{ ... }
func New() *Runner { return &Runner{} }
```

**Why.** Returning an interface means the producer can never add methods
without changing the interface (a breaking change for every implementer). The
right shape is "accept interfaces, return concrete types" — exception: when
the interface *is* the product (`io.Reader`, `http.Handler`). For Bakeoff,
`*Runner`, `*Ledger`, `*Manifest` are all concrete.

**Citations.** Google Best Practices §Designing effective interfaces ("Accept
interfaces, return concrete types"); Code Review §Interfaces.

---

### A14 — Storing `context.Context` in a struct

(See P4 for the positive form. Re-stated as antipattern because it is
genuinely common in ports from other languages.)

```go
// Bad
type Job struct {
    ctx context.Context
    plan Plan
}

// Good — context is a function parameter, not a field.
type Job struct{ plan Plan }
func (j *Job) Run(ctx context.Context) error { ... }
```

**Why.** Storing context makes lifetime unclear, breaks cancellation,
and prevents reuse of the struct across requests. The one exception is
methods that must match a stdlib or third-party interface signature.

**Citations.** Code Review §Contexts.

---

## Apply To The Bakeoff Plan

### 5 antipatterns most likely to bite this rewrite

1. **A7 — Goroutine leaks in `internal/runner`.** Stdout capture, stderr
   capture, heartbeat, timeout, and process-group cleanup all run
   concurrently. This is the Phase 3 stop-gate. Adopt `errgroup` + explicit
   cancellation from day one.
2. **A12 — Ignoring `ctx.Done()` in provider I/O.** Bakeoff's whole
   value proposition is reliable subprocess timeouts. Use
   `exec.CommandContext`, `Cmd.WaitDelay`, and context-aware `io.Copy`
   loops; never bare `io.ReadAll(stdout)`.
3. **A11 — Log-and-return double-reporting.** The runner produces rich
   diagnostic state (status, salvage, retries). Decide *at the command
   layer* whether to log; everywhere else, wrap with `%w` and return.
   Otherwise the parity harness sees stderr drift Python won't have.
4. **A6 — `utils`/`helpers` packages.** The Python refactor map has
   focused names (`output`, `hints`, `ledger`...); preserve that
   discipline. The first "shared IO helper" temptation will be
   `WriteJSONAtomic` — put it in `internal/artifact` (where it belongs),
   not `internal/util`.
5. **A8 — Premature interfaces for a single impl.** The Bakeoff plan
   already says "do not introduce interfaces until there are at least two
   real implementations or a test seam that cannot be handled with function
   parameters." The risk is that Phase 1 scaffolding sketches
   `ProviderRunner`, `LedgerStore`, `DecisionResolver` interfaces by
   reflex, and Phase 5 inherits them. Resist.

### 5 idioms that should be non-negotiable in the coding-standards section

1. **P3 — Errors: `%w` wrapping, sentinels via `errors.Is`, types via
   `errors.As`.** Status vocabulary parity with Python depends on stable,
   inspectable errors — not stringly-typed checks.
2. **P4 — `ctx context.Context` is always the first parameter; never a
   struct field.** Pair with `signal.NotifyContext` in `main` (P12) so
   SIGINT maps to exit code 130 cleanly.
3. **P6 — `errgroup` for any function that spawns goroutines.** Channel
   directions specified at boundaries. Caller blocks on `Wait()` and gets
   the first error.
4. **P5 — Accept interfaces, return structs; consumer defines the
   interface.** Producers (`runner`, `ledger`, `manifest`) return
   `*Runner`, `*Ledger`, `*Manifest`. Test seams live in the consuming
   command package.
5. **P11 — Build with `-trimpath` and inject version/commit via `-X`
   ldflags.** Single-binary distribution is the rewrite's headline
   benefit; lock in reproducible builds before Phase 2.

---

## Sources

- Google Go Style — Guide: https://google.github.io/styleguide/go/guide
- Google Go Style — Decisions: https://google.github.io/styleguide/go/decisions
- Google Go Style — Best Practices: https://google.github.io/styleguide/go/best-practices
- Go Code Review Comments: https://go.dev/wiki/CodeReviewComments
- Effective Go: https://go.dev/doc/effective_go
- Go Proverbs: https://go-proverbs.github.io/
- Dave Cheney, "Don't just check errors, handle them gracefully":
  https://dave.cheney.net/2016/04/27/dont-just-check-errors-handle-them-gracefully
- Dave Cheney, "Practical Go":
  https://dave.cheney.net/practical-go/presentations/qcon-china.html
- Uber Go Style Guide: https://github.com/uber-go/guide/blob/master/style.md

All sources fetched and indexed 2026-05-16; verbatim quotes verified against
the indexed text in the local sandbox knowledge base (sources:
`google-go-guide`, `google-go-decisions`, `google-go-best-practices`,
`go-code-review-comments`, `effective-go`, `go-proverbs`,
`dave-cheney-handle-errors`, `dave-cheney-practical-go`, `uber-go-style`).
