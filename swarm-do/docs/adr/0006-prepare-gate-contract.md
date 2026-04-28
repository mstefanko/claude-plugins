# ADR 0006: Prepared Run Artifact Contract

Date: 2026-04-27

## Status

Accepted (2026-04-27).

## Context

Today the `/swarmdaddy:prepare` -> `/swarmdaddy:do` handoff is implicit: the
`plan inspect` step writes `inspect.v1.json` and a `runs/index.jsonl` row,
but downstream review, normalize, decompose, and acceptance stages each
re-derive plan content, run state, and trust assumptions from scratch.
There is no single artifact that pins what was reviewed, what was
decomposed, what the operator accepted, or what the executor is running
against. Phase 0 §J of the prepare-gate plan also confirms that no
trust-boundary helper exists for plan-relative paths today: every consumer
hand-rolls `Path(...)` resolution. We need one signed contract that
review -> normalize -> decompose -> acceptance -> execution all share, plus
fail-closed validation at every read.

## Decision

We introduce `prepared_plan.v1.json` as the artifact-as-contract layer for
the prepare gate. The five locked-in decisions:

1. **Artifact-as-contract.** `runs/<run_id>/prepared_plan.v1.json` is the
   sole source of truth across stages. Writes go through the atomic helper
   from `run_state.py:144` (`NamedTemporaryFile` -> `fsync` -> `os.replace`)
   so partial writes can never be observed. The schema is `#v1`; bumps
   require a coordinated change across stages.
2. **Status state machine.** `draft -> ready_for_acceptance -> accepted`
   (or `-> needs_input -> ready_for_acceptance`); `-> stale` is a
   recoverable detection state; `-> rejected` is terminal. Only
   `accept_prepared()` may flip status to `accepted`, and only after
   re-running schema, trust-boundary, and stale checks. There is no
   `force_accept` shortcut.
3. **Stale detection sources.** `check_stale()` surfaces drift across four
   sources: whole-plan sha, prepared-plan sha, `git_base_sha`, and
   per-phase `cache_key`. `cache_key` composes phase content sha,
   prepared-plan sha, plan-context sha, prepared-plan schema version,
   work-units schema version, the decompose role version, and the prepare
   policy version into a single sha256 so any drift surfaces.
4. **Trust-boundary discipline.** Every path field round-trips through
   `canonicalize(path, *, repo_root)`. Absolute paths, `..` segments,
   empty strings, and resolved paths that escape `repo_root` all fail
   closed. `Path.resolve(strict=False)` is used so missing leaves still
   validate. Validation runs at write time AND at load time so a
   tampered-with on-disk artifact cannot bypass the boundary.
5. **Beads-optionality.** `swarm-do/py/swarm_do/pipeline/prepare.py` does
   not import `bd`. Tests run with no rig. This keeps the prepare gate
   usable in repositories that have not initialized the Beads stealth rig.

## Phase 6 Measurement Addendum

Phase 6 adds observation-only telemetry for promotion decisions. It does not
enable `--prepare --continue`, semantic decomposition promotion, docs gating,
or spec-review gating by default.

Additional decisions:

1. **Prepare emits lifecycle rows, not a new ledger.** Prepare uses the
   existing `telemetry/run_events.jsonl` ledger and `append_run_event` writer.
   Rows are validated against `schemas/telemetry/run_events.schema.json` before
   they are appended.
2. **`/swarmdaddy:do --prepared` remains pure consumption.** Dispatch emits
   `prepare_dispatch_started` only after the accepted artifact passes schema,
   trust-boundary, stale, sidecar hash, and work-unit lint checks. It still
   performs no decomposition and ignores the legacy `decompose.mode` preset
   field.
3. **Plan review remains bounded.** The prepare lifecycle records lint,
   review, safe-fix, ready, accepted, stale-rejected, and dispatch events, but
   the review/normalize loop still caps at 3 iterations before `needs_input`.
4. **Acceptance remains singular.** `prepare_accepted` means the operator
   accepted the whole prepared package: review findings, prepared markdown,
   and work-unit artifacts together.
5. **Phase 7 needs scorecard evidence.** `docs/eval-recipes.md` owns the
   promote/hold/rollback scorecard. Phase 7 may proceed only when dogfood data
   shows non-regressive `NEEDS_CONTEXT`, spec-mismatch, review-failure, stale
   dispatch, and doc-stage skip metrics.

## Consequences

- Future phases (2-8) layer review findings, decomposition, acceptance UX,
  resume integration, telemetry, ADR addenda, and operator docs on top of
  this artifact without re-deriving the artifact shape.
- The CLI surface gains `bin/swarm plan accept <run-id>` and
  `bin/swarm plan reject <run-id>` as siblings of the existing
  `plan inspect` and `plan decompose` subparsers; the existing
  `plan inspect` JSON shape is unchanged (regression-tested).
- Downstream resume flows continue to use `STATUS_PREPARED` from
  `resume.py:22` independently in Phase 1; integration with the prepared
  artifact is wired in a later phase.
- The schema is `#v1`; subsequent extensions (e.g. richer review_findings
  shapes) are additive within v1 only when fields remain optional, or
  require a coordinated v2 bump otherwise.
- Three minor internal-API decisions taken under coordinator `--auto`
  during Phase 1 are recorded here so spec-review can challenge them:
  - **Q1 canonicalize edge cases.** `Path.resolve(strict=False)` is used;
    empty strings are rejected; resolved paths escaping `repo_root` are
    rejected. Known limitations: case-insensitive filesystems (default on
    macOS / Windows) cannot distinguish `Plan.md` from `plan.md`;
    Windows drive letters / UNC paths are out of scope for v1.
  - **Q3 reject source states.** `reject_prepared` accepts source states
    `draft`, `ready_for_acceptance`, `needs_input`, `stale`. From
    `accepted` or `rejected`, reject is an idempotent no-op (returns the
    existing artifact path; does not raise). This avoids surprising errors
    when a rejection request races another agent finalizing the run.
  - **Q4 accept transition errors.** Calling `accept_prepared` from any
    state other than `ready_for_acceptance` raises
    `InvalidPreparedTransition`, a `ValueError` subclass defined in
    `prepare.py`. The error message includes the current status string so
    operators can debug without re-loading the artifact.
