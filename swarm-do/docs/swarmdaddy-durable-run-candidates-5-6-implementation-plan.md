# SwarmDaddy Durable Run Candidates 5-6 Implementation Plan

Status: implementation-ready after blocker-resolution revision
Date: 2026-04-30
Revised: 2026-05-01
Source research: `docs/swarmdaddy-durable-run-capabilities-research-plan.md`
Builds on:

- `docs/swarmdaddy-durable-run-candidates-1-2-implementation-plan.md`
- `docs/swarmdaddy-durable-run-candidates-3-4-implementation-plan.md`
- `docs/phase-session-durable-recovery-plan.md`
- `docs/auditable-worktree-launcher-hardening-plan.md`

## Goal

Turn durable-run capability candidates 5 and 6 into concrete work for the
current SwarmDaddy runtime:

1. Crash-Resumable Engineering Runs.
2. Auditable Worktree Choreography.

The implementation should extend the existing durable phase-session harness. It
should not add a second orchestration protocol, bypass `phase_sessions.v1.json`,
silently mutate the user's source checkout, or promise deterministic replay of
model output.

## Research Findings

The current tree already implements major foundations that the original
research plan treated as future work:

- `py/swarm_do/pipeline/phase_sessions.py` owns durable phase state, leases,
  child PID/process-group metadata, attempt history, evidence paths,
  cancellation, archival, and explicit retry/block/adoption transitions.
- `py/swarm_do/pipeline/phase_recovery.py` reconciles active and stale phase
  attempts before the pump claims new work. It can adopt valid artifacts after
  parent failure, schedule retries, gate deterministic failures, and preserve
  active attempts when child liveness is unknown.
- `py/swarm_do/pipeline/phase_pump.py` calls recovery before every claim, starts
  `claude-print` children in a new process session, refreshes running leases,
  records child metadata, and writes checkpoints after adopted completions.
- `py/swarm_do/pipeline/context_bundle.py` injects recovery-context markdown
  into retry prompts.
- `bin/swarm phases recover <run-id> --dry-run` already provides the read-only
  reconcile command the candidate requested.
- `py/swarm_do/pipeline/execution_worktree.py` implements the run-scoped
  `safe-worktree` launcher path: data-dir worktree, run execution branch,
  copied ignored artifacts, dirty-source blocking, dry-run adoption, and guarded
  cleanup.
- `py/swarm_do/pipeline/execution_workspace.py` automatically selects
  `safe-worktree` when a prepared run launches from a sensitive source path and
  rewrites prompt-visible source paths.
- `phase_recovery.py`, `phase_evidence.py`, `schemas/phase_sessions.schema.json`,
  and `schemas/phase_attempt_evidence.schema.json` already preserve safe
  worktree metadata in recovery and attempt evidence.
- `py/swarm_do/pipeline/worktrees.py` still contains the older per-unit
  worktree helpers. Those helpers write under `.swarm-do/worktrees` in the
  source checkout and should not be reused for sensitive-path execution.

The right plan is therefore incremental hardening, matrix coverage, and
integration semantics. Do not rebuild the runtime.

## Second-Pass Validation

A follow-up analysis found real execution-readiness gaps in the first revision.
These findings are validated against the current code and are resolved in this
revision:

| Finding | Validation | Resolution |
| --- | --- | --- |
| `adoption_state` migration was unresolved | Valid. `execution_worktree.py` treats `completed` as cleanup-eligible, but no transition writes it and the first revision rejected it without a migration path. | P0 now defines legacy `completed` normalization to `complete_no_changes`, with exact tests. |
| Active recovery precedence was ambiguous | Valid. `_active_phase_decision()` checks lease expiry before child liveness and does not pin `alive=None` or cross-host behavior. | Candidate 5 now freezes the precedence table and action strings. |
| Schema shapes were undefined | Valid. The first revision named `run_execution_worktree.schema.json` but did not give JSON types or reconcile overlap with evidence schemas. | Candidate 6 P0 now includes a concrete schema shape and evidence-schema delta. |
| Schema additivity was not addressed | Valid. Existing schemas use `additionalProperties: false`; new fields must land with schema and reader changes in the same slice. | A compatibility section now defines the additivity and versioning posture. |
| CLI wiring for `integrate-run` was missing | Valid. Existing `adopt-run` and `cleanup-run` are registered in `py/swarm_do/pipeline/cli.py`, but `integrate-run` was not assigned a registration site. | P1 now names `cmd_worktrees`, parser registration, and formatter/test locations. |
| Action string was undecided | Valid. "Such as" was not shippable. | Candidate 5 now freezes exact action strings. |
| Definition of Done was not testable | Valid. Several DoD bullets were outcome prose without named checks. | Candidate 5 and 6 now include named tests and test-backed DoD. |

