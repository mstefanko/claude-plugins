# SwarmDaddy Durable Run Candidates 5-6 Implementation Plan

Status: implementation-ready after codebase research
Date: 2026-04-30
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

1. If same-host child PID is recorded and process liveness proves the child is
   dead, recover with `child_process_dead_no_artifacts`.
2. If same-host child PID is recorded and the child is alive with a matching or
   unknown process group, preserve `active` even when the persisted lease is
   expired.
3. If child liveness is unknown and the lease is unexpired, preserve `active`.
4. If child liveness is unknown and the lease is expired, recover with
   `lease_expired_no_artifacts`.
5. If no child PID exists, use the lease TTL as the source of truth.

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
   - Add an action such as `active_preserved_child_alive` for the preserved
     live-child case.
   - Include child PID, process group, lease expiry, and host evidence in the
     action details returned by recovery.
   - Preserve current behavior for cross-host attempts: unknown liveness waits
     for TTL expiry before recovery.

4. Add idempotency assertions.

   - Running `reconcile_phase_sessions(..., dry_run=True)` does not mutate state.
   - Running mutating recovery twice after a retry decision does not append
     duplicate attempt-history records.
   - Running mutating recovery twice after adopting artifacts does not re-adopt
     or rewrite terminal phase state.
   - Preserved active attempts do not append failure history.

5. Tighten phase-status and resume output if needed.

   - `phase_status()` should expose enough active-attempt liveness metadata for
     operators to understand why recovery preserved active work.
   - `resume.py` stays read-only but should include the existing recovery
     command recommendation when a phase-session run is active, retry-waiting,
     retry-exhausted, blocked, or drifted.

6. Validate the matrix.

   - Run:
     `PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_phase_recovery`
   - If the new matrix lands in its own file, run it directly as well.
   - Run `test_phase_pump.py`, `test_resume.py`, and `test_context_bundle.py`
     after changing any shared transition or prompt behavior.

### P1 Work Breakdown

1. Add an optional active-lease repair event.

   - If a same-host child is live but the lease is expired, mutating recovery may
     extend `lease_expires_at` without changing `lease_owner`.
   - Append a run event such as `phase_session_active_preserved` with child
     liveness details.
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

   - Bundle manifest pointers, attempt evidence, recovery notes, and run events.
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
   - Required fields:
     `schema_version`, `run_id`, source/safe roots, `project_subdir`, branch,
     `base_sha`, `base_ref`, `copied_artifacts`, `adoption_state`,
     `created_at`, and `last_used_at`.
   - Define `adoption_state` as a closed enum. Prefer:
     `unadopted`, `adopted`, `complete_no_changes`, `preserved`, `conflicted`.
     Avoid the ambiguous existing `completed` value unless a migration maps it
     to a clearer state.

2. Add dirty-destination protection to adoption.

   - Before `adopt_run_worktree(..., apply=True)` copies or deletes a path,
     inspect the source checkout for tracked or untracked changes at every
     destination path.
   - Block apply with `destination_dirty` if a destination changed since the run
     base or since the dry-run report.
   - Include blocked destination paths in both JSON and text output.
   - Keep dry-run side-effect free.

3. Add a scope-check manifest for run adoption.

   - Write:
     `<data-dir>/worktrees/<run-id>/scope-check.json`.
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

4. Add adoption-state transitions.

   - `adopt-run --apply` writes `adoption_state="adopted"`.
   - A dry run with no copyback operations and no blocked paths may offer a
     separate `mark-complete-no-changes` command or set
     `complete_no_changes` only under an explicit `--apply` action.
   - Do not allow cleanup of `unadopted`, `preserved`, or `conflicted`.

5. Extend evidence schema coverage.

   - Add missing safe-worktree fields to
     `schemas/phase_attempt_evidence.schema.json` if needed, especially
     `git_base_ref` and copied-artifact summaries.
   - Add tests that read the generated `evidence.json` for a safe-worktree
     attempt, not only `command.json`.

6. Document operator commands.

   - Update the README worktree command list with:
     `bin/swarm worktrees adopt-run <run-id> [--apply] [--json]`
     and
     `bin/swarm worktrees cleanup-run <run-id> [--apply] [--json]`.
   - Mention that cleanup preserves unadopted and conflicted worktrees.

7. Validate P0.

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

   - Copyback may remain the first source-adoption mechanism.
   - It must use the same dirty-destination guard as P0.
   - Later, a git merge into the user's source checkout can be offered only as a
     separate explicit command.

6. Validate P1.

   - Add tests for clean integration merge, conflicting integration merge,
     conflict manifest content, source checkout unchanged during integration,
     and cleanup preserving conflicted worktrees.

### P2 Work Breakdown - Per-Unit Or Per-Phase Worktrees

P2 is not ready until P0/P1 are shipped. The missing dependency is not git; it
is the execution contract. The current `claude-print` pump launches whole
phases sequentially, while per-unit parallelism needs durable unit state,
independent writer launch records, post-writer gates, and merge ownership.

1. Design the unit execution state.

   - Decide whether unit state lives in a new
     `unit_sessions.v1.json`, in phase-session state, or in the existing
     work-unit artifact plus run events.
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

