# Artifacts And Ledger

Bakeoff writes run ledgers under `<out>/<run-id>`, with `runs` as the default
output directory. A `latest` pointer is updated when a run becomes active.

The ledger is the handoff. Inspect it instead of relying on terminal output.

## Required Core Artifacts

Every completed run should have:

| Path | Meaning |
| --- | --- |
| `work-order.json` | Exact work order used by the run. |
| `decision.json` | Machine-readable decision record. |
| `meta.json` | Run metadata: type, run mode, facet, optional experiment labels, terminal decision kind, canonical winner, judge status, exit code, timestamps, cwd, versions, scope policy, resolved models, input hashes. |
| `report.md` | Human-readable report. |
| `manifest.json` | Manifest with artifact paths, SHA-256 fingerprints, and local telemetry fields documented in [Manifest Telemetry](cli-reference.md#manifest-telemetry). |

Build runs also require `build-context.json`.

## Provider Artifacts

Provider artifacts live under `providers/<provider-id>/`.

| Path | Meaning |
| --- | --- |
| `prompt.txt` | Prompt sent to the provider. |
| `stdout.txt` | Captured stdout. |
| `stderr.txt` | Captured stderr. |
| `status.json` | Status summary without the full payload. |
| `final.json` | Parsed provider final JSON when the provider completed successfully. |
| `failure.json` | Structured failure summary when the provider did not complete successfully. |
| `last-message.txt` | Last-message capture when supported by the provider backend. |

Repair artifacts such as `repair-prompt.txt`, `repair-stdout.txt`,
`repair-stderr.txt`, and `repair-status.json` may appear when format retry was
needed.

Provider and judge `status.json` files include `stderr_kind` when available.
Values are `none`, `transport_noise`, `diagnostic`, or `errors`; raw
`stderr.txt` is still preserved unchanged.

## Judge Artifacts

Judge artifacts live under `judge/`.

Gather uses:

- `judge/prompt.txt`
- `judge/status.json`
- `judge/result.json`
- `judge/stdout.txt`
- `judge/stderr.txt`

Compare, analyze, and build use swapped passes:

- `judge/prompt-pass1.txt`
- `judge/result-pass1.json`
- `judge/status-pass1.json`
- `judge/prompt-pass2.txt`
- `judge/result-pass2.json`
- `judge/status-pass2.json`

## Review Context Artifacts

When `bakeoff research` captures review context with `--base`, `--diff`, or
`--changed-files`, the run includes:

| Path | Meaning |
| --- | --- |
| `source-work-order.json` | Original work order before generated context was appended. |
| `review-context.md` | Human-readable generated review context. |
| `review-context.json` | Metadata and captured diffstat/changed-file/patch text. |

Review context is all-or-none in manifests and triage input hashes.

## Triage Artifacts

Triage artifacts live under `triage/`.

| Path | Meaning |
| --- | --- |
| `triage/status.json` | Triage status or dry-run status. |
| `triage/prompt.txt` | Prompt sent to the triage provider. |
| `triage/final.json` | Parsed triage result when completed. |
| `triage/triage.md` | Human-readable triage report. |
| `triage/citation_checks.json` | Citation path checks. |
| `triage/source_finding_filter.json` | Which source findings were selected, skipped as non-actionable, or skipped as out-of-facet. |
| `triage/finding_index.json` | Present when finding IDs had to be synthesized from report order. |

Triage state is one of `no`, `dry_run`, `yes`, or `stale`. Manifests also
include `triage.source_finding_filter` when available and set
`triage.zero_selected: true` when completed triage selected zero source
findings.

## Build Artifacts

Build runs add baseline, context, diagnostics, and per-provider build evidence.

| Path | Meaning |
| --- | --- |
| `build-context.json` | Source repo, base ref/commit, worktree parent, provider ids, verifiers, and cleanup status. |
| `diagnostics.json` | Build diagnostics, warnings, phase timings, prompt sizes, patch integrity checks, and output truncation. |
| `baseline/verify/result.json` | Baseline verifier result before providers run. |
| `baseline/verify/<verifier-id>/stdout.txt` | Baseline verifier stdout. |
| `baseline/verify/<verifier-id>/stderr.txt` | Baseline verifier stderr. |
| `baseline/verify/<verifier-id>/status.json` | Baseline verifier status. |
| `baseline/verify/<verifier-id>/metric.json` | Baseline metric parse result when applicable. |

Per-provider build artifacts live under `providers/<provider-id>/build/`.

| Path | Meaning |
| --- | --- |
| `workspace.json` | Provider worktree metadata and cleanup status. |
| `capture.json` | Patch capture result. |
| `scope.json` | Scope diagnostics for changed files. |
| `diff.patch` | Captured candidate patch. |
| `diffstat.txt` | Diffstat for the captured patch. |
| `changed-files.txt` | Changed file list for the captured patch. |
| `test-files.json` | Provider-authored tests detected during capture. |
| `benchmark-files.json` | Provider-authored benchmarks or probes detected during capture. |
| `verify/result.json` | Provider verifier summary. |
| `verify/<verifier-id>/stdout.txt` | Verifier stdout. |
| `verify/<verifier-id>/stderr.txt` | Verifier stderr. |
| `verify/<verifier-id>/status.json` | Verifier status. |
| `verify/<verifier-id>/metric.json` | Metric parse result when applicable. |

Gate verifier status objects may include `baseline_expectation`,
`baseline_matched`, and `transition`. These fields are additive and explain how
baseline status related to provider status, especially for fail-to-pass gates.
Metric verifier status objects may be `skipped` when one or more gate verifiers
failed for the same candidate.

If there is a canonical winner, the selected handoff patch is:

```text
runs/<run-id>/providers/<winner>/build/diff.patch
```

Inside `report.md` and `bakeoff build --json`, selected patch artifact paths are
run-relative, for example `providers/<winner>/build/diff.patch`. Interactive
terminal output may print the full path as an operator convenience. Bakeoff does
not apply it.

## Manifest Verification

Run:

```text
bakeoff runs verify <run-id>
```

Use `--json` for a parseable verification report. Verification checks required
artifacts, manifest state, fingerprints, and triage state.

## Stable Manifest Contract

External scripts and notebooks should treat each `runs/<run-id>/manifest.json`
as the stable per-run data contract. Bakeoff emits durable evidence rows; it
does not own orchestration, retry policy, cross-run exports, confidence
intervals, Bradley-Terry/Elo, `pass@k`, `pass^k`, or paper tables.

Stable top-level manifest fields include:

- `run_id`
- `type`
- `run_mode`
- `single_provider`
- `facet_id`
- `started_at`
- `finished_at`
- `decision_kind`
- `canonical_winner`
- `selected_patch_provider`
- `judge_ran`
- `judge_attempted`
- `judge_completed`
- `providers`
- `judge`
- `triage`
- `artifacts`
- `artifact_fingerprints`
- `telemetry`
- `experiment_id`
- `task_id`
- `condition_id`
- `run_kind`
- `repetition_index`
- `slot_id`
- `slot_attempt`

Experiment fields are present when `work-order.json` included an
`experiment` object. `slot_id` and `slot_attempt` are nullable when no slot was
provided; older non-experiment runs may omit all experiment fields.
`run_mode` defaults to `pairwise` for old work orders. Intentional
single-provider runs set `single_provider` and leave `canonical_winner` null;
single-provider build handoff uses `selected_patch_provider`.

Evidence types are not interchangeable. LLM judge wins are preference evidence;
build verifier success is executable gate or metric evidence; triage-confirmed
findings are post-judge review evidence; human labels and calibration live in
external study tooling.

## Retained Worktrees

Build worktrees are removed by default. `--keep-worktrees` retains them for
debugging, and the retained parent path is recorded in `build-context.json` as
`worktree_parent_path`. Treat retained worktrees as debugging material, not as
the selected handoff patch.
