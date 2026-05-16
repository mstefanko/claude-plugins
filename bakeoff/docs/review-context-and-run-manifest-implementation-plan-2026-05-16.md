# Review Context and Run Manifest - Implementation Plan

Date: 2026-05-16
Status: proposed
Scope: `bakeoff research` review-context helpers, a run-level
machine-readable manifest, and lightweight manifest-backed history listing

## Decision

Add three small CLI hardening features:

1. `bakeoff research` may capture deterministic git review context through
   `--base`, `--diff`, and `--changed-files`.
2. Every completed run writes `manifest.json`, a compact machine-readable
   summary derived from existing run artifacts.
3. `bakeoff ls` gains a JSON manifest-scanning mode with basic filters.

These features should make code-review dogfood and shell automation easier
without changing Bakeoff's core topology. A run remains one work order, two
workers, an optional judge phase, a report, and optional triage. The new review
context is input capture. The manifest is output indexing. `ls --json` is the
light history surface until dogfood proves that SQLite/FTS is worth its extra
schema and lifecycle cost.

## Current Constraints

- `bakeoff init review` already creates a normal `type: "gather"` work order
  with a shared `code-review` facet.
- The README currently tells operators to paste branch, diff, changed-file,
  acceptance-criteria, and known-risk context into `background`.
- `run_research()` loads one work order, writes a run directory, runs workers,
  writes `decision.json`, `report.md`, and `meta.json`, then optionally runs
  triage.
- `rerun` currently replays `work-order.json` from a previous run.
- `ls` and `show` already consume `meta.json`, `decision.json`, `report.md`,
  and triage state.

The implementation should preserve those shapes. Do not add a background job
manager, worktree manager, provider matrix, auto-fix loop, or review-specific
mode.

## Non-Goals

- No new core mode; review remains a `gather` recipe plus `code-review` facet.
- No provider-specific review lenses.
- No automatic code edits, commits, issue creation, or PR comments.
- No tmux/session lifecycle management.
- No cross-run synthesis.
- No streaming or watching commands.
- No attempt to parse semantic meaning from diffs beyond deterministic git
  metadata.
- No arbitrary file-include system in this pass.
- No SQLite dependency in this implementation plan.
- No database-backed history, FTS, dashboards, or schema migrations in this
  pass.
- No automatic deletion of run directories from history commands. Run artifact
  cleanup should require an explicit future command.

## Bootstrap Evidence

- Package layout: `pyproject.toml` uses `src` layout with packages under
  `src/bakeoff/` (`pyproject.toml:16-21`). README documents `bin/bakeoff`,
  `src/bakeoff/`, `tests/`, and `examples/` (`README.md:12-22`).
- Python version and dependencies: `requires-python = ">=3.10"` with no runtime
  dependencies; `pytest>=8.0` is dev-only (`pyproject.toml:1-11`).
- Test command: `pytest`, matching README development setup
  (`README.md:24-32`) and pytest config (`pyproject.toml:23-34`).
- Current CLI surface: `research`, `rerun`, `triage`, `ls`, and `show` are
  argparse subcommands in `src/bakeoff/cli.py:97-127`.
- Current run write path: `run_research()` creates `runs/<run-id>/`, writes
  `work-order.json`, runs providers/judge, then writes `decision.json`,
  `report.md`, and `meta.json` in `src/bakeoff/cli.py:453-526`.
- Current metadata path: `write_meta()` records `run_id`, mode, facet,
  timestamps, cwd, `bakeoff_version`, provider CLI versions, input hashes, and
  resolved models in `src/bakeoff/cli.py:1203-1242`.
- Current triage freshness path: `triage_state_detail()` compares
  `decision.json`, `report.md`, and `work-order.json` hashes from
  `triage/final.json.input_hashes` in `src/bakeoff/triage.py:132-155`.
- Current JSON writer: `write_json()` writes directly with `Path.write_text()`
  in `src/bakeoff/cli.py:1343-1344`; manifest writes need stronger atomic
  semantics than this helper currently provides.

