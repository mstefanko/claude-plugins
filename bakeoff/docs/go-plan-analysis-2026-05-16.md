# Go Side-By-Side Parity Plan — Audit Findings

Date: 2026-05-16
Plan reviewed: `docs/go-side-by-side-parity-implementation-plan-2026-05-16.md`
Python source verified at: `src/bakeoff/*.py` (5,728 LOC across 11 modules)

---

## 1. Verified vs. Unverified Plan Claims

### VERIFIED
- **Module path is local:** The `pyproject.toml` defines `name = "bakeoff"` with no public publish URL; `bin/bakeoff` is a bash shim that does `exec python3 -m bakeoff.cli "$@"`. The plan's suggested module path (`github.com/mstefanko/claude-plugins/bakeoff`) is acceptable.
- **Exit codes 0/1/2/3 are canonical.** Confirmed in `src/bakeoff/cli.py:92-110` `EXIT_CODE_EPILOG`. The plan also lists `130` (interrupted) — this is **not** in the Python epilog but is reachable via standard Python signal handling. Mark as [UNVERIFIED] that any code path explicitly returns 130.
- **Status vocabulary is small.** `runner.py` emits `ok`, `ok_after_format_retry`, `timeout`, `output_cap`, `missing_provider`, `format_retry`, `stderr_truncated`. The plan correctly demands "match the Python status vocabulary exactly" but **does not enumerate** the vocabulary. This is a parity hazard.
- **JSON formatting:** `io.py:11` uses `json.dumps(data, indent=2, sort_keys=True) + "\n"` — two-space indent, sorted keys, trailing newline. The plan's "two-space indented JSON, deterministic key order, trailing newline" matches. However `cli.py:355` uses `sort_keys=False` for one summary path — **plan does not cover the inconsistency**.
- **Fake providers exist as a runtime mechanism**, not a fixture file. `tests/test_modes_end_to_end.py:777 install_fake_providers()` writes a Python script at test time, then injects it onto PATH and sets `BAKEOFF_FAKE_PROVIDER_NAME`. The plan says "deterministic fake provider scripts if the existing test fixtures are not reusable from a black-box harness" — they are **not** directly reusable; they are inlined in a Python test helper. This needs to be lifted out into standalone executable scripts before Phase 0 closes.
- **Process-group termination is Unix-only.** `runner.py:611,623` calls `os.killpg(process.pid, SIGTERM/SIGKILL)`. The plan flags Windows correctly.
- **`bin/bakeoff` is a bash shim**, not a Python entry point. Plan's Phase 8 cutover idea ("update bin/bakeoff to exec the Go binary") is feasible — the shim is 5 lines.
- **`bakeoff_version`** is embedded in `manifest.json` (`manifest.py:42`) and `meta.json` (`cli.py:1808`). Currently `0.0.0`. Plan's normalize-list does **not** include `bakeoff_version` — must be normalized when Python and Go disagree, or pinned to a shared value during the trial.

### UNVERIFIED / GAPS
- **Python's "src/bakeoff/" has no `commands/` subdirectory.** The plan implicitly assumes the maintainability refactor (which would create `commands/`) has already produced a clean map. It has not. `cli.py` is **2,018 lines** and is the monolithic command dispatcher. The plan's "command modules become Go command packages" requires the reader to mentally do the refactor first. This is a hidden prerequisite.
- **No `output.py`, `command_hints.py`, `ledger.py`, `summaries.py`, `verification.py`, `decisions.py`, `artifacts.py`, `prompts.py`, `scope.py` files exist in Python.** The "Python Refactor Plan To Go Package Map" table is a map from a **hypothetical** refactor (described in the sibling doc) to Go packages, not from actual Python files. Readers who skim will look for `ledger.py` and fail. Flag prominently.
- **`130` interrupted exit:** I did not find an explicit `return 130` or signal handler in `cli.py`. Plan should verify or remove.

---

## 2. Clarity of Implementation Details