## Final Recommendation

Ship Candidate 5 first as a formal crash-resume matrix plus one safety fix:
never retry an expired same-host active lease while the recorded child process is
still provably alive. The runtime already has most of the reconciliation logic;
the highest-value work is to make the cases explicit, fixture-backed, and
idempotent.

Then ship Candidate 6 in three layers:

1. Harden the current run-scoped safe worktree.
2. Add a data-dir-owned integration worktree and manifest-backed conflict/scope
   evidence.
3. Only then add per-unit or per-phase isolated worktrees for parallel work.

The current code is ready for the first two layers of Candidate 6. It is not yet
ready for parallel per-unit execution because the phase-session pump is still a
sequential whole-phase launcher and the only per-unit worktree helper mutates
the source checkout.

## Compatibility Boundaries

These constraints apply to both candidates:

1. Do not add required fields to `phase_sessions.v1.json` or existing attempt
   evidence manifests in P0. Existing in-flight runs must remain readable.
2. When adding optional fields to a schema with `additionalProperties: false`,
   update the schema, writer, reader, and tests in the same commit. Runtime code
   must not emit a new field before the schema accepts it.
3. Keep `phase_attempt_evidence.schema.json` at `schema_version=1` for the P0
   safe-worktree metadata additions because they are optional internal manifest
   fields. If a future change adds required fields or changes semantics, create
   schema version 2 and make the reader accept versions 1 and 2.
4. Normalize legacy run execution worktree manifests at read time. Do not reset
   branches or delete worktrees during migration.
5. Legacy source-checkout worktree mutators in `worktrees.py` remain for
   compatibility, but sensitive source paths must fail closed unless an explicit
   operator override is added for legacy behavior.

## Candidate 5 - Crash-Resumable Engineering Runs

### Requirement

Make long-running engineering runs resilient to parent death, child death,
terminal close, machine sleep, compaction, interrupted model sessions, and
rerunning the pump. Reconciliation must never duplicate active work when child
liveness proves work is still running.

### Current Behavior

Already covered:

- Parent death after valid artifacts: recovery adopts current-attempt artifacts
  through `adopt_phase_result()`.
- Non-zero launcher with valid artifacts: recovery records
  `launcher_nonzero_with_artifacts` and adopts.
- Non-zero launcher without artifacts: recovery records
  `launcher_nonzero_no_artifacts` and applies retry policy.
- Zero-returncode contract failure: recovery gates as deterministic instead of
  blindly retrying.
- Active unexpired attempt with unknown child liveness: recovery preserves
  `active`.
- Same-host dead child or process-group mismatch: recovery records
  `child_process_dead_no_artifacts` and applies retry policy.
- Lease expiry without artifacts: recovery records `lease_expired_no_artifacts`
  and applies retry policy.
- Retry prompts receive prior recovery context.
- `resume` remains read-only; mutation belongs to `phases recover`,
  `phases pump`, or `do --prepared --phase-sessions auto`.

Important gap:

- `_active_phase_decision()` checks lease expiry before same-host child
  liveness. After machine sleep or a missed lease refresh, an expired lease with
  a still-running same-host child can be retried, which risks duplicate work.

### Implementation Decision

Keep the state model unchanged. Add a matrix-driven test suite and adjust the
active-attempt decision order.

Recovery should use this precedence for active phases with no valid artifacts:

| Case | Action string | Status/failure |
| --- | --- | --- |
| Same host, child PID recorded, `_pid_alive(pid)` is `False` | `child_dead` | recover with `child_process_dead_no_artifacts` |
| Same host, child alive, expected process group recorded and `_process_group_matches()` is `False` | `child_dead` | recover with `child_process_dead_no_artifacts` |
| Same host, child alive, expected process group recorded and `_process_group_matches()` is `None` | `active_preserved_child_unknown` | preserve `active` |
| Same host, child alive, no expected process group or process group matches | `active_preserved_child_alive` | preserve `active`, even if lease expired |
| Same host, child liveness is `None`, lease unexpired | `active_preserved_child_unknown` | preserve `active` |
| Same host, child liveness is `None`, lease expired | `lease_expired` | recover with `lease_expired_no_artifacts` |
| Cross host, lease unexpired | `active_preserved_cross_host` | preserve `active` |
| Cross host, lease expired | `lease_expired_cross_host` | recover with `lease_expired_no_artifacts` |
| No child PID, lease unexpired | `active_preserved_no_child_metadata` | preserve `active` |
| No child PID, lease expired | `lease_expired` | recover with `lease_expired_no_artifacts` |