## User Surface

Extend `research` and `ls`:

```text
bakeoff research <work-order> [--out runs] [--run-id ID] [--force] [--quiet] [--no-triage]
  [--base REF] [--diff] [--changed-files]
bakeoff ls [--out runs] [--json] [--facet ID] [--triage-state STATE]
```

Semantics:

- Any of `--base`, `--changed-files`, or `--diff` enables review-context
  capture.
- Effective base ref: `--base REF` when provided, otherwise `HEAD`.
- Included sections always start with metadata and diffstat.
- Changed-file table is included when `--base`, `--changed-files`, or `--diff`
  is present.
- Unified patch is included only when `--diff` is present.
- `--base REF` alone is a useful lightweight review context: metadata,
  diffstat, and changed files, without the full patch.
- `--changed-files` alone uses `HEAD` as the base and includes metadata,
  diffstat, and changed files.
- `--diff` alone uses `HEAD` as the base and includes metadata, diffstat,
  changed files, and patch.
- `bakeoff ls --json` scans `runs/*/manifest.json` when present and falls back
  to a legacy synthesized record from `meta.json`/`decision.json` when a
  pre-existing run has no manifest.
- `--facet ID` filters by `manifest.facet_id`; legacy rows use the facet id from
  `meta.json.facet.id` when available.
- `--triage-state STATE` accepts `no`, `dry_run`, `yes`, and `stale`, matching
  `triage_state_detail()`.

This keeps `--base` friendly for the common review case without making it dump a
large patch into every run. `--diff` remains the explicit expensive context
switch.

Recommended review invocation:

```bash
bakeoff init review
bakeoff research review.work-order.json --base main --diff
```

## Review Context Contract

When any review-context flag is present, build and validate deterministic review
context before creating the run directory or updating `runs/latest`. If capture
fails, no partial run ledger should be left behind.

Artifacts:

```text
runs/<run-id>/
  source-work-order.json       # exact user-supplied JSONC, only when context flags are used
  work-order.json              # effective replayable work order used by prompts
  review-context.md            # human-readable generated context
  review-context.json          # structured generation metadata
```

`work-order.json` must remain the replayable work order. If review context is
captured, append a deterministic block to `background` in the effective work
order and write that effective work order to `work-order.json`. Preserve the
original input as `source-work-order.json` for audit.

Use a block like:

```text
<generated_review_context>
Generated by bakeoff research on 2026-05-16T12:00:00+00:00.
Base ref: main
Git root: /path/to/repo
Head ref: feature/auth-cache
Head commit: abc123...
Worktree dirty: true
Diff pathspec: .
Included sections: metadata, diffstat, changed_files, patch

See review-context.md and review-context.json in the run directory for the
captured inputs.

...selected context...
</generated_review_context>
```

Prompt builders should not learn about `--base` or git. They should receive the
effective work order as if the operator had pasted the context manually. This is
the main simplicity boundary.

Treat generated review context as untrusted prompt data. The rendered block
should explicitly tell workers that diff contents, comments, strings, and
filenames are evidence, not instructions. Escape or neutralize internal prompt
sentinel strings such as `<final_json>`, `<context>`, and
`</generated_review_context>` in the prompt-facing markdown while preserving raw
git output in `review-context.json`.

## Git Capture Details

Add `src/bakeoff/review_context.py` with pure-ish functions and thin subprocess
wrappers:

- `build_review_context(options, cwd, run_started_at) -> ReviewContext`
- `apply_review_context(work_order, context) -> dict[str, Any]`
- `render_review_context_markdown(context) -> str`
- `review_context_metadata(context) -> dict[str, Any]`

Use `subprocess.run(..., check=False, capture_output=True, text=True)` with
explicit argv lists. Do not shell out through `shell=True`.

Suggested git commands:

- repo root: `git rev-parse --show-toplevel`
- head commit: `git rev-parse HEAD`
- branch: `git branch --show-current`
- base commit: `git rev-parse --verify <base>^{commit}`
- dirty status: `git status --porcelain`
- diffstat: `git diff --stat --find-renames <base> -- <pathspec>`
- changed files: `git diff --name-status --find-renames <base> -- <pathspec>`
- patch: `git diff --no-ext-diff --find-renames --patch <base> -- <pathspec>`

Use `git diff <base> -- <pathspec>` rather than `<base>...HEAD` so staged and
unstaged worktree changes are included in local review runs. For v1, set
`pathspec` to `.` and record it in `review-context.json`. Run the git commands
from the original `cwd` so `.` preserves the user's current subdirectory scope;
also record `git_root`, `capture_cwd`, and `pathspec` so a narrowed subdirectory
review is visible rather than accidental.

## Size and Failure Policy

Keep the first pass deliberately strict:

- Full patch capture has a hard retained-size cap of `120_000` UTF-8 bytes.
- Diffstat and changed-file output each have a hard retained-size cap of
  `40_000` UTF-8 bytes.
- If a requested section exceeds its cap, fail before provider execution with a
  `ValidationError` that names the section, actual retained size, and cap.
- Do not silently truncate patches in v1.

Large review contexts should be narrowed manually in the work order rather than
hidden behind partial generated diffs. This is less convenient, but it avoids
false confidence in a code-review report that never saw the whole requested
patch.

## Scope and Validation

Review-context flags are allowed for any work order, but the CLI should print a
short note when the facet is not `code-review`:

```text
note: generated review context was requested for a non-code-review facet
```

Do not reject non-review runs. The same context may be useful for `analyze` or a
custom gather facet. Also do not require both providers to use `codebase` scope;
the captured diff becomes prompt context and can be used by `mixed` or even
`web` scoped providers.

Validation errors:

- no git repo: `review context requires a git repository`
- invalid base ref: `review context base ref not found: <ref>`
- dirty git command failure: include the command label and stderr tail
- oversize section: `review context patch is 184231 bytes, exceeding 120000 bytes; rerun without --diff or narrow the work order`

Terminal feedback:

- After successful capture, print one compact summary before launching providers:
  `review context: base main abc123, 12 changed files, patch 48.2KB, dirty yes`.
- After writing artifacts, print the paths to `review-context.md` and
  `manifest.json` alongside the existing `report:` and `next:` lines.
- If capture was scoped to a subdirectory, include that in the summary:
  `pathspec . from packages/api`.

## Rerun Behavior

`rerun` should remain simple and replayable:

- If a source run has `work-order.json`, rerun that effective work order.
- Do not regenerate review context during `rerun`.
- If the source run has `source-work-order.json`, `review-context.md`, or
  `review-context.json`, copy those artifacts into the new run before providers
  launch.
- Thread this through explicitly with
  `run_research(..., replay_source_run_dir=source_run)`. Do not make
  `run_research()` rediscover prior runs by id.
- Preserve `review_context` metadata in `manifest.json` from
  `review-context.json` when present. If only an older effective `work-order.json`
  exists, fall back to detecting the generated block and report
  `review_context.present: true` with whatever fields can be derived.

This means a rerun reviews the same captured diff/context even if the local git
branch moved later. That matches Bakeoff's audit model.

## Run Manifest Contract

Write `runs/<run-id>/manifest.json` after `meta.json` and after any automatic
triage attempt. The manifest is a compact index. It must be derived from
artifacts already written to disk, not maintained as separate mutable state. It
is also the contract that `ls --json` and any later history indexer consume.

Keep the manifest location-independent where possible. Artifact paths are
relative to the run directory. Do not bake the absolute run directory into
`manifest.json`; a SQLite indexer can record the absolute path based on the
ledger root it scans. Absolute paths that describe the original execution
context, such as `cwd`, `git_root`, and `capture_cwd`, are still useful audit
metadata and should remain.

Schema v1:

```json
{
  "schema_version": 1,
  "run_id": "review-auth-cache",
  "bakeoff_version": "0.0.0",
  "type": "gather",
  "facet_id": "code-review",
  "started_at": "2026-05-16T12:00:00+00:00",
  "finished_at": "2026-05-16T12:10:00+00:00",
  "cwd": "/path/to/repo",
  "decision_kind": "structured_union",
  "canonical_winner": null,
  "judge_ran": true,
  "triage": {
    "state": "yes",
    "stale_inputs": [],
    "attempt_status": "ok",
    "input_hashes": {
      "decision_sha256": "...",
      "report_sha256": "...",
      "work_order_sha256": "..."
    },
    "item_count": 3,
    "item_counts_by_classification": {
      "real_issue": 2,
      "false_positive": 1,
      "plan_doc_drift": 0,
      "product_decision": 0,
      "needs_repro": 0,
      "already_fixed": 0,
      "evidence_gap": 0
    },
    "highest_severity": "high"
  },
  "providers": {
    "claude": {
      "backend": "claude",
      "model": "claude-sonnet-4-6",
      "scope": "codebase",
      "effort": "high",
      "status": "ok",
      "wall_seconds": 665,
      "stdout_bytes": 1024,
      "stderr_bytes": 2048,
      "final_json_source": "stdout"
    }
  },
  "judge": {
    "backend": "claude",
    "model": "claude-opus-4-7",
    "effort": "xhigh"
  },
  "review_context": {
    "present": true,
    "base_ref": "main",
    "base_commit": "abc123",
    "head_commit": "def456",
    "git_root": "/path/to/repo",
    "capture_cwd": "/path/to/repo",
    "pathspec": ".",
    "included_sections": ["metadata", "diffstat", "changed_files", "patch"]
  },
  "artifacts": {
    "work_order": "work-order.json",
    "source_work_order": "source-work-order.json",
    "review_context_md": "review-context.md",
    "review_context_json": "review-context.json",
    "decision": "decision.json",
    "report": "report.md",
    "meta": "meta.json",
    "triage": "triage/triage.md"
  },
  "artifact_fingerprints": {
    "work-order.json": {
      "sha256": "...",
      "size_bytes": 2048,
      "mtime_ns": 1778951000000000000
    },
    "decision.json": {
      "sha256": "...",
      "size_bytes": 8841,
      "mtime_ns": 1778951900000000000
    },
    "report.md": {
      "sha256": "...",
      "size_bytes": 42112,
      "mtime_ns": 1778952000000000000
    },
    "triage/triage.md": {
      "sha256": "...",
      "size_bytes": 12043,
      "mtime_ns": 1778952600000000000
    }
  }
}
```

Rules:

- Artifact paths are relative to the run directory.
- Omit optional artifact paths when files do not exist.
- Include provider status summaries, not stdout/stderr payloads.
- Include `triage.state` using the existing `triage_state_detail()` logic.
- Include stale triage inputs when applicable.
- Include `triage.attempt_status` from `triage/status.json` when a triage attempt
  exists, so failed auto-triage does not look the same as "not run".
- Include `triage.input_hashes` only when `triage/status.json` or
  `triage/final.json` recorded the input hashes used by that triage attempt.
  These are semantic freshness inputs for `triage_state_detail()`, not general
  artifact fingerprints.
- Include exactly these triage rollups when `triage/final.json` exists:
  `item_count`, `item_counts_by_classification`, and `highest_severity`.
  `item_counts_by_classification` must include all current
  `TRIAGE_CLASSIFICATIONS` keys from `work_order.py`, with zeroes for absent
  classes. `highest_severity` uses order `high > medium > low > none`; use
  `null` when there are no triage items. Do not copy full triage item bodies
  into the manifest.
- Include `review_context.present: false` when no generated context was used.
- Do not duplicate full `decision.json`, `meta.json`, or triage payloads.
- Do not include a top-level CLI process exit code in schema v1. Keep the
  manifest artifact-derived; scripts can infer run health from provider status,
  decision kind, and triage attempt status.
