# CLI Audit Hygiene - Implementation Plan

Date: 2026-05-16
Status: revised
Scope: small operator-facing CLI hardening for docs, exit codes, stderr
discipline, final JSON summaries, run verification, atomic artifact writes, and
NO_COLOR behavior

## Decision

Ship the smallest set of CLI changes that improve Bakeoff's actual product
promise: auditable research runs that humans and scripts can inspect, replay,
and trust.

This is not a general CLI platform pass. Do not add a config layer, streaming
events, templating, cache pruning, command-package refactors, or global
strict-warning policy. Each accepted item must improve one of:

- auditability
- scripting
- recovery

The accepted v1 scope is:

1. Fix review-doc drift and add a tiny README common-workflows quickstart.
2. Document and align a tiny exit-code matrix.
3. Route notes and warnings to stderr through helper functions.
4. Add final `--json` summaries to `research`, `triage`, and `runs verify`.
5. Add `bakeoff runs verify <run-id>`.
6. Move existing atomic-write helpers to shared IO and make all artifact writes
   atomic.
7. Honor `NO_COLOR` by keeping output ANSI-free and testing that contract.

## Implementation Order

All items touch `src/bakeoff/cli.py`, so do the work in this order:

1. Atomic-write migration.
2. Exit-code behavior.
3. Stderr `_note()` / `_warn()` helpers.
4. Final `--json` summaries for `research` and `triage`.
5. `runs verify` command and JSON/human output.
6. README and `examples/review.work-order.json` drift fixes.
7. `NO_COLOR` regression test.

This order keeps the artifact-writing substrate stable before new summary and
verification surfaces depend on it.

## Current Baseline

Current code references as of this plan:

- `src/bakeoff/cli.py` already has `write_json_atomic()`,
  `write_text_atomic()`, and `copy_file_atomic()` near the replay-context copy
  helper.
- `src/bakeoff/cli.py` also has a separate non-atomic `write_json()` helper
  near the bottom of the file. That helper writes with `Path.write_text()` and
  is still used by artifact-writing call sites.
- `src/bakeoff/manifest.py` writes `manifest.json` with inline
  `NamedTemporaryFile` plus `os.replace()`.
- `research` returns `2` for `both_failed` today.
- compare runs where position-swap judging resolves to `decision_kind == "tie"`
  return `0` today.
- `doctor --json` already returns a `warnings: []` array, but it does not
  include a `command` field.

## User Surface

Update the command surface to:

```text
bakeoff research <work-order> [--out runs] [--run-id ID] [--force] [--quiet]
  [--no-triage] [--base REF] [--diff] [--changed-files] [--json]
bakeoff triage <run-id> [--out runs] [--force] [--dry-run] [--quiet] [--json]
bakeoff runs verify <run-id> [--out runs] [--json]
```

Register a `runs` command group in top-level help. `bakeoff runs --help` must
list `verify`.

Do not add `--jq`, `--template`, `--color`, `--config`, `runs prune`,
`runs dir`, or NDJSON event streaming in this pass.

## Atomic Artifact Writes

Create `src/bakeoff/io.py` and move the existing atomic helpers out of
`cli.py` to avoid circular imports:

```python
def json_text(data: Any, *, sort_keys: bool = True) -> str:
    return json.dumps(data, indent=2, sort_keys=sort_keys) + "\n"

def write_text_atomic(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    ...

def write_json_atomic(path: Path, data: Any, *, sort_keys: bool = True) -> None:
    write_text_atomic(path, json_text(data, sort_keys=sort_keys))

def copy_file_atomic(source: Path, destination: Path) -> None:
    ...
```

Implementation details:

- Create the temp file in `path.parent`.
- Use a hidden temp name based on the target filename.
- Write, flush, and `os.fsync()` the temp file before replacement.
- Replace with `os.replace(tmp_name, path)`.
- Best-effort unlink the temp file in `finally` if replacement did not happen.
- Do not add dependencies.
- Keep artifact JSON sorted with `sort_keys=True`.
- Use `sort_keys=False` only for stdout JSON summaries where field order is
  part of readability.

`manifest.py` migration:

- Replace the inline tempfile/`os.replace()` manifest writer with
  `write_json_atomic(run_dir / "manifest.json", manifest)`.
- Remove the now-unused local tempfile/os imports from `manifest.py`.

`cli.py` JSON migration list:

- `run_research`: `decision.json`.
- `run_triage`: `triage/source_finding_filter.json`,
  `triage/finding_index.json`, `triage/citation_checks.json`,
  dry-run `triage/status.json`, non-dry-run `triage/status.json`,
  `triage/final.json`.
- `run_single_judge`: `judge/status*.json`, `judge/result*.json`.
- `write_provider_artifacts`: `providers/<id>/status.json`,
  `providers/<id>/final.json`.
- `write_meta`: `meta.json`.
- `write_format_retry_artifacts`: `repair-status*.json`.

Current direct call sites to audit are the `write_json(...)` calls around
`cli.py:605`, `671`, `682`, `685`, `717`, `769`, `775`, `951`, `953`, `1301`,
`1303`, `1345`, and `1416`.

Implementation rule:

- Either replace each listed caller with `write_json_atomic(...)`, or make the
  existing `write_json(...)` name a thin compatibility wrapper around
  `write_json_atomic(...)` and leave no direct `Path.write_text()` JSON helper
  in `cli.py`.
- Prefer also migrating direct Bakeoff-generated text artifacts to
  `write_text_atomic(...)`: `report.md`, prompts, stdout/stderr captures,
  repair text artifacts, generated init templates, and review-context markdown.

Done criteria:

- `manifest.py` delegates manifest writes to shared IO.
- No Bakeoff artifact JSON is written with direct `Path.write_text()`.
- Tests cover successful atomic replacement and cleanup after a simulated write
  or replace failure.
- Existing artifact JSON formatting remains `indent=2, sort_keys=True`.

## Exit Codes

Define the v1 matrix:

```text
0  success
1  generic runtime or verification failure
2  usage, config, validation, or missing-input error
3  completed run with unresolved judge disagreement
```

Document the matrix in the root argparse epilog and in README. The epilog is
enough; do not add a new help command.

Implementation details:

- Keep `ValidationError` mapped to `2`.
- Keep argparse usage errors mapped to `2`.
- Keep `doctor` missing-tool/readiness failure mapped to `1`.
- Change completed run ledgers where provider or judge execution failed without
  producing a valid judged decision from `2` to `1`. This includes
  `decision_kind == "both_failed"` and failed judge provider calls.
- Change completed compare runs where judging succeeded but resolved to
  `decision_kind == "tie"` from `0` to `3`.
- Do not use `3` for compare consensus, single-provider-only caveats, analyze
  tiebreaks that still select a spine, dry-run triage, stale-triage display
  warnings, or validation failures.

Existing tests that must flip:

- Rename/update `tests/test_modes_end_to_end.py::test_both_failed_exits_two` to
  expect exit `1`.
- Update `tests/test_modes_end_to_end.py::test_compare_position_swap_catches_position_bias`
  to expect exit `3`.
- Leave `tests/test_decisions.py::test_compare_tie_preserves_material_from_each_unstable_pass`
  focused on pure decision shape; no CLI exit assertion is needed there unless
  the test is expanded.

Done criteria:

- Root `bakeoff --help` includes the matrix.
- Tests cover validation exit `2`, provider/judge runtime failure `1`, and
  compare tie exit `3`.
- Existing successful research, auto-triage, rerun, show, ls, and dry-run
  triage tests remain green with intentional exit-code updates only.

## Stderr Discipline

Add small output helpers in `src/bakeoff/cli.py`:

```python
def _note(message: str) -> None:
    print(f"note: {message}", file=sys.stderr)

def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)
```

Vocabulary:

- `note:` means informational; no action is required.
- `warning:` means action may be needed, but the command continues.
- `error:` means the command failed and exits nonzero.

Initial call sites:

- Generated review context requested for a non-code-review facet.
- Triage "invokes one provider call" advisory.
- Cleanup failures for temporary scope workspaces.
- Doctor auth probe warning currently rendered inline as
  `(warning: reason)`. Replace the inline suffix with `_warn()` while keeping
  the structured `warnings` array in `doctor --json`.
- Any future warning/note text added in this pass.

Do not move every progress line to stderr globally. In normal human mode, run
headers, artifact paths, and next commands may remain stdout. In `--json` mode,
all human progress, notes, warnings, and next-step hints go to stderr so stdout
contains exactly one JSON object.

Done criteria:

- Tests assert `_note()` and `_warn()` write to stderr.
- No human warning/note string appears on stdout during `research --json`,
  `triage --json`, or `runs verify --json`.

## JSON Summary Contract

Add final `--json` summaries. They are single JSON objects, not event streams.

Shared behavior:

- `--json` implies effective `--quiet`; passing both is harmless.
- In `--json` mode, stdout contains exactly one pretty-printed JSON object on
  normal completion or artifact-producing runtime failure.
- In `--json` mode, provider heartbeats are suppressed.
- On usage/config/validation failure before a run or triage directory can be
  resolved, keep the current stderr error and exit `2`; no JSON object is
  required.
- On SIGINT during `research --json` or `triage --json`, emit no JSON summary,
  write `error: interrupted` to stderr, exit with conventional interrupt status
  `130`, and let operators recover with `bakeoff runs verify <run-id>` if a run
  directory was already created.
- Summary JSON uses `json.dumps(..., indent=2, sort_keys=False)` so the
  documented field order is preserved.
- Add `"command": "doctor"` to `doctor --json` for parity with new JSON
  summaries. Do not change `ls --json` in this pass.
- Include `warnings: []` in `research`, `triage`, and `runs verify` JSON
  summaries for parity with `doctor --json`.

Provider status enum for summary JSON:

- Use a closed summary enum: `ok`, `ok_after_format_retry`, `failed`.
- Preserve the underlying Bakeoff status as `raw_status` when it differs or
  when the summary status is `failed`.
- Examples: raw `timeout`, `output_cap`, `scope_error`, `missing_provider`,
  `exit_error`, and `schema_error` become summary `failed`.

### Research JSON

Shape:

```json
{
  "schema_version": 1,
  "command": "research",
  "status": "ok",
  "exit_code": 0,
  "warnings": [],
  "run_id": "2026-05-16-abcd",
  "run_dir": "runs/2026-05-16-abcd",
  "decision_kind": "structured_union",
  "canonical_winner": null,
  "judge_ran": true,
  "providers": {
    "claude": {"status": "ok", "raw_status": "ok", "wall_seconds": 12.3},
    "codex": {"status": "ok_after_format_retry", "raw_status": "ok_after_format_retry"}
  },
  "judge": {"status": "ok", "raw_status": "ok"},
  "triage": {
    "auto_started": false,
    "state": "no",
    "status": null,
    "exit_code": null,
    "artifacts": {}
  },
  "artifacts": {
    "work_order": "runs/2026-05-16-abcd/work-order.json",
    "decision": "runs/2026-05-16-abcd/decision.json",
    "meta": "runs/2026-05-16-abcd/meta.json",
    "manifest": "runs/2026-05-16-abcd/manifest.json",
    "report": "runs/2026-05-16-abcd/report.md"
  },
  "next": "bakeoff show 2026-05-16-abcd"
}
```

Top-level `status` values:

- `ok` for exit `0`.
- `failed` for exit `1`.
- `judge_disagreement` for exit `3`.

Auto-triage requirements:

- If research starts auto-triage, set `triage.auto_started: true`.
- Include the final triage state after auto-triage.
- Include triage artifact paths when they exist.
- If auto-triage fails, research summary `status` is `failed`, `exit_code` is
  `1`, `decision_kind` still reflects the completed research decision, and
  `triage.exit_code` records the triage failure.

Done criteria:

- `research --json` success emits parseable JSON and exits `0`.
- `research --json` with both providers failed emits parseable JSON and exits
  `1`.
- `research --json` compare tie emits parseable JSON and exits `3`.
- `research --json` with auto-triage success includes `triage.auto_started:
  true`, final triage state, and triage artifact paths.
- `research --json` stdout contains no human text.

### Triage JSON

Shape:

```json
{
  "schema_version": 1,
  "command": "triage",
  "status": "ok",
  "exit_code": 0,
  "warnings": [],
  "run_id": "2026-05-16-abcd",
  "run_dir": "runs/2026-05-16-abcd",
  "dry_run": false,
  "triage": {
    "state": "yes",
    "status": "ok",
    "raw_status": "ok",
    "selected_findings": 4,
    "skipped_non_actionable": 1,
    "skipped_out_of_facet": 0
  },
  "artifacts": {
    "prompt": "runs/2026-05-16-abcd/triage/prompt.txt",
    "status": "runs/2026-05-16-abcd/triage/status.json",
    "citation_checks": "runs/2026-05-16-abcd/triage/citation_checks.json",
    "source_finding_filter": "runs/2026-05-16-abcd/triage/source_finding_filter.json",
    "final": "runs/2026-05-16-abcd/triage/final.json",
    "triage": "runs/2026-05-16-abcd/triage/triage.md"
  },
  "next": "bakeoff show 2026-05-16-abcd --triage"
}
```

