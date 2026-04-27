# Agentless Repair Design

Date: 2026-04-27

`agentless-repair` is intentionally not a stock runnable preset yet. The
current pipeline DSL can express agent stages, provider review stages, fan-out,
and synthesize/vote merges. It cannot yet express deterministic candidate patch
artifacts, temp-worktree validation/reranking, or a non-mutating patch handoff
from one stage to another.

## Inspection Findings

- The current pipeline schema intentionally has only three stage kinds:
  `agents`, `fan_out`, and `provider`. Provider stages are read-only and only
  accept `command: review`, with `output: findings`. Do not overload that path
  with patch generation.
- `work_units.v2` already owns much of the validation vocabulary:
  `allowed_files`, `blocked_files`, `validation_commands`, `expected_results`,
  `risk_tags`, and `handoff_notes`. Patch candidates should reuse those fields
  rather than inventing a parallel unit schema.
- `py/swarm_do/pipeline/worktrees.py` already owns predictable branch/worktree
  names, integration branches, merge-conflict events, and cleanup helpers for
  unit worktrees. Candidate validation should extend this module or sit beside
  it, not create a second ad hoc worktree implementation.
- `py/swarm_do/pipeline/provider_review.py` is the best local model for this
  subsystem: schema-normalized artifacts, fake fixtures for deterministic tests,
  sidecars/manifests for large raw output, prompt-safe evidence summaries, and
  fail-open telemetry writes.
- Telemetry metadata belongs in `swarm_do.telemetry.registry.LEDGERS` plus
  schema files. Per-run artifacts can keep rich logs; queryable cross-run facts
  should be append-only JSONL rows.

## Target Flow

```text
localization -> candidate unified diffs -> temp-worktree validation/rerank
  -> winning patch handoff -> normal writer/spec-review/provider-review/review
```

This should be built first as a generic substrate:

```text
patch_candidates artifact -> isolated apply/validate -> ranked evidence
  -> non-mutating handoff
```

`agentless-repair` then becomes one consumer of that substrate, not the owner
of the hard runtime machinery.

## Recommended Architecture

Add a `patch_candidates` Python module under `py/swarm_do/pipeline/` with a
thin CLI surface under `bin/swarm patch-candidates ...`.

The module owns:

- schema loading and artifact linting,
- stable candidate ids and diff hashes,
- safe path validation against allowed/blocked file policy,
- temp worktree creation and cleanup,
- patch apply checks,
- deterministic validation command execution,
- ranked evidence generation,
- prompt-safe summary rendering,
- telemetry/run-event writes.

Initial CLI:

```bash
bin/swarm patch-candidates lint <artifact>
bin/swarm patch-candidates validate <artifact> --repo . --run-id <id> --output-dir <dir>
bin/swarm patch-candidates evidence <validation-result.json>
bin/swarm patch-candidates handoff <validation-result.json> --candidate winner --output <patch.diff>
```

The first implementation should not require a new stock pipeline stage. Prove
the artifact, validator, ranking, cleanup, fake fixtures, and telemetry first.
After the primitive is stable, add an explicit pipeline stage kind rather than
misusing `provider`:

```yaml
- id: validate-candidates
  depends_on: [candidate-patches]
  patch_candidates:
    input_artifact: patch-candidates
    validation_source: work_unit
    selection_policy: deterministic-v1
    timeout_seconds: 1800
    max_parallel: 4
    cleanup: always
```

That schema change should update `schemas/pipeline.schema.json`,
`validation.py`, `engine.graph_lines`, budget estimates, CLI display, and
tests in the same commit.

## Patch Artifact Contract

Create `schemas/patch_candidates.schema.json` for per-run artifacts. Keep the
full unified diffs in sidecar files when they are large; the JSON artifact
stores hashes, metadata, and relative sidecar paths.

Required shape:

```json
{
  "schema_version": "patch-candidates.v1",
  "run_id": "01...",
  "issue_id": "bd-123",
  "stage_id": "candidate-patches",
  "base_ref": "HEAD",
  "base_sha": "0123456789abcdef0123456789abcdef01234567",
  "work_unit_id": "unit-a",
  "allowed_files": ["py/swarm_do/**/*.py"],
  "blocked_files": ["data/**", ".git/**"],
  "validation_commands": [
    {
      "id": "unit-tests",
      "command": "PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_worktrees",
      "timeout_seconds": 300,
      "required": true
    }
  ],
  "candidates": [
    {
      "candidate_id": "pc_...",
      "source_kind": "agent",
      "source_id": "agent-writer:candidate-a",
      "summary": "Fix off-by-one in batch slicing.",
      "assumptions": ["The input list is already validated upstream."],
      "touched_files": ["py/swarm_do/pipeline/executor.py"],
      "diff_sha256": "sha256:...",
      "diff_path": "candidates/pc_001.patch"
    }
  ]
}
```

Validation rules:

- `candidate_id` is deterministic from `base_sha + diff_sha256 + source_id`.
- `diff_path` must be relative to the artifact directory and must not traverse.
- Every touched file must stay inside the repo and respect `allowed_files` and
  `blocked_files`.
- Diffs must be unified diffs that pass `git apply --check` before any command
  runs.
- The artifact must not contain provider/private reasoning. Put only summaries,
  assumptions, hashes, and patch text or patch paths.

## Validation Contract

Validation is deterministic and bounded. The runner should accept command
strings because `work_units.v2.validation_commands` already uses strings, but
it must execute them with a fixed contract:

- `cwd` is the candidate worktree root unless a command-local repo-relative
  `cwd` is provided.
- Environment is minimal plus an explicit allowlist; secrets are not inherited
  by default.
- Each command has `timeout_seconds`, an output byte cap, and an expected exit
  code, defaulting to `0`.
- Required commands determine pass/fail. Optional commands are evidence only.
- The runner records stdout/stderr sidecar paths, exit code, elapsed seconds,
  timeout status, and truncated-output flags.

Validation command source order:

1. `work_units.v2.validation_commands` and `expected_results`, when validating
   a decomposed unit.
2. Explicit commands in the patch-candidates artifact.
3. Operator-provided CLI commands for benchmark runs.
4. `git apply --check` only. This is allowed, but produces low-confidence
   ranking and cannot promote `agentless-repair`.

## Temp Worktree Lifecycle

Candidate validation must never mutate the operator's primary worktree.

- Create candidate worktrees under
  `.swarm-do/candidates/<run_id>/<candidate_id>/`.
- Start from `base_sha`, preferably as a detached worktree or a namespaced
  throwaway branch such as `swarm/<run_id>/candidate/<candidate_id>`.
- Apply exactly one candidate patch per worktree.
- Run validation commands inside that candidate worktree.
- Remove worktrees by default after results are written.
- Support `--keep-worktrees` for debugging, but mark retained paths in the
  manifest and telemetry.
- Cleanup failures are non-fatal but must be surfaced in the result artifact
  and `run_events`.

This reuses the existing worktree discipline for large-project-manager while
adding isolation for non-mutating patch trials.

## Ranking Contract

Ranking should be deterministic in v1. LLMs may generate candidates, but the
validator selects by evidence:

1. Reject candidates that fail path policy, do not apply, or fail required
   validation commands.
2. Prefer candidates with all required commands passing.
3. Prefer fewer optional-command failures.
4. Prefer smaller blast radius: fewer files, fewer changed lines, fewer
   non-local edits.
5. Prefer stronger localization match when the artifact includes localized
   files or spans.
6. Prefer lower-risk files when risk tags indicate public API, migration,
   security, or generated-file concerns.

If two or more candidates remain tied after deterministic scoring, emit
`selection_status: needs_human`. Do not ask a same-context writer or judge to
break the tie silently.

## Handoff Contract

The primitive is non-mutating. Its output is evidence, not a commit.

Write:

- `patch-candidate-results.json`: normalized status for every candidate.
- `patch-candidate-results.full.json`: full logs and per-command sidecars.
- `patch-candidate.manifest.json`: paths, truncation counts, cleanup status.
- `winning.patch` when exactly one winner exists.
- a prompt-safe evidence summary for downstream agents.