`None` from `_pid_alive()` or `_process_group_matches()` means inconclusive
because of `PermissionError` or `OSError`; it is not proof of death.

These action strings are recovery action details, not `failure_kind` values. Do
not add them to `failure_taxonomy.py`.

Do not add a new phase status. If implementation needs to record the
expired-but-live case, use a run event detail and keep the phase status
`running`.

### P0 Work Breakdown

1. Add a crash-resume matrix fixture helper.

   - New test helper: `py/swarm_do/pipeline/tests/phase_crash_fixtures.py`.
   - Build helpers for: prepared run, active attempt, command metadata,
     current-attempt result/handoff artifacts, partial artifacts, expired lease,
     child PID/process-group patches, and launcher result shapes.
   - Keep the helper fixture-backed and local. Do not invoke live Claude.

2. Add explicit matrix tests in `test_phase_recovery.py` or a new
   `test_phase_crash_resume.py`.

   Required rows:

   | Scenario | Expected result |
   | --- | --- |
   | parent died after `complete` artifacts | adopt completion and continue |
   | parent died after `blocked` artifacts | adopt blocked status and stop |
   | parent died after retryable `failed` artifacts | policy retry or gate based on handoff |
   | non-zero launcher with valid artifacts | adopt with `launcher_nonzero_with_artifacts` |
   | child died with no artifacts | retry or gate with `child_process_dead_no_artifacts` |
   | child died with partial invalid artifacts | recovery retry or deterministic gate |
   | zero-returncode no-artifact attempt | deterministic human gate |
   | expired lease with no child liveness | retry or gate with `lease_expired_no_artifacts` |
   | expired lease with same-host live child | preserve active, no retry history append |
   | unexpired active lease with unknown child liveness | preserve active |
   | retry-waiting in the future | report wait without claiming |
   | retry-waiting past due | release to pending without launching |

3. Fix `_active_phase_decision()` in `phase_recovery.py`.

   - Check same-host child death and live-child evidence before TTL expiry.
   - Use only the action strings in the precedence table above.
   - Include child PID, process group, lease expiry, and host evidence in the
     action details returned by recovery.
   - Preserve cross-host attempts until TTL expiry, then recover by lease.

4. Add idempotency assertions.

   - Running `reconcile_phase_sessions(..., dry_run=True)` does not mutate state.
   - Running mutating recovery twice after a retry decision does not append
     duplicate attempt-history records.
   - Running mutating recovery twice after adopting artifacts does not re-adopt
     or rewrite terminal phase state.
   - Preserved active attempts do not append failure history.

5. Add named P0 tests.

   Put these in `py/swarm_do/pipeline/tests/test_phase_crash_resume.py` unless
   a smaller extension to `test_phase_recovery.py` is clearer:

   - `test_parent_death_complete_artifacts_adopts_once`
   - `test_parent_death_blocked_artifacts_adopts_and_stops`
   - `test_parent_death_retryable_failed_artifacts_uses_policy_once`
   - `test_child_dead_no_artifacts_records_retryable_lifecycle_failure`
   - `test_child_dead_partial_artifacts_uses_recovery_retry_or_gate`
   - `test_zero_returncode_no_artifacts_human_gates`
   - `test_expired_same_host_live_child_preserves_active`
   - `test_same_host_live_child_unknown_process_group_preserves_active`
   - `test_expired_same_host_unknown_child_liveness_recovers_by_lease`
   - `test_expired_cross_host_active_lease_recovers_by_lease`
   - `test_unexpired_cross_host_active_lease_is_preserved`
   - `test_retry_waiting_future_reports_wait_without_claim`
   - `test_retry_waiting_past_due_releases_without_launch`
   - `test_recover_dry_run_does_not_mutate_state`
   - `test_recovery_after_retry_decision_is_idempotent`
   - `test_recovery_after_artifact_adoption_is_idempotent`