Done criteria:

- `triage --json --dry-run` emits parseable JSON with `dry_run: true` and exits
  `0`.
- `triage --json` success emits parseable JSON and exits `0`.
- `triage --json` provider/schema failure emits parseable JSON and exits `1`.
- `triage --json` stdout contains no human text.

## Run Verification

Add:

```text
bakeoff runs verify <run-id> [--out runs] [--json]
```

Keep it intentionally narrow. It verifies one run ledger; it does not list,
delete, prune, repair, or rewrite.

Verification checks:

- Resolve `latest` and path-like run ids using existing `resolve_run_dir()`
  behavior.
- Require `manifest.json`.
- Require manifest `schema_version == 1`.
- Require manifest `run_id` to match the resolved run directory name.
- Require all manifest-listed required artifacts to exist:
  `work-order.json`, `decision.json`, `meta.json`, and `report.md`.
- Recompute fingerprints for every path under
  `manifest.artifact_fingerprints`, not just required artifacts.
- Compare `sha256` and `size_bytes`.
- Treat `mtime_ns` differences as informational only; content and size are the
  integrity checks.
- Report current triage state using `triage_state_detail()`, including stale
  inputs when applicable. Stale triage is not a ledger-integrity failure.
- Return `0` when required artifacts and content fingerprints verify.
- Return `1` when verification finds missing artifacts, invalid manifest
  content, or fingerprint mismatches.
- Return `2` for usage/config/missing-run errors raised as `ValidationError`.

Human output:

```text
run verify: 2026-05-16-abcd
  run dir: runs/2026-05-16-abcd
  manifest: ok
  required artifacts: ok
  fingerprints: ok (8 checked)
  triage: stale (decision.json changed)
next: bakeoff triage 2026-05-16-abcd --force
```

Failure output:

```text
run verify: review-run
  run dir: runs/review-run
  manifest: ok
  required artifacts: failed
  fingerprints: failed (7 checked)
  triage: no
problems:
  - missing artifact: runs/review-run/report.md
  - fingerprint mismatch: runs/review-run/decision.json
next: bakeoff rerun review-run
```

Next hint rules:

- If verification passes and triage is stale, suggest
  `bakeoff triage <run-id> --force` with the correct `--out` suffix.
- If verification passes and triage is available, suggest
  `bakeoff show <run-id> --triage` with the correct `--out` suffix.
- If verification passes otherwise, suggest `bakeoff show <run-id>` with the
  correct `--out` suffix.
- If verification fails but `work-order.json` exists, suggest
  `bakeoff rerun <run-id>` with the correct `--out` suffix.
- If no safe command exists, use `next: restore the listed artifacts or rerun
  the original work order`.

JSON shape:

```json
{
  "schema_version": 1,
  "command": "runs verify",
  "status": "ok",
  "exit_code": 0,
  "warnings": [],
  "run_id": "2026-05-16-abcd",
  "run_dir": "runs/2026-05-16-abcd",
  "manifest": {"status": "ok", "path": "runs/2026-05-16-abcd/manifest.json"},
  "required_artifacts": {
    "status": "ok",
    "checked": ["work-order.json", "decision.json", "meta.json", "report.md"],
    "missing": []
  },
  "fingerprints": {
    "status": "ok",
    "checked_count": 8,
    "mismatches": []
  },
  "triage": {"state": "stale", "stale_inputs": ["decision.json"]},
  "problems": [],
  "next": "bakeoff triage 2026-05-16-abcd --force"
}
```

Done criteria:

- Top-level help exposes `runs`; `bakeoff runs --help` exposes `verify`.
- Valid manifest-backed run verifies with exit `0`.
- Missing manifest exits `1` with a clear problem.
- Missing required artifact exits `1`.
- SHA or size mismatch exits `1`.
- Stale triage is reported but does not fail verification.
- `latest` works.
- `runs verify --json` stdout contains parseable JSON and no human text.

## Docs and Quickstart

Update `examples/review.work-order.json`:

- Replace the stale comment that says Bakeoff does not compute branch diffs.
- Point operators to `bakeoff research ... --base main --diff` for generated
  review context while still allowing manually pasted background context.

Update README:

- Keep the existing detailed artifact reference.
- Add a short `Common Workflows` section near the top, before or immediately
  after `User Surface`.
- Include only practical workflows:
  - create a review work order, edit TODO placeholders, validate, and run it
  - inspect the latest report
  - rerun a previous work order
  - run or dry-run triage
  - verify a run ledger
- Make the quickstart copy-paste safe by saying `bakeoff init review` writes
  TODO placeholders and operators must edit them before `validate`.
- Add the exit-code table.
- Add the new `research --json`, `triage --json`, and `runs verify` entries to
  the user-surface block.
- Document that `--json` implies effective `--quiet`.
- Document the summary provider status enum:
  `ok | ok_after_format_retry | failed`.

Done criteria:

- README describes the new surfaces and does not imply unsupported config,
  pruning, templating, or streaming features.
- `examples/review.work-order.json` no longer contradicts review-context
  capture.
- README workflows do not tell users to validate unedited TODO templates.

## NO_COLOR

Bakeoff should remain plain text in this pass.

Rules:

- Do not add `--color`.
- Do not add colored output.
- If any formatter introduced in this pass is tempted to add styling, gate it
  on `NO_COLOR` and default to no ANSI output.

Done criteria:

- With `NO_COLOR=1`, `bakeoff --help`, `research --json`, `triage --json`, and
  `runs verify --json` emit no ANSI escape sequences.
- The implementation introduces no colorized output.

## Tests

Add focused tests rather than broad snapshots:

- Atomic write success and failure cleanup.
- `manifest.py` writes through shared IO.
- Root help includes exit codes.
- `bakeoff runs --help` lists `verify`.
- `_note()` and `_warn()` write to stderr.
- Doctor auth probe warnings use the new warning path in human mode while
  preserving `doctor --json.warnings`.
- `doctor --json` includes `"command": "doctor"`.
- `research --json` success, both-providers-failed exit `1`, compare tie exit
  `3`, and auto-triage success shape.
- `triage --json` success or dry-run, plus provider/schema failure.
- `runs verify` success, missing manifest, missing required artifact,
  fingerprint mismatch, stale triage, and `--json`.
- `--json` implies effective quiet: no heartbeat lines are emitted.
- SIGINT in JSON mode emits no JSON summary.
- `NO_COLOR=1` produces no ANSI escapes in representative outputs.

Run:

```bash
pytest
```

## Deferred

### Global Config

Defer `--config`, `BAKEOFF_CONFIG`, `config show`, and a config file format.
Mature CLIs grow config after repeated command-line pain. Bakeoff already has a
real configuration surface: the work order. A second global config layer would
create precedence rules, support burden, and hidden state before it earns its
place.

Add narrow environment mirrors such as `BAKEOFF_OUT` only if repeated dogfood
shows that operators constantly pass the same flag.

### NDJSON Event Streams

Defer event streaming. Terraform and Cargo need it because their long-running
operations produce meaningful mid-run diagnostics. Bakeoff already has compact
heartbeats and durable files. Stable final summaries and verifiable artifacts
come first.

### Run Pruning

Defer `runs prune --older-than`. It deletes audit artifacts, which is directly
against Bakeoff's product promise unless disk pressure becomes real. If added
later, it should require explicit confirmation or a dry-run-first flow.

### Runs Dir

Defer `runs dir`. It is harmless, but unnecessary. `runs verify` prints the
resolved run path when that matters.

### Command Package Split

Defer splitting `cli.py` into command modules. Bakeoff has about eight
top-level commands and argparse does not force a package-per-command shape.
Refactor when reading pain is real, not because larger Cobra/clap CLIs need
that structure.

### Warning Strictness

Defer `--warnings-as-errors`. A global warning policy is not a good fit for
Bakeoff right now. If a warning should affect automation, encode it as a clear
decision state or exit code in the relevant command.

### Formatting Extras

Defer `--jq`, `--template`, custom columns, and rich output formatting. Final
JSON summaries are enough; users can pipe to `jq`.

### Color Controls

Defer `--color auto|always|never`. Bakeoff should remain plain text for now.
Honor `NO_COLOR` by continuing not to emit ANSI styling.