- Do not include a top-level `input_hashes` object in manifest schema v1. The
  load-bearing distinction is:
  `triage.input_hashes` records the exact inputs a triage attempt evaluated;
  `artifact_fingerprints` records current compact artifact identity for listing,
  legacy detection, and future indexing.
- Include `artifact_fingerprints` only for compact, history-relevant artifacts:
  `work-order.json`, `source-work-order.json`, `review-context.md`,
  `review-context.json`, `decision.json`, `meta.json`, `report.md`,
  `triage/status.json`, `triage/final.json`, and `triage/triage.md` when present.
  Do not hash provider stdout/stderr or repair payloads for the manifest.
- A missing optional artifact should be absent from both `artifacts` and
  `artifact_fingerprints`. A missing required artifact should make manifest
  generation fail loudly because the run ledger is incomplete.
- `bakeoff_version` must use the existing package constant
  `bakeoff.__version__`, matching current `write_meta()` behavior. Do not switch
  to `importlib.metadata` in this pass.
- Manifest writes must be atomic: write JSON to a temporary file in the run
  directory, flush and close it, then `os.replace()` it onto `manifest.json`.
  After replacement, read the file back and validate `schema_version == 1` and
  `run_id == run_dir.name`; if validation fails, raise `ValidationError`.

No new `show --json` flag in the first pass. Scripts can read
`runs/<run-id>/manifest.json` directly. If dogfood shows repeated friction, a
later tiny pass can add `bakeoff show <run-id> --json` as a manifest printer.

## Manifest-Backed Listing

Add a small JSON mode to existing `bakeoff ls` instead of introducing a history
database now.

Output contract:

```json
{
  "schema_version": 1,
  "out_dir": "runs",
  "runs": [
    {
      "run_id": "review-auth-cache",
      "manifest_state": "present",
      "type": "gather",
      "facet_id": "code-review",
      "decision_kind": "structured_union",
      "triage_state": "yes",
      "finished_at": "2026-05-16T12:10:00+00:00",
      "report_path": "runs/review-auth-cache/report.md",
      "manifest_path": "runs/review-auth-cache/manifest.json"
    }
  ]
}
```

Rules:

- `manifest_state` is `present`, `missing`, or `invalid`.
- For `present` manifests, read `manifest.json` and project a stable subset of
  fields. Do not emit full provider statuses or full artifact fingerprints from
  `ls --json`.
- For pre-existing runs without manifests, synthesize a legacy row from
  `meta.json`, `decision.json`, and `triage_state_detail()`. Set
  `manifest_state: "missing"`, include `report_path` when `report.md` exists,
  and omit `manifest_path`.
- For invalid manifests, set `manifest_state: "invalid"` and include
  `manifest_error` with a short parse/validation message. Do not crash the whole
  listing unless `--strict` is added in a future pass.
- Apply `--facet` and `--triage-state` after normalizing rows so the same
  filters work for manifest and legacy rows.
- Preserve the existing tabular `bakeoff ls` output when `--json` is absent.

This should cover the near-term history use cases: machine-readable listing,
basic filtering, and easy handoff to `jq` or another plugin. Full-text report
search is the main capability it does not cover.

## Deferred SQLite Catalog

Do not implement SQLite in this plan. The manifest makes each run directory
self-describing; a manifest scan should be the first dogfood surface.

Revisit SQLite only when at least one concrete trigger appears:

- Manifest scanning is too slow or awkward at roughly `500+` runs in real use.
- A user asks for full-text search over `report.md` or `triage/triage.md`.
- A dashboard or another plugin needs repeated cross-run queries that are
  painful with `ls --json` plus direct manifest reads.

If SQLite ships later, write a separate plan. Start with the narrow version:

- Keep run directories and `manifest.json` canonical.
- Use SQLite as a rebuildable cache/index, not as actual run storage.
- Prefer two real tables plus FTS: `runs`, `documents`, and
  `documents_fts`.
- Store normalized filter metadata and a `manifest_json` copy in `runs`.
- Store cached text for compact human-facing documents only:
  `report.md`, `triage/triage.md`, and optionally `work-order.json` and
  `review-context.md`.
- Drop separate `artifacts`, `providers`, and `triage_items` tables until a
  real query requires them; they duplicate manifest data and add migration
  surface without clear v1 value.
- Specify pre-existing-run migration in that separate plan: a rebuild must
  either synthesize legacy rows from `meta.json`/`decision.json` or clearly skip
  missing-manifest runs with a report.

## Implementation Steps

1. Extend argparse for `research` with `--base`, `--diff`, and
   `--changed-files`, and extend `ls` with `--json`, `--facet`, and
   `--triage-state`.
2. Add a `ReviewContextOptions` shape internally and thread it into
   `run_research()`.
3. If review-context flags are present, build and size-check the context before
   creating the run directory or moving `runs/latest`.
4. Create the run directory only after context validation succeeds.
5. When context is present, write `source-work-order.json`, generate an
   effective work order with augmented `background`, and write that effective
   work order to `work-order.json`.
6. Use the effective work order for `print_run_header()`, workers, judge,
   reports, meta, and auto-triage.
7. Add `review-context.md` and `review-context.json` artifacts.
8. For `rerun`, pass the source run directory into `run_research()` and copy
   existing review-context artifacts without regenerating git context.
9. Add `build_run_manifest(run_dir) -> dict[str, Any]` that reads existing
   artifacts and returns schema v1.
10. Add `write_run_manifest(run_dir)` with temp-file-plus-`os.replace()`
    semantics and read-after-write validation. Call it after `write_meta()`.
11. If auto-triage runs, call `write_run_manifest(run_dir)` again after triage
   completes so triage state is current.
12. Include compact artifact fingerprints and triage rollups in the manifest.
13. Add `manifest_row_for_ls(run_dir) -> dict[str, Any]` that reads
    `manifest.json` when present and synthesizes a legacy row from
    `meta.json`/`decision.json` when absent.
14. Implement `cmd_ls --json` with `--facet` and `--triage-state` filtering over
    normalized manifest/legacy rows.
15. Print review-context and manifest artifact paths in the completion summary.
16. Update README user surface and run ledger artifact list.

## Definition of Done

Phase 1 is complete when:

- `bakeoff research --base main` writes `source-work-order.json`,
  effective `work-order.json`, `review-context.md`, `review-context.json`,
  `decision.json`, `report.md`, `meta.json`, and atomic `manifest.json`.
- `bakeoff research --base main --diff` includes the bounded patch; `--base`
  without `--diff` includes no patch.
- `--changed-files` alone and `--diff` alone both use `HEAD` as the effective
  base and produce deterministic included sections as specified above.
- Review-context capture failures and oversize patch failures happen before run
  directory creation and before `runs/latest` changes.
- `rerun` replays the effective work order and copies existing review-context
  artifacts without invoking git.
- `manifest.json` contains schema v1, package version from `bakeoff.__version__`,
  provider status summaries, decision summary, triage state, pinned triage
  rollups, review-context metadata, relative artifact paths, and compact
  artifact fingerprints.
- Auto-triage rewrites `manifest.json` so triage state and attempt status are
  current.
- `bakeoff ls` tabular output remains backward-compatible.
- `bakeoff ls --json`, `--facet`, and `--triage-state` work for both new
  manifest runs and legacy runs that only have `meta.json`/`decision.json`.
- README documents the new flags and run ledger artifacts.
- `pytest` passes.

## Tests

Add focused tests rather than broad end-to-end explosion:

- `review_context` unit tests for command construction using monkeypatched
  subprocess results.
