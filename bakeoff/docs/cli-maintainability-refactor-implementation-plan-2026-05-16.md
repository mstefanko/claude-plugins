# CLI Maintainability Refactor - Implementation Plan

Date: 2026-05-16
Status: proposed
Scope: behavior-preserving beautification and maintainability refactor for the
Bakeoff CLI, command workflows, artifact helpers, provider prompts, and runner
internals

## Decision

Refactor Bakeoff toward the shape used by mature Python CLIs such as pipx,
pre-commit, pip, and coverage.py:

1. Keep `argparse` and the current zero-runtime-dependency posture.
2. Keep `bakeoff.cli:main` as the public console-script entry point.
3. Make `src/bakeoff/cli.py` a thin parser, dispatcher, and top-level error
   boundary.
4. Move command behavior, ledger helpers, JSON summaries, output formatting,
   decision resolution, and prompt rendering into focused modules.
5. Keep each commit small enough to land directly on `main` with the full test
   suite passing.

This should be a refactor, not a feature rewrite. The user-facing CLI should
remain stable unless a phase explicitly calls out a small intentional cleanup.

## Why This Shape

The external codebases point in the same direction:

- pipx documents `main.py` as parser/dispatch and `commands/` as the command
  implementation package.
- pre-commit keeps a small `main.py` dispatcher and command-specific modules,
  while preserving a low-dependency `argparse` style.
- pip uses a heavier command class framework, but the useful lesson is the same:
  command lifecycle, option parsing, and error handling have a defined home.
- coverage.py keeps command-line code in one class, but delegates most real work
  into library APIs. Bakeoff currently keeps too much real work inside
  `cli.py`.

Bakeoff should copy the modular boundary, not the dependencies or framework
weight.

## Patterns To Fold In

Use these external patterns in the implementation, with Bakeoff-specific
exit-code semantics:

- pip-style lazy command registry: `cli.py` should dispatch through a small
  table such as
  `{"research": ("bakeoff.commands.research", "cmd_research", True)}` and
  load command modules with `importlib.import_module()` only when selected.
  This reduces circular import pressure and keeps startup cheap.
- pre-commit-style top-level error boundary: wrap `main()` dispatch in one
  context/helper that maps `ValidationError` to Bakeoff usage/config exit `2`,
  `KeyboardInterrupt` to `130`, and unexpected internal exceptions to `1` with
  a concise stderr message plus an optional diagnostic file. Do not copy
  pre-commit's numeric mapping because Bakeoff already reserves `3` for
  unresolved judge disagreement.
- httpie-style output environment: introduce a tiny `Output` object with
  `stdout`, `stderr`, `quiet`, and `json_mode`. Thread it through command
  modules so `if human_output: print(...)` branches shrink into explicit
  output calls.
- coverage.py-style parser option helpers: add small helpers such as
  `_add_out_option`, `_add_quiet_option`, and `_add_json_option` in `cli.py` so
  repeated subparser options are defined once.

## Current Baseline

- `src/bakeoff/cli.py` is 2,018 lines and owns parser setup, dispatch,
  research orchestration, triage orchestration, JSON summary building, ledger
  verification, output formatting, path safety, status shaping, and decision
  merging.
- Largest functions in `cli.py`:
  - `run_triage`: 168 lines.
  - `run_research`: 140 lines.
  - `cmd_doctor`: 96 lines.
  - `verify_run_ledger`: 84 lines.
  - `run_workers`: 76 lines.
  - `run_judge_phase`: 73 lines.
- `src/bakeoff/runner.py` is cohesive but dense. `run_provider()` is 413 lines
  with nested helpers for subprocess lifecycle, byte capture, output caps,
  final JSON extraction, heartbeats, and status construction.
- JSON helpers are duplicated:
  - `src/bakeoff/cli.py::read_json`
  - `src/bakeoff/triage.py::read_json`
  - `src/bakeoff/manifest.py::_read_json`
- Artifact path vocabulary is duplicated across CLI summary helpers and
  `manifest.py`.
- Direct `print()` calls are scattered across command code, which makes quiet
  mode, JSON mode, stderr discipline, and next-step hints harder to reason
  about.
- Tests import helpers from `bakeoff.cli`, which means `cli.py` has become an
  accidental public module for domain internals.

## Non-Goals

- Do not switch to Click, Typer, Rich, Pydantic, dataclasses everywhere, or a
  plugin framework.