6. Keep read-only status and resume surfaces stable in P0.

   - Do not add new phase statuses.
   - Do not mutate `resume.py` in P0.
   - The liveness explanation lives in the `reconcile_phase_sessions()` action
     payload under the frozen action strings above.
   - Add operator-facing resume/status polish only in P1 if the P0 tests show
     the existing surfaces are insufficient.

7. Validate the matrix.

   - Run:
     `PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_phase_recovery`
   - If the new matrix lands in its own file, run it directly as well.
   - Run `test_phase_pump.py`, `test_resume.py`, and `test_context_bundle.py`
     after changing any shared transition or prompt behavior.

### P1 Work Breakdown

1. Add active-lease repair for the expired-but-live same-host case.

   - Implement only for action `active_preserved_child_alive`.
   - In mutating recovery, extend `lease_expires_at` to
     `now + running_ttl_seconds` without changing `lease_owner`.
   - Append `phase_session_active_preserved` to
     `schemas/telemetry/run_events.schema.json` before emitting it.
   - Event details must include `phase_id`, `attempt`, `child_pid`,
     `process_group_id`, old lease expiry, new lease expiry, and
     `action="active_preserved_child_alive"`.
   - `--dry-run` reports the repair but does not write it.

2. Add archive-aware crash recovery tests.

   - Verify `phases archive` preserves state, launches, results, handoffs,
     recovery markdown, and evidence manifests.
   - Verify `phases evidence --include-archived` or the existing attempt summary
     path still explains old attempts after archive.

3. Add machine-sleep style timing tests.

   - Simulate a running child whose lease expired while the process group is
     still live.
   - Simulate a process group that changed underneath the PID and confirm the
     existing dead-child recovery path still fires.

4. Document the matrix in `README.md` or a small durable recovery guide.

   - Keep the operator workflow short: `phases status`, `phases recover
     --dry-run`, `phases recover`, `phases evidence`, then `phases pump`.
   - Do not imply that `resume` mutates state.

### P2 Work Breakdown

1. Add a sanitized crash-run fixture pack.

   - Capture representative `phase_sessions.v1.json`, `command.json`,
     stdout/stderr tails, result/handoff artifacts, and evidence manifests.
   - Redact local paths and transcripts.
   - Use the pack for regression tests only; do not market it as deterministic
     model replay.

2. Add support-bundle export if Candidate 2 needs it.

   - Keep this out of Candidate 5 implementation. If support-bundle export
     becomes necessary, implement it as a separate Candidate 2 follow-up.
   - That follow-up should bundle manifest pointers, attempt evidence, recovery
     notes, and run events.
   - Keep raw prompts, raw transcripts, and env values out unless an explicit
     local-only flag asks for them.

### Out Of Scope

- Live long-running Claude crash tests in CI.
- Replaying model outputs.
- Starting a background daemon.
- Letting `/swarmdaddy:resume` mutate `phase_sessions.v1.json`.

### Definition Of Done

Candidate 5 is complete when the crash matrix is fixture-backed, the expired
same-host-live-child case cannot duplicate work, recovery is idempotent across
the matrix, and the operator has a clear dry-run path before mutation.

Candidate 5 DoD is test-backed by:

- `test_expired_same_host_live_child_preserves_active`
- `test_expired_same_host_unknown_child_liveness_recovers_by_lease`
- `test_expired_cross_host_active_lease_recovers_by_lease`
- `test_recover_dry_run_does_not_mutate_state`
- `test_recovery_after_retry_decision_is_idempotent`
- `test_recovery_after_artifact_adoption_is_idempotent`
- `test_retry_waiting_future_reports_wait_without_claim`
- `test_retry_waiting_past_due_releases_without_launch`

## Candidate 6 - Auditable Worktree Choreography

### Requirement

Make implementation work safer by isolating execution in worktrees, preserving
diff evidence, scope-checking changes, integrating through an auditable path,
and retaining enough metadata to clean up or recover without guessing.

### Current Behavior

Already wired from the launcher-hardening plan:

- Sensitive prepared runs launch `claude-print` from
  `<data-dir>/worktrees/<run-id>/repo[/<project-subdir>]`.
- The run execution branch is `swarm/<run-id>/execution`.
- The worktree is created from `prepared_plan.git_base_sha`, falling back to
  `git_base_ref` only when necessary.
- Monorepo subdir and top-level repo shapes are supported.
- Submodules, sparse checkouts, sensitive safe roots, dirty source checkouts,
  existing branch mismatches, and manifest mismatches fail closed.