The normal `agent-writer` remains the first mutating actor. It receives the
winning patch and evidence, applies or adapts the patch, reruns validation, and
may reject the patch in notes if it is stale, out of scope, or unsafe.

## Telemetry

Use per-run artifacts for rich details and a compact ledger for cross-run
comparison.

Recommended rows:

- `patch_candidate_validations.jsonl` registered in
  `swarm_do.telemetry.registry.LEDGERS`, one row per candidate validation.
- `run_events.jsonl` entries for lifecycle events:
  `patch_candidates_started`, `patch_candidate_validated`,
  `patch_candidate_selected`, `patch_candidates_cleanup_failed`.

Ledger fields should include `run_id`, `issue_id`, `stage_id`, `work_unit_id`,
`candidate_id`, `source_kind`, `source_id`, `base_sha`, `diff_sha256`,
`apply_status`, `required_pass_count`, `required_fail_count`,
`optional_fail_count`, `selected`, `selection_status`, `score`,
`validation_wall_clock_seconds`, `artifact_path`, `schema_ok`, and
`cleanup_status`.

Do not mutate `runs.v2` for this. `runs` stays the backend-run ledger;
candidate validation is a separate deterministic runtime surface.

## Shared Consumers

This substrate improves more than `agentless-repair`:

- `competitive`: writers can emit patch artifacts that are validated in
  isolated worktrees before any synthesis or handoff, reducing cross-writer
  mutation risk.
- Provider-generated patch suggestions: provider shims can stay read-only by
  emitting candidate diffs instead of editing the repo.
- Benchmarks: fixed candidate sets can be replayed through the same validator
  and compared by pass rate, ranking quality, wall time, and cleanup failures.
- Large projects: work-unit patches can be preflighted independently before
  integration-branch merge attempts.
- Review-finding autofix trials: each finding can spawn one or more candidate
  patches, validate them without touching the main worktree, and hand only
  evidence to the writer.
- Repair loop: a future revision pass can receive a validated patch suggestion
  rather than ungrounded prose.

## Agentless-Repair Consumer Plan

Once the substrate is stable, add `agentless-repair` as an experimental preset:

```text
agent-localize-bug or agent-debug -> candidate patch generation
  -> patch_candidates validation/ranking -> agent-writer handoff
  -> spec-review + provider-review + agent-review
```

For v1, prefer a narrow `agent-localize-bug` role if the preset is bug-fix
specific. Reusing `agent-debug` is acceptable for dogfood only when the
candidate generator can still receive exact files/spans and validation commands.

Promotion gate:

- It beats `repair-loop` or `balanced` on accepted fixes or
  wall-time-per-accepted-fix for bug-like tasks.
- It does not increase manual cleanup or merge-conflict interventions.
- It keeps writer mutations single-threaded and auditable.
- It produces useful artifacts for at least one non-agentless consumer above.

## Build Order

1. Add the artifact schema, Python validator, and `lint` CLI with unit tests.
2. Add safe apply checks, path-policy enforcement, fake fixtures, and result
   artifacts.
3. Add temp worktree validation with timeout/output caps and cleanup tests.
4. Add deterministic ranking, tie handling, and prompt-safe evidence summaries.
5. Add telemetry registry/schema entries and run-event emission.
6. Dogfood via manual CLI on benchmark fixtures and review-finding autofix
   trials.
7. Add the explicit `patch_candidates` pipeline stage kind.
8. Add the experimental `agentless-repair` preset as a consumer.

## Open Decisions

- Whether the stage kind should be named `patch_candidates` or generalized to
  a later `tool` stage. Prefer the narrower name until a second deterministic
  non-agent helper proves the abstraction.
- Whether retained candidate worktrees should expire through a cleanup command
  or piggyback on telemetry purge.
- Whether candidate generation should start as agent fan-out only, provider
  suggestions only, or both behind the same artifact contract.
- Whether localization can reuse `agent-debug` for the first dogfood run or
  needs `agent-localize-bug` immediately.

Until these decisions are made, use `repair-loop` for normal implementation
work and treat Agentless-style repair as a benchmark-oriented design track.