- Do not adopt pip's command class hierarchy, cleo/Application-style command
  frameworks, `argparse.set_defaults(func=...)`, or a plugin manager.
- Do not change the work-order schema in this refactor.
- Do not change the run artifact layout unless a phase explicitly says the
  change is an alias-preserving cleanup.
- Do not redesign provider topology, prompt contracts, triage policy, or
  judging semantics.
- Do not add streaming events, config files, caches, pruning, dashboards, or
  SQLite.
- Do not remove `bakeoff.cli` helper exports until downstream tests and docs
  have been migrated in the same commit.

## Target File Map

Keep existing files where they are already cohesive:

- `src/bakeoff/io.py`
  - Atomic writes.
  - Shared JSON text formatting.
  - Shared optional/required JSON readers.
- `src/bakeoff/manifest.py`
  - Manifest construction and manifest-backed listing rows.
- `src/bakeoff/report.py`
  - Markdown report rendering.
- `src/bakeoff/review_context.py`
  - Git review-context capture and rendering.
- `src/bakeoff/triage.py`
  - Triage source selection, citation checks, triage freshness, triage markdown.
- `src/bakeoff/work_order.py`
  - Work-order loading, normalization, and final JSON schema validation.

Add or split into these files:

- `src/bakeoff/output.py`
  - `Output`, plus compatibility `_note`, `_warn`, `print_json_summary`.
  - `format_heartbeat_line`, `format_kb`, `make_tick_printer`.
  - Human rendering helpers that do not need command state.
- `src/bakeoff/commands.py` or `src/bakeoff/command_hints.py`
  - `bakeoff_show_command`, `bakeoff_triage_command`,
    `bakeoff_rerun_command`, and `out_dir_suffix`.
  - Prefer `command_hints.py` if `commands/` package exists, to avoid name
    ambiguity.
- `src/bakeoff/ledger.py`
  - `RUN_ID_RE`, `make_run_id`, `utc_now`.
  - `validate_run_id`, `resolve_run_dir`, `update_latest_symlink`.
  - `ensure_child_path`, run-id path safety helpers, and artifact path helpers.
  - `research_artifact_paths` and `triage_artifact_paths`.
- `src/bakeoff/summaries.py`
  - `command_status`, `compact_status`, `provider_status_summary`.
  - `judge_json_summary`, `research_triage_summary`.
  - `build_research_json_summary`, `build_triage_json_summary`.
- `src/bakeoff/verification.py`
  - `validate_verify_run_id`, `verify_run_ledger`,
    `verify_fingerprint_entry`, `runs_verify_next`.
  - Human verify rendering can live here or in `output.py`; choose one and keep
    it consistent.
- `src/bakeoff/decisions.py`
  - `resolve_compare_decision`, `resolve_analyze_decision`,
    `decision_base`, `judge_pass_summary`.
  - `canonical_winner`, `annotate_source`, `merge_items`, near-duplicate
    helpers, and single-provider caveat helpers.
- `src/bakeoff/artifacts.py`
  - `codex_final_message_path`, `status_without_payload`,
    `auth_probe_status`, `write_provider_artifacts`,
    `write_format_retry_artifacts`, `write_meta`.
  - This module may depend on `providers`, `runner`, `triage`, and `io`, but
    avoid importing command modules from it.
- `src/bakeoff/prompts.py`
  - Large prompt template constants and prompt rendering helpers currently in
    `providers.py`.
- `src/bakeoff/scope.py`
  - Scope enforcement helpers currently in `providers.py`, if splitting
    `providers.py` becomes worthwhile after command extraction.
- `src/bakeoff/commands/`
  - `__init__.py`
  - `context.py` for frozen command/run context objects used at module
    boundaries.
  - `init.py`
  - `validate.py`
  - `research.py`
  - `triage.py`
  - `runs.py`
  - `show.py`
  - `doctor.py`

Keep `src/bakeoff/cli.py` responsible for:

- `ORIENTATION` and root help epilog.
- `build_parser()`.
- `main()`.
- A small dispatch table from parsed command names to command handlers.
- Top-level `ValidationError` and `KeyboardInterrupt` mapping.
- Parser option helper functions for repeated flags.

## Compatibility Rule

During the refactor, keep temporary compatibility imports in `cli.py` for
helpers currently imported by tests:

- `_note`
- `_warn`
- `resolve_compare_decision`
- `resolve_run_dir`
- `validate_run_id`
- `format_heartbeat_line`
- `make_tick_printer`
- `merge_items`
- `status_without_payload`
- `write_json`