| Item | Verdict | Notes |
|---|---|---|
| Binary names | OK | `cmd/bakeoff-go` clearly distinct from `bin/bakeoff` |
| Package layout | OK | 21 internal packages enumerated; boundaries from refactor doc |
| Dependencies | OK | Cobra + stdlib only |
| Module path | Soft | Plan says "can be local at first" — does not say where to commit go.mod, whether at repo root or under `bakeoff/`. Given the marketplace structure (root `.claude-plugin/marketplace.json`, plugins as subdirs), this matters. **`go.mod` should go in `bakeoff/`**, not the marketplace root. Plan should state this. |
| Entry points | Weak | No mention of `init()` ordering, `cobra.OnInitialize`, or how environment vars are read. |
| Logging format | **Missing** | Python has no `logging` import (verified). Output goes via `_note()` and `_warn()` printing to stderr. Plan does not codify this — `internal/output` package boundaries are vague on whether it owns the stderr channel. |
| Error model | **Missing** | Plan never says how Go errors map to exit codes. Cobra has its own `RunE` error pattern; does a `ValidationError`-equivalent map to exit 2 by type? By sentinel error? By wrapping? |
| Config loading | OK by omission | Plan correctly says "Do not add config files." Python verified to use **zero** env vars in `cli.py` and `runner.py`. |
| Output streams | Weak | Python prints notes/warnings to stderr; JSON summaries to stdout. Plan does not state this contract for Go. |
| Stdout vs stderr discipline | **Missing** | Critical for `--json` mode parity. |
| Interactive mode | OK | No TTY behavior in Python; no concern. |
| Version pinning | **Missing** | No Go version pin. `go.mod` `go 1.??` declaration is undefined. Local Go is 1.24.4. |
| Cross-platform support | Partial | Windows process-group is flagged; nothing about case-insensitive FS, path separators in manifests, line endings in `report.md`. |
| Test harness | OK | Plan correctly puts `scripts/parity-go.py` in Phase 0 and reasons about black-box invocation. |
| CI | **Missing** | No GitHub Actions / CircleCI mention. Plan says "go test ./...; pytest; python3 scripts/parity-go.py" in Phase 7 but never wires it up. **Recommend** lifting CI into Phase 0 alongside the parity harness. |

---

## 3. Build Order

### Strong points
- Phase 3 (Provider Runner Spike) is correctly placed early — the plan's own "Risk Notes" cite it as the conversion risk. Good.
- Phase 0 (Python freeze + parity harness) before any Go is correct.
- Stop-gate after Phase 3 is well chosen.

### Reordering recommendations
1. **Move fake-provider extraction into Phase 0 explicitly.** The plan says "deterministic fake provider scripts if the existing test fixtures are not reusable." They are not reusable — they live inside `tests/test_modes_end_to_end.py:777`. Phase 0 must produce **standalone, executable fake-provider scripts on disk** (probably under `tests/parity/fakes/`) so both CLIs can spawn them via PATH. Without this, Phase 3 will block.
2. **Move CI wiring earlier.** Plan's Phase 7 implicitly assumes a working CI to run all three test suites. Add a Phase 0.5 or fold into Phase 0: a CI job that runs `pytest` and `python3 scripts/parity-go.py` on every PR. Add `go test ./...` to the same job once Phase 1 lands.
3. **Phase 2 sequencing risk:** Phase 2 implements `init` and `validate` *and* the prompt contracts. Prompts are byte-for-byte sensitive but cannot be parity-tested end-to-end until Phase 3 (runner) exists — only unit-level prompt-text comparisons are possible. Plan does state this ("Prompt-generation tests compare Go prompts against Python-generated prompt fixtures byte-for-byte"). This works but requires **Phase 0 to also dump prompt fixtures from Python** so Phase 2 has something to compare against. The plan does not list prompt fixtures as a Phase 0 deliverable.
4. **Phase 5 collapses too much.** Phase 5 implements `internal/provider`, `internal/scope`, `internal/decision`, `internal/report`, and the entire research command — 5 packages, one phase. Compare to Phase 4 (4 packages, no commands) and Phase 6 (5 commands). Recommend splitting Phase 5 into **5a (provider/scope/argv)** and **5b (decision/report/research command)**. The scope-probe logic alone (`providers.py:70-89` parses CLI `--help` text) is fragile and deserves isolated tests.

---

## 4. Hidden Assumptions

The plan assumes the reader knows:

1. The Python maintainability refactor target file names (`output.py`, `ledger.py`, etc.) are **proposed**, not extant. The mapping table reads as if they exist.
2. `bin/bakeoff` is a 5-line bash wrapper, not a Python entry point that needs porting.
3. Fake providers are an inline Python textwrap.dedent string in a test helper, not standalone fixtures.
4. `cli.py` is monolithic (2,018 lines); "command modules become Go command packages" assumes a refactor the reader must internalize.
5. `runner.py` already implements all the listed behaviors (it does — 761 lines, 17 test cases verified).
6. The `manifest.json` schema is fingerprint-driven (`manifest.py:203 _artifact_fingerprints`) — Go must hash the **same bytes** the same way (SHA-256, file size).
7. The Python `report.md` is generated, not hand-edited (true, but plan never says).
8. Cobra's exit-on-error behavior must be overridden to hit the bespoke exit-code matrix; plan says "preserve exit codes" but not "disable Cobra's default error printing / SilenceErrors=true."
9. The reader knows that argparse's `--help` is **never** going to match Cobra's, and the plan correctly accepts that — but doesn't articulate how `--help` output is excluded from parity diffs.
10. Bakeoff's run-ledger compatibility includes the `latest` symlink dance (`cli.py:1952-1964`) with text-file fallback for symlink-hostile filesystems. Plan says "latest symlink/text fallback behavior" — assumes reader knows why both exist.
11. The repository convention: this is a **plugin marketplace**, not a single Go-friendly repo. `go.mod` placement (`bakeoff/go.mod` vs root) is unstated.