- Ignored run artifacts are copied into the safe project root and selected JSON
  artifacts are rebased to the safe root.
- `_run_real_claude()` launches with both `cwd` and `PWD` set to the safe
  project root.
- `command.json`, attempt history, and evidence manifests carry safe-worktree
  metadata.
- Recovery diffs the safe project root for safe-worktree attempts.
- `bin/swarm worktrees adopt-run <run-id>` provides dry-run and `--apply`
  copyback.
- `bin/swarm worktrees cleanup-run <run-id>` preserves unadopted worktrees and
  removes adopted worktrees only with `--apply`.

Current gaps:

- The run worktree manifest has no schema file and is not schema-validated.
- `adopt-run --apply` does not yet protect against dirty destination files in
  the original source checkout.
- Adoption blocks path escapes and run artifacts, but it does not yet write a
  first-class scope-check manifest against prepared work-unit allowed/blocked
  files.
- There is no data-dir-owned integration worktree.
- Merge-conflict evidence exists only for the older source-checkout
  `worktrees.py` helper.
- The `completed` cleanup state is allowed by code but no transition currently
  writes it.
- The older `worktrees.py` per-unit helper still writes under
  `.swarm-do/worktrees` in the source checkout.
- `README.md` lists the older worktree commands but not `adopt-run` or
  `cleanup-run`.

### Implementation Decision

Treat `execution_worktree.py` as the canonical Candidate 6 foundation. Do not
extend the old `.swarm-do/worktrees` helper for sensitive or future parallel
execution. Either wrap it with data-dir roots or replace it with run-aware
helpers once per-unit worktrees are ready.

Keep first-slice integration as explicit copyback. Add branch-merge integration
only after scope manifests and dirty-destination checks exist.

### P0 Work Breakdown - Harden Current Run Worktree

1. Add a run execution worktree manifest schema.

   - New schema: `schemas/run_execution_worktree.schema.json`.
   - Validate reads and writes in `execution_worktree.py`.
   - Add `RUN_EXECUTION_WORKTREE_SCHEMA_PATH` and
     `validate_run_execution_worktree_manifest(payload)` in
     `execution_worktree.py`, following the existing schema-validation style in
     `phase_evidence.py`.
   - Use this exact P0 schema shape:

     ```json
     {
       "$schema": "https://json-schema.org/draft/07/schema#",
       "$id": "https://mstefanko-plugins/swarm-do/run_execution_worktree.schema.json#v1",
       "title": "swarm-do run execution worktree manifest",
       "type": "object",
       "additionalProperties": false,
       "required": [
         "schema_version",
         "run_id",
         "source_git_root",
         "source_project_root",
         "safe_git_worktree_root",
         "safe_project_root",
         "project_subdir",
         "branch",
         "base_sha",
         "base_ref",
         "copied_artifacts",
         "adoption_state",
         "created_at",
         "last_used_at"
       ],
       "properties": {
         "schema_version": { "type": "integer", "enum": [1] },
         "run_id": {
           "type": "string",
           "pattern": "^[0-9A-HJKMNP-TV-Z]{26}$"
         },
         "source_git_root": { "type": "string", "minLength": 1 },
         "source_project_root": { "type": "string", "minLength": 1 },
         "safe_git_worktree_root": { "type": "string", "minLength": 1 },
         "safe_project_root": { "type": "string", "minLength": 1 },
         "project_subdir": { "type": "string" },
         "branch": { "type": "string", "minLength": 1 },
         "base_sha": {
           "type": "string",
           "pattern": "^[0-9a-f]{40}$"
         },
         "base_ref": { "type": "string", "minLength": 1 },
         "copied_artifacts": {
           "type": "array",
           "items": {
             "type": "object",
             "additionalProperties": false,
             "required": [
               "source_path",
               "destination_path",
               "relative_path",
               "source_sha256",
               "destination_sha256",
               "kind",
               "transformed"
             ],
             "properties": {
               "source_path": { "type": "string", "minLength": 1 },
               "destination_path": { "type": "string", "minLength": 1 },
               "relative_path": { "type": "string", "minLength": 1 },
               "source_sha256": {
                 "type": "string",
                 "pattern": "^[0-9a-f]{64}$"
               },
               "destination_sha256": {
                 "type": "string",
                 "pattern": "^[0-9a-f]{64}$"
               },
               "kind": { "type": "string", "minLength": 1 },
               "transformed": { "type": "boolean" }
             }
           }
         },
         "adoption_state": {
           "type": "string",
           "enum": [
             "unadopted",
             "adopted",
             "complete_no_changes",
             "preserved",
             "conflicted"
           ]
         },
         "adopted_at": { "type": ["string", "null"], "format": "date-time" },
         "created_at": { "type": "string", "format": "date-time" },
         "last_used_at": { "type": "string", "format": "date-time" },
         "scope_check_path": { "type": ["string", "null"] },
         "conflict_manifest_path": { "type": ["string", "null"] },
         "integration_manifest_path": { "type": ["string", "null"] }
       }
     }
     ```

   - Do not include legacy `completed` in the schema enum.