Each compatibility import should have a clear removal target in the same commit
that migrates tests. Do not leave stale wrappers indefinitely.

The temporary `cli.write_json(path, data)` alias should preserve the old public
shape, including returning `None`, but it should upgrade the implementation to
delegate to `io.write_json_atomic(path, data)`. In other words: preserve call
semantics, improve write safety.

## Helper Routing Table

Route these smaller helpers during extraction so Commit 7 does not inherit an
unbounded cleanup bucket:

| Current helper | Target |
| --- | --- |
| `bakeoff_show_command`, `bakeoff_triage_command`, `bakeoff_rerun_command`, `out_dir_suffix`, `format_stale_inputs` | `command_hints.py` |
| `_note`, `_warn`, `print_json_summary`, `format_heartbeat_line`, `format_kb`, `make_tick_printer`, `print_validation_summary`, `print_run_header`, `format_budget_summary` | `output.py` |
| `make_run_id`, `utc_now`, `update_latest_symlink`, `resolve_run_dir`, `validate_run_id`, `ensure_child_path`, run-id path helpers, artifact path helpers | `ledger.py` |
| `validate_verify_run_id`, `verify_run_ledger`, `verify_fingerprint_entry`, `runs_verify_next`, `print_runs_verify_human` | `verification.py` |
| `resolve_compare_decision`, `resolve_analyze_decision`, `decision_base`, `judge_pass_summary`, `canonical_winner`, `annotate_source`, `preserved_compare_material`, `merge_items`, `merge_item_key`, `merge_item_text_and_source`, `is_near_duplicate`, `token_similarity`, `merge_tokens`, `numeric_tokens`, `normalize_merge_text`, `single_provider_caveat`, `_rationale` | `decisions.py` |
| `codex_final_message_path`, `status_without_payload`, `auth_probe_status`, `last_nonempty_line`, `diagnostic_tail`, `write_provider_artifacts`, `write_format_retry_artifacts`, `write_meta`, `internal_error_result`, `scope_error_result` | `artifacts.py` |
| `cleanup_scope_paths`, `judge_validator`, `copy_replay_context_artifacts` | `commands/research.py` |
| `print_missing_judge_artifacts` | `commands/show.py` |
| `filter_ls_rows` | `commands/runs.py` |
| `check_cwd_writable`, `tool_version` | `commands/doctor.py` |

## Suggested Commit Sequence

Each commit should build on `main`, pass targeted tests, and ideally pass the
full suite before the next commit lands.

### Commit 1: Shared IO, Output, And Command Hints

Goal: remove small duplication and create safe landing zones before moving
large workflows.

Files to add or update:

- `src/bakeoff/io.py`
  - Add `read_optional_json(path) -> Any`.
  - Add `read_required_json(path) -> dict[str, Any]`.
  - Preserve existing atomic write helpers.
- `src/bakeoff/output.py`
  - Add an `Output` object with `stdout`, `stderr`, `quiet`, and `json_mode`.
  - Move `_note`, `_warn`, `print_json_summary`, `format_kb`,
    `format_heartbeat_line`, and `make_tick_printer` from `cli.py`.
  - Keep `_note` and `_warn` callable through `bakeoff.cli` until tests move.
- `src/bakeoff/command_hints.py`
  - Move `bakeoff_show_command`, `bakeoff_triage_command`,
    `bakeoff_rerun_command`, and `out_dir_suffix`.
- `src/bakeoff/cli.py`
  - Import and re-export moved helpers for compatibility.
  - Replace local helper bodies with imports.
  - Add parser option helpers for repeated `--out`, `--quiet`, and `--json`
    definitions.
  - Keep `write_json(path, data)` as a compatibility alias that delegates to
    `write_json_atomic(path, data)`.
- `src/bakeoff/triage.py`
  - Replace the local `read_json()` copy with shared IO helpers where the
    current missing/invalid-JSON behavior matches.
- `tests/test_io.py`
  - Add shared JSON reader tests for missing, invalid, and required object
    behavior.
- `tests/test_cli_helpers.py`
  - Update imports to use `bakeoff.output` or keep compatibility assertions
    until the later test-migration commit.

Done criteria:

- No behavior change in command outputs.
- `tests/test_cli_helpers.py::test_note_and_warn_write_to_stderr` still passes
  through the temporary `bakeoff.cli._note` and `bakeoff.cli._warn` aliases.