- `research --base main --diff` with a temporary git repo and
  fake providers writes:
  - `source-work-order.json`
  - effective `work-order.json`
  - `review-context.md`
  - `review-context.json`
  - `manifest.json`
- Effective `work-order.json` includes `<generated_review_context>` in
  `background`.
- `--base main` includes diffstat and changed files without a patch.
- `--changed-files` without `--base` uses `HEAD`.
- `--diff` without `--base` uses `HEAD` and includes changed files plus patch.
- `rerun` uses the effective work order, copies review-context artifacts, and
  does not call git context capture.
- Oversize patch fails before run directory creation and before fake providers
  launch.
- Prompt-facing review context escapes internal prompt sentinel strings while
  `review-context.json` preserves raw git output.
- `manifest.json` includes provider statuses, decision kind, relative artifact
  paths, review-context metadata, and triage state.
- `manifest.json` includes artifact fingerprints for compact indexed artifacts
  and omits provider stdout/stderr fingerprints.
- `manifest.json` includes exact triage rollups without copying full triage
  items.
- `manifest.json` is written atomically and read back with schema/run-id
  validation.
- Auto-triage updates `manifest.json` from `triage:no` to `triage:yes`.
- Failed auto-triage records `triage.attempt_status` in `manifest.json`.
- `manifest.json` omits optional review-context artifacts when no context flags
  are used.
- `bakeoff ls --json` emits manifest rows for new runs and legacy synthesized
  rows for pre-existing runs without `manifest.json`.
- `bakeoff ls --json --facet code-review` filters manifest and legacy rows.
- `bakeoff ls --json --triage-state yes` filters manifest and legacy rows.

## Documentation

README updates:

- Add the new `research` flags to the user surface.
- Add the new `ls --json`, `--facet`, and `--triage-state` flags.
- Explain that generated review context is written into the effective
  `work-order.json` and preserved separately as `source-work-order.json`.
- Add `manifest.json`, `review-context.md`, `review-context.json`, and
  `source-work-order.json` to the run ledger list.
- Add a short code-review example:

```bash
bakeoff init review
bakeoff research review.work-order.json --base main --diff
```

## Risks

- **Prompt bloat:** bounded by strict caps and explicit `--diff`.
- **Replay confusion:** addressed by writing effective `work-order.json` and
  preserving source and generated review-context artifacts.
- **Git edge cases:** keep v1 to local git metadata and clear validation
  failures; do not support remote fetching or merge-base inference.
- **Subdirectory surprise:** record `capture_cwd`, `git_root`, and `pathspec`,
  and print a scoped-capture note when `cwd` is below the git root.
- **Prompt injection through diffs:** generated context is labeled untrusted and
  prompt sentinel strings are escaped in markdown prompts while raw git output is
  preserved in JSON.
- **Manifest drift:** derive from artifacts on disk and rewrite after auto
  triage.
- **Manifest atomicity:** write via temp file and `os.replace()`, then read back
  `schema_version` and `run_id`.
- **Legacy run ambiguity:** `ls --json` labels pre-manifest runs with
  `manifest_state: "missing"` instead of pretending they have full schema-v1
  metadata.
- **History overbuild:** SQLite/FTS is deferred until manifest scans are proven
  insufficient.
- **CLI sprawl:** no separate `review-context` command, no `show --json`, no
  batch runner, and no `history` command in this pass.

## Resolved Phase 1 Decisions

- Patch cap is `120_000` bytes for v1.
- Diffstat and changed-file caps are `40_000` bytes each for v1.
- Review capture preserves the user's current subdirectory scope by running git
  commands from the original `cwd` with pathspec `.`.
- Manifest schema v1 uses `bakeoff.__version__`.
- Manifest schema v1 does not include top-level `input_hashes`; triage attempt
  hashes live under `triage.input_hashes`, and current artifact identity lives
  under `artifact_fingerprints`.
- SQLite/FTS is deferred to a separate plan and should start from the narrow
  `runs` + `documents` + `documents_fts` shape only after a concrete trigger.