2. Add legacy manifest normalization.

   - Add `_normalize_run_worktree_manifest(raw: Mapping[str, Any]) ->
     tuple[dict[str, Any], bool]` in `execution_worktree.py`.
   - Normalization rules:
     - missing or null `adoption_state` becomes `unadopted`;
     - `adoption_state="completed"` becomes `complete_no_changes`;
     - missing optional path fields become `None`;
     - unknown fields still fail schema validation after normalization.
   - `_load_manifest()` and `_require_manifest()` return normalized manifests.
   - Any later write through `materialize_run_execution_worktree()`,
     `adopt_run_worktree()`, `cleanup_run_worktree()`, or
     `integrate_run_worktree()` writes the normalized value back.
   - `cleanup_run_worktree()` treats `adopted` and `complete_no_changes` as
     cleanup-eligible. It no longer checks for `completed` after normalization.

3. Add dirty-destination protection to adoption.

   - Before `adopt_run_worktree(..., apply=True)` copies or deletes a path,
     inspect the source checkout for tracked or untracked changes at every
     destination path.
   - Use `git status --porcelain=v1 -z -- <path>` from the source git root and
     project-relative path. A non-empty result blocks that operation with
     `destination_dirty`.
   - Use `git diff --name-only <base_sha> HEAD -- <path>` from the source git
     root and project-relative path. A non-empty result blocks that operation
     with `destination_changed_since_base`.
   - Also block when a delete operation targets a directory.
   - Include blocked destination paths in both JSON and text output.
   - Keep dry-run side-effect free.

4. Add a scope-check manifest for run adoption.

   - Add `build_run_worktree_scope_check(...)` in
     `execution_worktree.py`.
   - Inputs:
     prepared artifact, work-unit sidecars for every phase, safe-worktree
     changed files, blocked paths, and adoption operations.
   - For each changed file record:
     `path`, `status`, matching phase ids, matching work-unit ids, matched
     allowed patterns, matched blocked patterns, and decision.
   - P0 enforcement:
     block `path_escape`, `data/runs/**`, and explicit `blocked_files`
     matches.
   - P0 warning:
     changed files outside `allowed_files` when no reliable phase/unit ownership
     can be inferred.
   - P1 can promote outside-allowed changes to a hard block once fixture
     coverage is strong.
   - `adopt-run` dry-run returns the scope-check object but does not write a
     file.
   - `adopt-run --apply` writes
     `<data-dir>/worktrees/<run-id>/scope-check.json` before copyback and stores
     that path in the run worktree manifest.

5. Add adoption-state transitions.

   - `adopt-run --apply` writes `adoption_state="adopted"`.
   - No new mark-complete command. If `adopt-run --apply` has no copyback
     operations and no blocked paths, it writes
     `adoption_state="complete_no_changes"`.
   - Do not allow cleanup of `unadopted`, `preserved`, or `conflicted`.

6. Extend evidence schema coverage.

   - Add exactly these optional fields to
     `schemas/phase_attempt_evidence.schema.json#/properties/workspace/properties`:

     ```json
     "git_base_ref": { "type": ["string", "null"] },
     "copied_ignored_artifacts": {
       "type": ["array", "null"],
       "items": {
         "type": "object",
         "additionalProperties": true
       }
     }
     ```

   - Update `phase_evidence.py` to emit those fields from `command.json`.
   - Do not add any other evidence fields in P0.
   - Add tests that read the generated `evidence.json` for a safe-worktree
     attempt, not only `command.json`.