- `pytest tests/test_io.py tests/test_cli_helpers.py` passes.
- Full `pytest` passes before commit.

Suggested commit message:

```text
Refactor shared CLI output and JSON helpers
```

### Commit 2: Ledger, Artifact Paths, And Verification

Goal: move run-directory and verification logic out of `cli.py`.

Files to add or update:

- `src/bakeoff/ledger.py`
  - Move run id validation, latest resolution, symlink update, path safety,
    `make_run_id`, `utc_now`, and artifact path helpers.
- `src/bakeoff/verification.py`
  - Move `verify_run_ledger`, fingerprint verification, verify run-id
    validation, next-command selection, and human verify output.
- `src/bakeoff/manifest.py`
  - Reuse shared JSON readers where semantics match.
  - Keep manifest-specific strict errors when useful.
- `src/bakeoff/cli.py`
  - Import moved ledger and verification helpers.
  - Keep compatibility re-exports for tests if needed.
- `tests/test_manifest.py`
- `tests/test_modes_end_to_end.py`
- `tests/test_decisions.py`

Done criteria:

- `bakeoff ls`, `bakeoff show`, and `bakeoff runs verify` behavior is
  unchanged.
- `pytest tests/test_manifest.py tests/test_modes_end_to_end.py` passes.
- Full `pytest` passes before commit.

Suggested commit message:

```text
Extract run ledger and verification helpers
```

### Commit 3: Decision And Summary Modules

Goal: separate domain decision logic and machine summary shaping from command
execution.

Files to add or update:

- `src/bakeoff/decisions.py`
  - Move compare/analyze resolution, merge/deduping helpers, caveat helpers,
    and `decision_base`.
- `src/bakeoff/summaries.py`
  - Move command status, provider status summaries, judge summaries, research
    summaries, and triage summaries.
- `src/bakeoff/cli.py`
  - Import the moved helpers.
  - Keep short compatibility imports only for tests not yet migrated.
- `tests/test_decisions.py`
  - Import from `bakeoff.decisions`.
- `tests/test_cli_helpers.py`
  - Move `merge_items` imports to `bakeoff.decisions`.
- `tests/test_runner.py`
  - Do not import status shaping from `cli.py` after `artifacts.py` exists, or
    keep a temporary compatibility import until Commit 4.

Done criteria:

- Decision JSON and report content are unchanged for all fake-provider tests.
- `pytest tests/test_decisions.py tests/test_cli_helpers.py tests/test_modes_end_to_end.py` passes.
- Full `pytest` passes before commit.

Suggested commit message:

```text
Extract decision resolution and summary builders
```

### Commit 4: Artifact Writers And Command Modules

Goal: shrink `cli.py` substantially while preserving `bakeoff.cli:main`.

Files to add or update:

- `src/bakeoff/artifacts.py`
  - Move status shaping, final-message path helper, provider artifact writing,
    format retry artifact writing, auth probe status, and meta writing.
- `src/bakeoff/commands/__init__.py`
- `src/bakeoff/commands/context.py`
  - Add a frozen `RunContext` or small `NamedTuple` for shared command/run
    boundary state such as `out_dir`, `run_id`, `quiet`, `json_output`, and
    `Output`.
  - Add narrow research/triage option context objects only if they remove
    repeated argument threading.
- `src/bakeoff/commands/init.py`
  - `cmd_init`.
- `src/bakeoff/commands/validate.py`
  - `cmd_validate` and validation summary output if not already in
    `output.py`.
- `src/bakeoff/commands/show.py`
  - `cmd_show` and missing judge artifact display.
- `src/bakeoff/commands/runs.py`
  - `cmd_ls`, `filter_ls_rows`, `cmd_runs_verify`.
- `src/bakeoff/commands/doctor.py`
  - `cmd_doctor`, `check_cwd_writable`, `tool_version`.
- `src/bakeoff/commands/research.py`
  - `cmd_research`, `cmd_rerun`, `run_research`, `run_workers`,
    `run_judge_phase`, and `run_single_judge`.
- `src/bakeoff/commands/triage.py`
  - `cmd_triage` and `run_triage`.
- `src/bakeoff/cli.py`
  - Keep parser construction and dispatch only.
  - Use a lazy command registry with `importlib.import_module()`:

    ```python
    COMMAND_HANDLERS = {
        "init": ("bakeoff.commands.init", "cmd_init", False),
        "research": ("bakeoff.commands.research", "cmd_research", True),
    }
    ```

  - Dispatch through a small sync/async helper rather than spreading
    `asyncio.run(...)` branches through `main()`.