---

## 5. Open Questions / Punts

1. **What is the go.mod path actually?** Plan says "can be local at first." This is procrastination — pick `github.com/mstefanko/mstefanko-plugins/bakeoff` and commit.
2. **What Go version?** Pin in `go.mod` (`go 1.22` for stable, `go 1.24` for current). Affects struct-tag handling, slog availability, etc.
3. **What is the error model?** Sentinel errors? Typed `*ExitError{code int}`? Cobra `SilenceErrors` + outer recovery in `main`?
4. **How does `_note`/`_warn` map to Go?** A `internal/output.Note(string)` function writing to `os.Stderr` is implicit but never declared.
5. **`--json` stdout discipline:** when `--json` is set, are notes/warnings still permitted on stderr, or fully silenced? Python emits them to stderr; plan should confirm.
6. **`bakeoff_version` field in artifacts:** how does Go version itself? Same `0.0.0`? A separate `bakeoff_go_version`? Plan is silent.
7. **Random / time non-determinism:** `RUN_ID_RE` runs ids are generated by `cli.py` — how? Plan does not say "preserve run-id generation algorithm" vs "any matching ID is fine because parity harness normalizes it."
8. **Cobra `--help` output:** plan says "Cobra help output will not match argparse byte-for-byte" but does not say which sections (`Exit codes:` epilog?) should be preserved. The epilog is product-meaningful documentation.
9. **JSONC comment stripping:** plan says "Port JSONC comment stripping and validation behavior" — algorithm-level parity, byte-level parity, or just behavioral parity on valid inputs?
10. **What does "semantic parity for JSON artifacts" mean exactly?** Two-space indent + sorted keys + trailing newline + same value graph? Or just same value graph? Plan implies the former but says "semantic." Tighten.
11. **Validator callbacks in runner:** Python passes a `validator` callable; Go's idiomatic shape is a `Validator interface`. Plan says "do not introduce interfaces until two implementations exist" — fine, but then **how does runner accept the validator?** Function-typed field? Anonymous func? Decide once.
12. **Manifest fingerprint stability across OSes:** SHA-256 of file bytes is OS-neutral; but file size on Windows with CRLF line endings is not. Plan should mandate LF-only writes.

---

## 6. Parity Contract Gaps

### What the plan covers
- Exit code, stdout/stderr (after normalization), required artifacts, prompts, `meta.json`, `manifest.json`, `decision.json`, `report.md`, ledger tree, `runs verify` cross-CLI.
- Normalize list (run id, temp paths, wall-clock, timings, timestamps, provider versions, manifest fingerprints when underlying differs only in normalized fields).
- Do-not-normalize list (status names, artifact names, prompt text, decision kinds, triage states, exit codes, report content).

### Gaps
1. **Definition of "pass" for the harness is implicit.** Is it: zero non-normalized differences across all captured workflows? Plan says "parity harness passes for X" in each phase but never defines `passes`. **Recommend:** the harness should emit a structured diff report, and `pass` means `diff_count == 0` after normalization.
2. **No fixture inventory.** Plan lists 20+ workflows to capture in Phase 0 but doesn't say where the recorded outputs land (`tests/parity/fixtures/<workflow>/{stdout,stderr,exit_code,ledger.tar,...}` is the implied shape, never stated).
3. **No coverage matrix for runner statuses.** All seven statuses (`ok`, `ok_after_format_retry`, `timeout`, `output_cap`, `missing_provider`, `format_retry`, `stderr_truncated`) need at least one parity case. Plan should make this a checklist.
4. **`report.md` rendering:** "report content" is "do not normalize" but `report.md` may include timestamps or run ids inline. Verify. (Not done in this audit.)
5. **`bakeoff_version` parity:** Go and Python must agree on what to write. Plan needs a rule: e.g., both emit `0.0.0` during trial; cutover bumps both.
6. **No "definition of done" for the **overall** trial.** Phase 7 lists cutover criteria, but "smaller or clearly easier to navigate" is subjective. Add a measurable metric: e.g., LOC count, cyclomatic complexity, or a third-party reviewer rubric.
7. **Cross-CLI ledger reads:** Phase 6 says "Existing Python ledgers can be inspected by Go `show`, `ls`, `runs verify`" — good, but Phase 4 done-criteria already implies this. Make the constraint explicit at the **end of Phase 4**, not Phase 6.
8. **JSONC comment stripping edge cases:** strings containing `//`, block comments inside string literals — plan does not call these out as parity test cases.