7. Guard legacy source-checkout worktree mutators.

   - Update `py/swarm_do/pipeline/cli.py` in `cmd_worktrees` for
     `ensure-integration`, `add-unit`, and `merge`.
   - If `is_sensitive_path(Path(args.repo).resolve(strict=False))` is true,
     return exit code 1 with a message containing
     `legacy source-checkout worktrees are disabled for sensitive repos`.
   - Add `--allow-source-worktree` to those three legacy subcommands. The flag
     is explicit and defaults to false.
   - `names` remains read-only and does not need the guard.

8. Document operator commands.

   - Update the README worktree command list with:
     `bin/swarm worktrees adopt-run <run-id> [--apply] [--json]`
     and
     `bin/swarm worktrees cleanup-run <run-id> [--apply] [--json]`.
   - Mention that cleanup preserves unadopted and conflicted worktrees.

9. Add named P0 tests.

   Add or extend `py/swarm_do/pipeline/tests/test_execution_worktree.py`:

   - `test_manifest_schema_requires_roots_branch_base_and_artifacts`
   - `test_manifest_schema_rejects_unknown_fields`
   - `test_legacy_completed_manifest_migrates_to_complete_no_changes`
   - `test_cleanup_accepts_complete_no_changes_after_legacy_migration`
   - `test_adopt_apply_blocks_dirty_destination`
   - `test_adopt_apply_blocks_destination_changed_since_base`
   - `test_adopt_apply_blocks_delete_directory_operation`
   - `test_adopt_dry_run_returns_scope_check_without_writing_manifest`
   - `test_adopt_apply_writes_scope_check_manifest`
   - `test_adopt_apply_marks_complete_no_changes_when_no_operations`
   - `test_scope_check_blocks_explicit_blocked_files`

   Add or extend `py/swarm_do/pipeline/tests/test_phase_evidence.py`:

   - `test_safe_worktree_evidence_manifest_includes_git_base_ref_and_copied_artifacts`

   Add or extend `py/swarm_do/pipeline/tests/test_phase_cli.py`:

   - `test_legacy_worktree_mutators_refuse_sensitive_repo_without_override`
   - `test_legacy_worktree_mutators_allow_sensitive_repo_with_explicit_override`

10. Validate P0.

   - Run:
     `PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_execution_worktree`
   - Also run:
     `test_phase_pump.py`, `test_phase_recovery.py`, and
     `test_phase_evidence.py` when metadata or evidence schema changes.

### P1 Work Breakdown - Data-Dir Integration Worktree

1. Add an integration worktree resolver.

   - New module or extension:
     `py/swarm_do/pipeline/execution_worktree.py`.
   - Integration root:
     `<data-dir>/worktrees/<run-id>/integration/repo`.
   - Integration branch:
     `swarm/<run-id>/integration`.
   - Base:
     `prepared_plan.git_base_sha`.
   - The source checkout must not be checked out or merged in.

2. Add `worktrees integrate-run`.

   - CLI registration lives in `py/swarm_do/pipeline/cli.py`.
   - Add an `elif args.worktrees_command == "integrate-run"` branch in
     `cmd_worktrees`.
   - Add a parser beside `adopt-run` and `cleanup-run`:
     `p = worktrees_sub.add_parser("integrate-run")`.
   - Parser args:
     positional `run_id`, optional `--data-dir`, `--apply`, `--json`.
   - Add `_format_worktree_integrate(payload)` for text output.
   - Dry-run default:
     `bin/swarm worktrees integrate-run <run-id> [--json]`.
   - Apply:
     `bin/swarm worktrees integrate-run <run-id> --apply`.
   - Dry-run reports source branch, execution branch, integration branch,
     changed files, scope-check result, validation commands, and predicted
     merge command.

3. Merge execution into integration, not source.

   - On `--apply`, merge `swarm/<run-id>/execution` into
     `swarm/<run-id>/integration` inside the integration worktree.
   - If the merge conflicts, leave the integration worktree in place and write:
     `<data-dir>/worktrees/<run-id>/conflict.json`.
   - Record conflicted files, merge command, branch names, base SHA, current
     heads, and `git status --porcelain=v1 -z` details.
   - Mark the run worktree manifest `adoption_state="conflicted"`.
   - Emit the existing `worktree_merge_conflict` run-event type with the new
     conflict manifest path in `details`.

4. Validate integration before source adoption.

   - Reuse the scope-check manifest.
   - Run phase or unit validation commands from the integration worktree when
     present.
   - Do not copy back to the source checkout until integration is clean and
     scope-approved.

