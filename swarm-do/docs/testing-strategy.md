# Testing Strategy

This note answers the current testing question for `swarm-do`: whether the
suite needs pytest or a larger refactor, what it already catches, and where it
will miss bugs that users would hit in normal operation.

## Current Inventory

- Test runner: `unittest`.
- Passing baseline checked on 2026-04-25:
  `python3 -m unittest discover -s py -p 'test_*.py'` ran 301 tests with 1
  skipped test.
- Test files: 44 `test_*.py` files under `py/swarm_do/**/tests/`.
- Approximate test code size: 6,141 lines including shared helpers.
- Main covered areas: pipeline schemas/invariants, preset and pipeline
  persistence, CLI command functions, role generation, telemetry golden/parity
  behavior, extractor hashing/parsing, work-unit scheduling, worktree helpers,
  provider doctoring, resume/run-state, permissions, and TUI state helpers.
- Not present today: `pytest` config, `pyproject.toml`, coverage config,
  shell-test harness, ShellCheck gate, Bats tests, Textual `run_test()`/Pilot
  interaction tests, or a single repo-level smoke command.

## What Is Working

The current suite is better than a token unit-test layer. It exercises real
user-facing contracts in several places:

- Preset and pipeline operations use temporary `${CLAUDE_PLUGIN_DATA}` roots,
  write actual TOML/YAML files, reload them, and reject invalid saves.
- Telemetry tests compare command output to golden fixtures and validate schema
  behavior against realistic ledger directories.
- Pipeline validation covers stage graph ordering, fan-out semantics, prompt
  variant/lens rules, MCO provider constraints, backend route invariants, and
  preview-only activation guards.
- Worktree tests shell out to `git` in temporary repositories, so branch and
  merge helpers are not purely mocked.
- TUI state tests cover the model layer without requiring Textual, which keeps
  most status, preset, pipeline, and provider preview logic cheap to test.
- Generator tests guard README and telemetry docs sections against drift.

This suite should catch many refactor regressions in deterministic Python
helpers, especially around schemas, routing, persistence, and telemetry.

## Gaps That Matter

- There is no top-level command that a maintainer can run to mean "the plugin
  is healthy." Different entrypoints test different subsets.
- Slash-command behavior is mostly documented prompt protocol; the executable
  coverage stops at deterministic helper functions and command files.
- Shell wrappers in `bin/` are only lightly exercised through Python parity
  tests and ad hoc `--test` flags. There are no Bats tests with stubbed `bd`,
  `claude`, `codex`, or `mco` commands.
- No ShellCheck gate exists for the bash-heavy wrapper layer.
- The Textual app itself is not driven headlessly. State helpers are covered,
  but keyboard flows, screen transitions, save/discard interactions, and visual
  regressions are not.
- No coverage report exists, so we do not know which modules are dark. This is
  especially relevant for `py/swarm_do/tui/app.py`, shell-adjacent paths, and
  error branches.
- Parser-heavy code such as simple YAML, plan inspection, work-unit linting,
  and path normalization would benefit from property-style or larger corpus
  tests.
- The full suite currently emits noisy expected-drift output and Python 3.13
  `ResourceWarning` messages about unclosed sqlite connections. The suite still
  passes, but noisy green runs make real failures easier to miss.

## Do We Need pytest?

Not as an immediate wholesale migration. The existing `unittest` suite passes,
is discoverable with the standard library, and already covers a lot of real
contracts.

We should add pytest as a dev-only runner when we start the next test refactor.
The reason is practical, not fashionable: pytest can run existing
`unittest.TestCase` tests during a gradual migration, and its fixtures,
`tmp_path`, `monkeypatch`, output capture, parametrization, and plugin ecosystem
fit the missing coverage areas. Textual's official testing guide also uses
pytest plus `pytest-asyncio` for headless app interaction tests.

The right move is incremental:

1. Keep all current `unittest` tests green.
2. Add dev test tooling without making plugin runtime depend on it.
3. Write new scenario, shell, and Textual interaction tests in pytest style.
4. Convert old tests only when they are being touched for real reasons.

## Recommended Refactor Path

1. Add a dev test command.
   A small `scripts/test.sh` or `bin/swarm-selftest` should run the full Python
   suite, generator drift checks, key CLI dry-runs, and optional shell checks.

2. Add dev dependencies.
   A minimal dev set would be `pytest`, `pytest-asyncio`, `coverage`, and
   `ruff`. Add `hypothesis` only for parser/path invariants, not by default.

3. Add coverage reporting.
   Start with report-only branch coverage. Do not gate on a percentage until
   the current blind spots are intentionally triaged.

4. Add shell coverage.
   Use ShellCheck for static checks and Bats for `bin/` behavior. The Bats
   tests should run wrappers with temporary `CLAUDE_PLUGIN_DATA` and stubbed
   command directories on `PATH`.

5. Add Textual interaction tests.
   Keep state tests, then add pytest-asyncio tests using `App.run_test()` and
   Pilot for navigation, shortcuts, route edits, save/discard, and provider
   preview flows. Add `pytest-textual-snapshot` later if visual drift becomes a
   recurring problem.

6. Add scenario smoke tests.
   Cover actual operator flows without live agents:
  `bin/swarm research --dry-run`, `bin/swarm design --dry-run`,
  `bin/swarm review --dry-run`, `bin/swarm prepare <plan-path> --dry-run`,
  `bin/swarm plan prepare <plan-path> --dry-run --json`,
  `bin/swarm preset dry-run`, permission dry-runs, provider doctor with stubbed
  executables, run-state checkpoint, resume manifests, and work-unit batching.

7. Clean current green-run noise.
   Fix the sqlite `ResourceWarning` sources and keep expected drift output
   buffered or scoped so successful runs are quiet.

## Source Notes

External guidance checked while writing this:

- Python `unittest` supports standard-library test discovery.
  https://docs.python.org/3/library/unittest.html
- pytest can run `unittest` suites and supports gradual migration, with limits
  around directly injecting fixtures into `unittest.TestCase` methods.
  https://docs.pytest.org/en/stable/how-to/unittest.html
- pytest fixtures provide useful built-ins such as `tmp_path`, `monkeypatch`,
  and output capture for scenario-style tests.
  https://doc.pytest.org/en/latest/reference/fixtures.html
- coverage.py measures which code and branches tests exercise.
  https://coverage.readthedocs.io/
- Textual recommends pytest plus pytest-asyncio for headless `run_test()` and
  Pilot-driven interaction tests.
  https://textual.textualize.io/guide/testing/
- Bats is a TAP-compliant Bash test framework suited to shell scripts and UNIX
  commands.
  https://bats-core.readthedocs.io/
- ShellCheck is a static analysis tool for shell scripts.
  https://www.shellcheck.net/