- Tests
  - Update imports away from `bakeoff.cli` for moved internals.
  - Keep `main` and `build_parser` imports from `bakeoff.cli`.

Done criteria:

- `src/bakeoff/cli.py` is mostly parser, dispatch, and error mapping.
- `run_research` and `run_triage` no longer grow their already-wide argument
  lists during the move; new cross-module state goes through `RunContext` or a
  narrower sibling context.
- `bakeoff --help` and every subcommand help still work.
- `pytest tests/test_cli_helpers.py tests/test_modes_end_to_end.py tests/test_triage.py tests/test_runner.py` passes.
- Full `pytest` passes before commit.

Suggested commit message:

```text
Move CLI command implementations into command modules
```

### Commit 5: Provider Prompt And Scope Split

Goal: make provider-related code easier to scan without changing prompts.

Files to add or update:

- `src/bakeoff/prompts.py`
  - Move prompt template constants and prompt rendering functions:
    `build_worker_prompt`, `build_judge_prompt`, `build_triage_prompt`,
    `render_runtime_budget_block`, facet rendering helpers, and schema strings.
- `src/bakeoff/scope.py`
  - Move `ScopeEnforcementError`, scope capability detection, scope help
    parsing, `build_scope_execution`, temp scope workspace helpers, and
    scope constants.
- `src/bakeoff/providers.py`
  - Keep provider backend argv and version helpers, or become a compatibility
    facade that re-exports from `prompts.py` and `scope.py` during migration.
  - The compatibility facade must explicitly preserve the current imports used
    by tests and internal modules:
    - provider/backend exports: `DEFAULT_MODEL_IDS`, `build_participant_argv`,
      `version_argv`, `codex_exec_supports_output_last_message`,
      `codex_exec_supports_output_last_message_from_help`,
      `anonymized_worker_output`.
    - prompt exports: `SCOPE_INSTRUCTIONS`, `RUNTIME_BUDGET_ROLES`,
      `WORKER_RESULT_SCHEMA`, `TRIAGE_RESULT_SCHEMA`, `TRIAGE_PROMPT`,
      `GATHER_WORKER_PROMPT`, `COMPARE_WORKER_PROMPT`,
      `ANALYZE_WORKER_PROMPT`, `GATHER_JUDGE_PROMPT`,
      `COMPARE_JUDGE_PROMPT`, `ANALYZE_JUDGE_PROMPT`,
      `render_runtime_budget_block`, `build_worker_prompt`,
      `build_judge_prompt`, `build_triage_prompt`, `render_facet_block`,
      `render_worker_facet_rules`, `render_judge_facet_rules`.
    - scope exports: `ScopeEnforcementError`, `SCOPE_POLICY_DEFAULT`,
      `SCOPE_POLICY_VALUES`, `detect_scope_capabilities`, `scope_help_argv`,
      `scope_capabilities_from_help`, `help_option_tokens`,
      `has_help_option`, `build_scope_execution`, `make_scope_workspace`,
      `safe_temp_prefix`.
- `tests/test_prompts.py`
  - Either update imports to `bakeoff.prompts` in this commit, or prove the
    `bakeoff.providers` facade covers the old imports until Commit 7.
- `tests/test_scope_enforcement.py`
  - Either update imports and monkeypatch paths to `bakeoff.scope`, or prove
    the `bakeoff.providers` facade covers the old imports and monkeypatch path
    until Commit 7.

Implementation rule:

- Do this as pure moves first. Do not rewrite prompt text, indentation, or JSON
  schema wording in the same commit.
- If prompt snapshots or string tests change, stop and inspect; changed prompt
  text should be intentional and documented.

Done criteria:

- Prompt output is byte-for-byte unchanged except import paths.
- Existing imports from `bakeoff.providers` do not break during the split.
- Scope enforcement tests pass.
- Full `pytest` passes before commit.

Suggested commit message:

```text
Split prompt rendering and scope enforcement modules
```

### Commit 6: Runner Internal Decomposition

Goal: make `run_provider()` easier to change without altering process behavior.

Files to add or update:

- `src/bakeoff/runner.py`
  - Extract private helpers or small private classes for:
    - stdout capture buffer and tail preservation.
    - stderr capture cap.
    - IO/heartbeat state snapshot.
    - output cap metadata.
    - subprocess termination and task settling.
  - Keep public API stable:
    - `extract_final_json`
    - `run_provider`
    - `run_provider_with_format_retry`
    - `provider_succeeded`