5. Add source adoption from integration.

   - Copyback remains the first source-adoption mechanism.
   - It must use the same dirty-destination guard as P0.
   - Later, a git merge into the user's source checkout can be offered only as a
     separate explicit command.

6. Validate P1.

   - Add tests for clean integration merge, conflicting integration merge,
     conflict manifest content, source checkout unchanged during integration,
     and cleanup preserving conflicted worktrees.
   - Named tests:
     - `test_integrate_run_parser_is_registered`
     - `test_integrate_run_dry_run_reports_execution_and_integration_branches`
     - `test_integrate_run_apply_merges_execution_into_data_dir_integration_worktree`
     - `test_integrate_run_conflict_writes_conflict_manifest_and_preserves_worktrees`
     - `test_integrate_run_does_not_mutate_source_checkout`
     - `test_cleanup_preserves_conflicted_worktree`

### P2 Work Breakdown - Per-Unit Or Per-Phase Worktrees

P2 is not ready until P0/P1 are shipped. The missing dependency is not git; it
is the execution contract. The current `claude-print` pump launches whole
phases sequentially, while per-unit parallelism needs durable unit state,
independent writer launch records, post-writer gates, and merge ownership.

1. Design the unit execution state.

   - Use a new durable state file:
     `<data-dir>/runs/<run-id>/unit_sessions.v1.json`.
   - Do not overload `phase_sessions.v1.json` and do not mutate the prepared
     work-unit artifact as execution state.
   - Required fields:
     `phase_id`, `unit_id`, branch, worktree root, base SHA, lease metadata,
     writer status, post-writer report path, scope-check path, merge state,
     attempt history, and cleanup state.

2. Replace or wrap `worktrees.py`.

   - New data-dir unit roots:
     `<data-dir>/worktrees/<run-id>/units/<phase-id>/<unit-id>/repo`.
   - Unit branches:
     `swarm/<run-id>/<phase-id>/<unit-id>`.
   - Branch from the run execution branch or integration branch, never from a
     moving source checkout unless explicitly requested.
   - Keep the old `.swarm-do/worktrees` CLI behavior for compatibility but mark
     it legacy for sensitive execution.

3. Add unit launcher plumbing.

   - Render unit-scoped context with safe paths.
   - Start each unit from its data-dir unit worktree.
   - Record `command.json`, stdout/stderr, evidence, and worktree metadata per
     unit attempt.
   - Use the existing post-writer report to collect changed files, validation,
     blocked-file violations, and budget status.

4. Add unit merge choreography.

   - Merge passing unit branches into the data-dir integration worktree.
   - Preserve conflicts as manifests.
   - Update durable unit state only from coordinator-owned transitions.
   - Do not let a worker mutate shared merge state directly.

5. Add phase completion synthesis.

   - Once all units in a phase are approved/merged, synthesize the phase result
     and handoff artifacts from unit reports and integration evidence.
   - Keep result/handoff schema validation as the source of truth.

6. Validate P2.

   - Fixtures for independent units, dependent units, blocked files, validation
     failure, merge conflict, retry after failed unit, and cleanup.
   - At least one fixture must use a source checkout under fake `.claude` and
     prove no `.swarm-do/worktrees` path is used.

### Out Of Scope

- Auto-merging into the user's active source checkout without a dry run.
- Removing failed, conflicted, blocked, or unadopted worktrees by default.
- Reusing `.swarm-do/worktrees` for sensitive execution.
- Parallel unit execution before a durable unit-state contract exists.
- Tool-result rewriting interposers.

### Definition Of Done

Candidate 6 P0 is complete when the current safe-worktree path has a validated
manifest, dirty-destination adoption guard, scope-check manifest, evidence-schema
coverage, and documented operator commands.

Candidate 6 P1 is complete when integration happens in a data-dir worktree,
conflicts become durable evidence, source checkout state is unchanged until an
explicit adoption step, and cleanup preserves unresolved worktrees.

Candidate 6 P2 is complete when per-unit or per-phase worktrees use data-dir
roots, durable unit state, post-writer reports, scope-gated merges, and conflict
manifests without relying on source-checkout `.swarm-do/worktrees`.

Candidate 6 DoD is test-backed by the named P0/P1 tests above. A writer should
not mark P0 complete without passing the manifest migration tests, dirty
destination tests, scope-check tests, safe-worktree evidence test, and legacy
mutator guard tests.
