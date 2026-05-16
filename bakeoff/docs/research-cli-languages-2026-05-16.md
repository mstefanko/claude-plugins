# CLI language choice for bakeoff — research notes

**Date:** 2026-05-16
**Subject:** Should bakeoff stay Python, or be rewritten in Go / Rust / TS?
**Author/researcher:** delegated research pass; sources cited inline.

## TL;DR

**Stay on Python.** For a solo-dev, IO-bound, subprocess-orchestration harness with ~9k LOC and zero runtime dependencies, the rewrite ROI is negative. The arguments for Go/Rust evaporate once you notice that (a) the bottleneck is the LLM subprocess (minutes), not the harness (milliseconds), (b) Python's `asyncio.create_subprocess_exec` + `wait_for` covers every concurrency primitive bakeoff needs, and (c) `uv` has effectively eliminated the historical Python distribution pain.

If you ever distribute to end users via `brew install bakeoff`, revisit the question. Until then: keep Python, fix the 2000-line `cli.py` instead.

---

## 1. What does the industry actually ship in? (2024–2026)

The popular-modern-CLI landscape sorts cleanly:

| Tool | Primary language | Notes / source |
|---|---|---|
| ripgrep | **Rust** | https://blog.burntsushi.net/ripgrep/ — speed-first, single static binary |
| fd | **Rust** | https://github.com/sharkdp/fd |
| bat | **Rust** | https://github.com/sharkdp/bat |
| zoxide | **Rust** | https://github.com/ajeetdsouza/zoxide |
| uv | **Rust** | https://astral.sh/blog/uv (Feb 2024) — Python *packaging* in Rust |
| ruff | **Rust** | https://astral.sh/blog/the-ruff-formatter (Oct 2023) |
| fzf | **Go** | https://github.com/junegunn/fzf — "Distributed as a single binary for easy installation" |
| gh (GitHub CLI) | **Go** | https://github.com/cli/cli — 44k stars; Cobra-based |
| kubectl, terraform, hugo, docker | Go | (well-established) |
| **codex** (OpenAI) | **Rust** (96.2%) + Python (2.8%) + TS (0.3%) | https://github.com/openai/codex — repo contains both `codex-cli/` (legacy TS) and `codex-rs/` (current Rust); language pie is Rust-dominant |
| **claude-code** (Anthropic) | JS/TS (npm-distributed) | https://github.com/anthropics/claude-code — `npm i -g @anthropic-ai/claude-code` |
| pip, poetry, pipx, ansible, aws-cli, httpie | Python | (still standard) |

### Reading the pattern