Recommended internal shapes:

```python
class OutputCapture:
    ...

class ProviderIOState:
    ...
```

Do not introduce dataclasses unless they reduce boilerplate in practice. Plain
small classes or private functions are fine.

Done criteria:

- `run_provider()` is shorter and reads as orchestration rather than byte-buffer
  mechanics.
- Existing timeout, output cap, final-message, heartbeat, repair retry, and
  schema error tests pass.
- `pytest tests/test_runner.py` passes.
- Full `pytest` passes before commit.

Suggested commit message:

```text
Decompose provider runner internals
```

### Commit 7: Test Import Cleanup, Error Boundary, And Compatibility Removal

Goal: remove the temporary compatibility clutter left behind by the extraction
and install the final top-level error boundary.

Files to update:

- `src/bakeoff/cli.py`
  - Remove compatibility exports for internals that tests no longer import.
  - Keep only `build_parser` and `main` as intentional public CLI functions.
  - Add the final pre-commit-style error boundary helper/context manager:
    `ValidationError` -> `2`, `KeyboardInterrupt` -> `130`, unexpected
    exception -> `1`.
  - For unexpected internal exceptions, print a concise `error:` line to stderr
    and write a diagnostic traceback file under a predictable temp location or
    run-local location when a run directory is already known.
- Tests
  - Import helpers from their domain modules.
- `README.md`
  - Update developer notes if command modules are worth mentioning.
- `CLAUDE.md`
  - Update codebase orientation only if it currently points contributors at
    `cli.py` as the main place to edit command behavior.

Done criteria:

- `rg "from bakeoff.cli import"` in `tests/` returns only `main` and
  `build_parser`, unless there is a clear reason for another CLI-level helper.
- Uncaught internal exceptions no longer dump raw tracebacks in ordinary CLI
  usage; tests cover the new error-boundary mapping.
- Full `pytest` passes.

Suggested commit message:

```text
Clean up CLI compatibility imports and error handling
```

## Build Order Summary

Use this order on `main`:

1. Shared IO, output, and command hints.
2. Ledger, artifact paths, and verification.
3. Decisions and summaries.
4. Artifact writers and command modules.
5. Prompt and scope split.
6. Runner internal decomposition.
7. Compatibility cleanup, error boundary, and docs orientation.

This order keeps low-risk extraction work ahead of the larger command split,
and keeps the runner refactor last because it has the most subtle runtime
behavior.

## Validation Checklist

Run targeted tests during each commit, then the full suite before committing:

```text
pytest
```

Useful targeted commands:

```text
pytest tests/test_io.py tests/test_cli_helpers.py
pytest tests/test_manifest.py tests/test_modes_end_to_end.py
pytest tests/test_decisions.py tests/test_report.py
pytest tests/test_prompts.py tests/test_scope_enforcement.py
pytest tests/test_runner.py
pytest tests/test_triage.py
```

Manual smoke checks after Commit 4:

```text
bakeoff --help
bakeoff init gather --force
bakeoff validate gather.work-order.json
bakeoff ls --json
bakeoff doctor --skip-auth-probe --json
```

Do not run spendful provider calls as part of the refactor unless a separate
dogfood run is explicitly requested.

## Risk Notes

- The command-module split can accidentally create circular imports. Keep shared
  helpers in low-level modules (`io`, `ledger`, `output`, `command_hints`) and
  keep command modules at the top of the dependency graph.
- Prompt moves are deceptively risky because whitespace and wording are product
  behavior. Move first, rewrite later.
- Runner decomposition is the highest-risk phase. Preserve public return
  dictionaries and status fields exactly.
- Compatibility re-exports are useful during migration, but leaving them behind
  recreates the junk-drawer problem. Remove them in the cleanup commit.
- This plan assumes no external consumers import Bakeoff internals except tests.
  If that assumption proves false, keep compatibility aliases longer and
  document them.

## Deferred Cleanups

Do these only after the refactor lands and dogfood confirms the new structure:

- Consider a tiny command registry object if dispatch grows beyond simple
  functions.
- Consider moving human output rendering for reports and validation summaries
  into `output.py` if command modules still feel noisy.
- Consider replacing manual prompt `.replace()` chains with `string.Template`,
  but only after prompt output tests lock the exact text.