---

## 7. Definition of Done — Per Phase

| Phase | Has DoD? | Quality | Gap |
|---|---|---|---|
| Phase 0 | Yes | Adequate | Missing: extracted fake-provider scripts, prompt fixtures, snapshot directory layout, normalize-list test, harness exit-code contract |
| Phase 1 | Yes | Good | `go test ./...` passes is trivially true if no tests exist yet; should require "at least N table tests for flag parsing per command" |
| Phase 2 | Yes | Good | "Parity harness passes for init and validate" is the right bar |
| Phase 3 | Yes + stop gate | **Best in plan** | Explicit stop gate is excellent. Strengthen: require timing parity within X% on output-cap salvage (timing-sensitive race) |
| Phase 4 | Yes | Adequate | Cross-CLI `runs verify` is the right bar; add explicit fingerprint-byte-equality assertion |
| Phase 5 | Yes | Weak | "Semantically and byte-for-byte where dynamic fields are not involved" — vague. Define which fields are dynamic. |
| Phase 6 | Yes | Adequate | "Every frozen workflow" — only meaningful if Phase 0 froze them all |
| Phase 7 | Yes | Subjective | "Smaller or clearly easier to navigate" — add objective metric |
| Phase 8 | No formal DoD | Weak | Cutover is described as a list of edits; no test that proves cutover succeeded. Add: "post-cutover, `bin/bakeoff --help` invokes Go binary AND parity harness still green from the new entry point." |

---

## 8. Security / Performance / Coupling

- **Security:** Plan invokes provider CLIs via subprocess; Go's `exec.CommandContext` with PATH lookup matches Python. No new auth boundaries. Note: scope-help parsing (`providers.py:70-89`) consumes stdout/stderr of `claude --help` — if a provider CLI returns malicious help text, both Python and Go are exposed equally. Out of scope but worth noting.
- **Performance:** Plan never sets a performance bar. Go is expected to be faster than Python for subprocess orchestration. If Go is *slower* in any scenario, is that a parity blocker? Plan should say no, but should require it not be *catastrophically* slower (e.g., 10x).
- **Coupling:** The 21-package layout risks over-modularization. Phase 5's `internal/provider`, `internal/scope`, `internal/decision`, `internal/report` and `internal/commands/researchcmd` will have circular import temptations. Cobra commands typically depend on domain packages, never the reverse — plan should state this rule.

---

## 9. Out-of-Scope Items the Plan Should Explicitly Disclaim

The plan does say "Do not add config files, SQLite, dashboards, caches, pruning, streaming event protocols, or plugin systems." Good. Add:

- No structured logging library (slog/logrus/zap). Stick to `internal/output`.
- No metrics/telemetry.
- No alternative output formats (TOML, YAML).
- No Windows binaries until Unix parity is boring.
- No Homebrew formula or release artifacts during the trial.

---

## 10. Top Risks (Prioritized)

1. **Fake provider extraction blocks Phase 3.** Currently inlined in test helper; must be lifted out.
2. **Prompt fixtures must exist before Phase 2.** Plan says compare against fixtures but never produces them in Phase 0.
3. **Error/exit-code mapping in Cobra is unspecified.** Will be reinvented inconsistently across phases.
4. **`bakeoff_version` field in artifacts** creates a parity field that needs an explicit rule.
5. **JSON sort_keys inconsistency** in Python (one path uses `sort_keys=False`) is a latent parity bug.
6. **CI not wired until Phase 7.** Earlier phases will accumulate undetected drift.
7. **Phase 5 is too wide.** Split into 5a/5b.
8. **Windows process-group support** is hand-waved to "before public release" — acceptable, but Phase 3 stop-gate should explicitly accept Unix-only.
9. **Run-id generation algorithm parity** is unspecified — if random-based, both CLIs must seed compatibly, or the harness must always normalize.
10. **`130` exit code** for interrupt may not exist in Python today; plan inherits an unproven claim.

---

## Status

COMPLETE. Plan is structurally sound and the build order (especially the runner-spike-early decision and stop-gate) is strong. The biggest weaknesses are (1) implicit dependence on a not-yet-done Python refactor for the package map, (2) unspecified error/output/CI machinery, and (3) an under-defined "parity passes" contract. None are fatal; all are addressable before Phase 0 begins.