- **Compute-bound / hot-path tools → Rust.** ripgrep, ruff, uv, fd, bat. The motivation is real: ruff is 30–100× faster than Black; uv is ~10× faster than pip-tools (https://astral.sh/blog/uv benchmark chart: uv 0.60s vs pip-compile 3.37s for Trio resolve). These tools' value proposition *is* speed.
- **Industrial CLIs that wrap external services → Go.** gh, kubectl, terraform, fzf. Go wins where the dominant work is "spawn workers, manage their lifecycle, hit network, render output" — exactly bakeoff's profile.
- **Coding agents → split.** Anthropic shipped claude-code in JS/TS to ride the npm ecosystem and Node's mature async story. OpenAI started codex in TS and **migrated the core to Rust** (the language ratio in the repo is the proof). The migration is interesting but the workload differs from bakeoff: codex implements terminal UI, sandboxed exec, MCP servers, IDE integrations. It's a product, not a personal harness.
- **Glue / orchestration / data-shaped CLIs → Python.** ansible, aws-cli, httpie, pip, jc, datasette. Where the value is in the *logic* (config parsing, JSON munging, subprocess plumbing, schema validation), Python is still the default.

**Conclusion for Q1:** There is no single "industry-shipped" language. The selection sorts by *workload*, not fashion. Bakeoff's workload (subprocess plumbing + JSON + filesystem + occasional report rendering) sits squarely in the "Python is normal" bucket.

---

## 2. Is there a real case for Go or Rust *for this tool*?

Working through the actual bakeoff workload:

### Subprocess orchestration

- **Python** (`asyncio.create_subprocess_exec` + `asyncio.wait_for` + `asyncio.gather`): https://docs.python.org/3/library/asyncio-subprocess.html. The example in the Python docs is *literally* "run two shell commands in parallel with `gather`." `Process.terminate()` sends SIGTERM, `Process.kill()` sends SIGKILL, `start_new_session=True` (via the underlying `Popen`) gives you the process group. `wait_for(timeout=...)` is the wall-clock deadline primitive.
- **Go** (`exec.CommandContext`): https://pkg.go.dev/os/exec. The `Cmd.Cancel` field + `WaitDelay` is genuinely well-designed — context cancellation maps to a kill signal, `WaitDelay` is the bakeoff "kill grace period" baked into stdlib.
- **Rust** (`std::process::Command`): https://doc.rust-lang.org/std/process/struct.Command.html. Solid but lower-level. Async + timeout requires Tokio (`tokio::process` + `tokio::time::timeout`). More machinery to wire up than Python or Go.

**Honest take:** Go's `CommandContext` model is the *cleanest* of the three for "spawn N children with deadlines and graceful kill." Python is fine but you write a wrapper. Rust requires more ceremony but compile-time guarantees the lifecycle is honored. None of these is a strict order-of-magnitude win for bakeoff — they're shading.

### Concurrency model for N subprocesses with deadlines

Bakeoff runs **2** providers in parallel today, not 200. `asyncio.gather` + `wait_for` is enough. Goroutines would be elegant but you're not contention-limited.

Peter Bourgon's "Go for Industrial Programming" (https://peter.bourgon.org/go-for-industrial-programming/) makes the case that goroutines are a *low-level primitive* and that real industrial Go uses `oklog/run` or `errgroup` to enforce "never start a goroutine without knowing how it stops." That's a feature you'd build anyway. Python's `asyncio.TaskGroup` (3.11+) gives you the same structured-concurrency guarantee.

### JSON / schema-heavy code

- **Python:** `json` stdlib + `jsonschema` (or hand-rolled validation like bakeoff today). Dict-shaped, ergonomic, but no compile-time guarantees.
- **Go:** `encoding/json` + struct tags. *Type-safe at compile time*, which would genuinely catch some bakeoff bugs (e.g., schema field rename). The cost: every schema change is two edits (struct + JSON code), and Go's zero-value semantics for missing fields require careful pointer/optional handling.
- **Rust:** `serde` is best-in-class. Schema-aware deserialization with compile-time enforcement, sum types via enums, `Option<T>` for missing-or-null. **This is the one place Rust has a clear technical advantage** for bakeoff — provider output schemas are exactly the bugs Rust's type system catches.

But: bakeoff already passes schema tests and the JSON code isn't where bugs are coming from. The bugs are in the 2000-line `cli.py` (orchestration logic). Type safety on JSON solves a problem you don't have.

### Startup time

- **Python:** ~30–80ms cold (3.11+). With `bakeoff` invoked as a subagent or shell-out, this is rounding error vs. a multi-minute LLM call.
- **Go:** ~5–15ms. Imperceptibly better.
- **Rust:** ~2–10ms. Imperceptibly better.

**Irrelevant for bakeoff.** This matters for `ls`-like tools called in tight loops. It does not matter for `bakeoff run`.

### Distribution

- **Python:** Historically the worst part. Today: `uv tool install bakeoff` or the shebang trick (`#!/usr/bin/env -S uv run`, https://simonwillison.net/2024/Aug/21/usrbinenv-uv-run/) effectively gives you single-command install with isolated env. For a personal tool, `bin/bakeoff` shim + `uv sync` is fine.
- **Go:** `go install`, or `goreleaser` for cross-platform single binaries. fzf and gh do this. Genuinely better for *distribution to others*.
- **Rust:** `cargo install`, or release-mode static binaries via GitHub Actions. ripgrep's model.

**Verdict:** Single-binary is a real advantage *if* you're shipping to non-Python-having users. The prompt says "not distributed via package managers to end users yet." So this advantage is hypothetical for bakeoff.

### Maintainability for a solo dev

- **Python:** Best AI-assistance ergonomics (model training data overwhelmingly Python). LSP (Pyright/pylsp) is good but not bulletproof — bakeoff would benefit from stricter `mypy --strict` + `ruff` to claw back what static typing gives you for free in Go/Rust. Refactoring tools are weaker than Go's.
- **Go:** Refactoring rename, jump-to-definition, gopls all rock-solid. Verbose but very readable. Lower AI-assistance density than Python but still strong.
- **Rust:** rust-analyzer is excellent. Refactoring is type-driven and reliable. Compile times for a tool this size: ~30–60s clean, ~5–10s incremental. AI assistance: weaker than Python, improving fast.

**For a solo senior engineer: Python with strict typing + ruff is the highest-velocity option.** Rust is the highest-correctness option. Go is the middle road.

### Iteration speed when adding commands / features

Python wins on this axis, decisively, for a tool that's still figuring out its shape. No compile step, no struct-tag dance for every JSON change, REPL-friendly. The bakeoff codebase is *still evolving its abstractions* (review-context, run-manifest, faceted research are all recent additions per `docs/`). Locking the shape into Go interfaces or Rust traits prematurely is expensive.

---

## 3. Real tradeoffs vs. Python — scorecard

| Dimension | Python | Go | Rust | Winner for bakeoff |
|---|---|---|---|---|
| Startup time | ~50ms | ~10ms | ~5ms | Tie (bottleneck is LLM, not harness) |
| Distribution | `uv tool install` | single binary | single binary | Go/Rust if you ship; Python if solo |
| Concurrency model | asyncio + TaskGroup | goroutines + context | Tokio | Go cleanest; Python sufficient |
| Subprocess API | Good, async-native | **Excellent** (CommandContext/WaitDelay) | Good (Tokio required) | Go |
| JSON / schema | Dynamic, hand-validated | Struct tags, type-safe | **serde, best-in-class** | Rust |
| Solo-dev maintainability | **Best (AI density, brevity)** | Good | Steeper learning curve | Python |
| Refactoring tools | OK with strict types | Excellent | Excellent | Tie Go/Rust |
| AI assistance | **Best** | Strong | Improving | Python |
| Iteration speed | **Best** | Good | Slowest | Python |
| Catches lifecycle bugs at compile time | No | Partial | **Yes** | Rust |
| Already-working code | **8.9k LOC** | 0 | 0 | Python (overwhelmingly) |

Python loses two cells: subprocess API ergonomics (Go's `CommandContext` is genuinely nicer) and JSON schema enforcement (Rust's serde catches a bug class Python lets through). Neither is bakeoff's current pain point. The 2000-line `cli.py` is — and a rewrite doesn't fix architecture problems, it relocates them.

---

## 4. Counter-evidence: when Python remains the right answer

- **Astral's own tooling** is the strongest pro-Rust marketing in existence (uv, ruff). But the irony is **the thing they're packaging is Python**. The Python ecosystem is the product. Astral chose Rust because *speed of the tool* was the entire pitch (https://astral.sh/blog/uv: "10–100x faster"). Bakeoff is not selling speed.
- **Armin Ronacher** (Flask/Jinja author), who knows both ecosystems intimately, writes Rust when he needs a library to be embeddable from many languages and reach (https://lucumr.pocoo.org/2024/8/27/minijinja/ — MiniJinja in Rust). He still ships Python for application-level work. His pattern: Rust for libraries with hot loops, Python for glue. Bakeoff is glue.
- **uv ecosystem changes the math.** Pre-uv, "Python distribution hell" was a real argument for Go/Rust. Post-uv, `uv tool install` + `uv run` + the `uv run` shebang (https://simonwillison.net/2024/Aug/21/usrbinenv-uv-run/) cover the gap. The "you have to ship a venv" objection is largely dead in 2025-2026.
- **Peter Bourgon's industrial-Go talk** (https://peter.bourgon.org/go-for-industrial-programming/) is a long argument that even *in* Go, you have to add conventions (oklog/run, errgroup) to make concurrency safe. Python's `asyncio.TaskGroup` gives you structured concurrency in stdlib. The "Go's concurrency is just better" pitch is weaker than it looks once you account for what you actually have to build.
- **Maintainer cost on a 9k-LOC codebase.** A rewrite in Rust at one-LOC-per-LOC parity is several weeks of senior-engineer time. A rewrite in Go is faster but still 1–2 weeks. That time spent refactoring `cli.py` and adding `mypy --strict` returns more value.

---

## 5. Sources I read (verified URLs)

1. **Charlie Marsh, "uv: Python packaging in Rust"** — https://astral.sh/blog/uv (Feb 15, 2024). The pitch for Rust-as-tooling-for-Python; benchmark numbers; positions uv as drop-in pip replacement. Indexed as `astral-uv-launch-blog`.
2. **Charlie Marsh, "The Ruff Formatter"** — https://astral.sh/blog/the-ruff-formatter (Oct 24, 2023). 30–100× speed claims; "obsessive focus on performance" as the design axis. Indexed as `astral-ruff-formatter-blog`.
3. **Andrew Gallant (burntsushi), "ripgrep is faster than {grep, ag, git grep, ucg, pt, sift}"** — https://blog.burntsushi.net/ripgrep/ (Sep 23, 2016, still canonical). Deep dive on why Rust + smart algorithms beats the field. Indexed as `burntsushi-ripgrep`.
4. **Peter Bourgon, "Go for Industrial Programming"** — https://peter.bourgon.org/go-for-industrial-programming/ (talk transcript from GopherCon EU 2018). Argues goroutines are low-level and you need `oklog/run`-style discipline; relevant for honest assessment of Go's concurrency story. Indexed as `peter-bourgon-go-industrial`.
5. **Armin Ronacher, "MiniJinja: Learnings from Building a Template Engine in Rust"** — https://lucumr.pocoo.org/2024/8/27/minijinja/ (Aug 27, 2024). Why one of Python's most prolific authors picks Rust *for embeddable libraries* but not for glue. Indexed as `mitsuhiko-rust-python`.
6. **Simon Willison, "#!/usr/bin/env -S uv run"** — https://simonwillison.net/2024/Aug/21/usrbinenv-uv-run/ (Aug 21, 2024). The uv shebang pattern that closes the Python distribution gap. Indexed as `simonw-uv-run`.
7. **Python stdlib: asyncio subprocesses** — https://docs.python.org/3/library/asyncio-subprocess.html. Indexed as `python-asyncio-subprocess`. The `gather`/`wait_for`/`terminate`/`kill` surface that already covers bakeoff's needs.
8. **Go stdlib: os/exec** — https://pkg.go.dev/os/exec. Indexed as `go-os-exec`. The `CommandContext` + `Cancel` + `WaitDelay` API; the cleanest of the three for deadline-bounded child management.
9. **Rust stdlib: std::process::Command** — https://doc.rust-lang.org/std/process/struct.Command.html. Indexed as `rust-std-process-command`. Comprehensive but lower-level; async needs Tokio.
10. **GitHub repos consulted for language facts:** github.com/cli/cli (Go), github.com/openai/codex (Rust 96.2%), github.com/anthropics/claude-code (JS/TS, npm), github.com/sharkdp/bat, github.com/sharkdp/fd, github.com/ajeetdsouza/zoxide, github.com/junegunn/fzf (Go).

---

## 6. Concrete recommendations for bakeoff

**Stay on Python. Do these instead of a rewrite:**

1. **Break up `src/bakeoff/cli.py` (2018 lines).** The planning docs already include `docs/cli-maintainability-refactor-implementation-plan-2026-05-16.md`. Execute that. This is where the bugs live; this is where the rewrite pressure is actually coming from.
2. **Adopt strict typing.** Add `mypy --strict` or `pyright` in `--strict` mode. Reclaim ~80% of the "Rust would catch this" argument without a rewrite. Schema dataclasses (or `pydantic` if you accept a dep) catch the JSON-shape bugs Rust's serde would catch.
3. **Adopt `asyncio.TaskGroup` for the provider runner if not already.** Structured concurrency closes the "Go would be cleaner" gap. (Python 3.11+; bakeoff already targets 3.10+ — consider bumping floor to 3.11.)
4. **Use `uv` for distribution.** `uv tool install` or `uvx bakeoff` makes single-command install work on any machine with uv. Stop thinking of distribution as a Python problem.
5. **Revisit the language question only if** (a) bakeoff becomes a shipping product with non-Python users, OR (b) you find yourself fighting genuine concurrency/lifecycle bugs that types could prevent. Neither applies today.

**If you later decide a rewrite is necessary:** the choice is Go, not Rust. Go's subprocess API (`CommandContext` + `WaitDelay`) is purpose-built for this workload; Rust's type-system wins don't pay off enough for a 9k-LOC orchestration tool to justify the iteration-speed loss. The codex repo is the *only* strong counter-example, and codex is a far larger product with a much wider surface area than bakeoff.

**Do not rewrite in TypeScript/Node.** It buys you nothing Python doesn't have, and the subprocess + signal story on Node is the weakest of the four.
