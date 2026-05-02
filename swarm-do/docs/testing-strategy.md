# Testing Strategy

This note describes the accepted testing direction for `swarm-do` after the
pytest adoption work in `../plans/pytest-adoption-plan.md`.

## Current Inventory

- Test runner: `pytest` is the canonical dev runner; the existing
  `unittest.TestCase` suite is still supported and collected by pytest.
- Current Python inventory after pytest adoption: 1,011 tests across 108
  `test_*.py` files under `py/swarm_do/**/tests/`, with about 23,758 lines of
  test code including shared helpers.
- Legacy fallback:
  `PYTHONPATH=py python3 -m unittest discover -s py -p 'test_*.py'` remains
  supported during migration for the files that still use `unittest`.
- Main covered areas: pipeline schemas/invariants, preset and pipeline
  persistence, CLI command functions, role generation, telemetry golden/parity
  behavior, extractor hashing/parsing, work-unit scheduling, worktree helpers,
  provider doctoring, resume/run-state, permissions, TUI state helpers, TUI
  app interaction tests, phase-pump orchestration, path canonicalization, and
  shell wrapper smoke coverage.

## Canonical Commands

From `swarm-do/`:

```bash
bin/swarm test unit
bin/swarm test tui
bin/swarm test shell
bin/swarm test all
```

Useful selection and reporting forms:

```bash
bin/swarm test -k path_resolution
bin/swarm test -m tui
bin/swarm test --coverage unit
bin/swarm test unit -- -x --pdb
```

Coverage is report-only. There is no fail-under threshold in this phase.

## Local Setup

Python dev dependencies:

```bash
python3 -m pip install -e '.[dev]'
python3 -m pip install -e '.[hypothesis]'
```

Shell test dependencies on macOS:

```bash
brew install bats-core shellcheck
```

If Homebrew is unavailable, install `bats-core` manually:

```bash
git clone https://github.com/bats-core/bats-core.git /tmp/bats
/tmp/bats/install.sh ~/.local
```

## Migration Policy

Pytest is the runner, not a mandate to rewrite the suite. New tests should use
pytest-style functions and fixtures. Existing `unittest.TestCase` files should
stay as-is unless the file is already being materially rewritten and pytest
removes real ceremony.

The current targeted migrations are complete:

- `py/swarm_do/tui/tests/test_app.py` is pytest-style and marked `tui`.
- `py/swarm_do/pipeline/tests/test_phase_pump.py` has been split into focused
  phase-pump modules plus a non-collected helper module.
- Path-resolution properties live beside the existing role path tests and use
  Hypothesis when the optional extra is installed.

## Shell Layer

`bin/swarm test shell` runs ShellCheck against regular files in `bin/`,
`bin/_lib/*.sh`, and `hooks/*.sh`, then runs Bats recursively under
`tests/shell/`. Missing `bats` or `shellcheck` is a hard local setup error with
an install hint.

## Source Notes

- pytest collects `unittest` suites during gradual migration:
  https://docs.pytest.org/en/stable/how-to/unittest.html
- pytest fixtures provide `tmp_path`, `monkeypatch`, and output capture:
  https://doc.pytest.org/en/latest/reference/fixtures.html
- coverage.py reads the `[tool.coverage.*]` config in `pyproject.toml`:
  https://coverage.readthedocs.io/
- Textual recommends pytest plus pytest-asyncio for headless `run_test()`:
  https://textual.textualize.io/guide/testing/
- Bats is suited to shell script behavior tests:
  https://bats-core.readthedocs.io/
- ShellCheck is the static check for the shell wrapper layer:
  https://www.shellcheck.net/
