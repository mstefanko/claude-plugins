# Auditable Worktree Launcher Hardening Plan

Date: 2026-04-30

## Purpose

This plan rolls the Round 2 sensitive-path-write recommendation into the
Auditable Worktree Choreography candidate from
`docs/swarmdaddy-durable-run-capabilities-research-plan.md`.

The target outcome is that swarmdaddy launches writer phases from a real,
non-sensitive checkout outside `~/.claude`, while preserving enough evidence to
diff, scope-check, recover, and integrate the resulting changes.

## Validated Findings

1. The worktree direction is structurally sound for path spelling. If the writer
   runs from a real checkout under a safe data-dir path, then `pwd`,
   `os.getcwd()`, `Path.resolve()`, `git rev-parse --show-toplevel`, and most
   tool error paths report the safe location instead of the plugin marketplace
   path.

   This is not a containment boundary. A git worktree still shares git metadata
   with the source checkout, and commands such as `git rev-parse
   --git-common-dir` may reveal paths under `~/.claude`. The fix is meant to
   remove the high-probability canonical cwd leaks that caused Round 2, while
   the transcript tripwire catches any remaining channel.

2. `swarm-do` is not the git top-level. The local repo lives at:

   - Git top-level: `~/.claude/plugins/marketplaces/mstefanko-plugins`
   - Project subdir: `swarm-do/`

   Therefore the safe worktree must be created for the parent repository, and
   writer phases must launch from `<safe-worktree>/swarm-do`.

3. The existing worktree helper is not sufficient as-is. It currently places
   worktrees under `.swarm-do/worktrees` inside the source checkout. For a source
   checkout under `~/.claude`, that still leaves the real path sensitive.

4. Prepared artifacts currently reference repo-visible ignored paths such as
   `swarm-do/data/runs/<run-id>/prepared.md` and
   `swarm-do/data/runs/<run-id>/work_units/...`. A fresh git worktree will not
   contain those files unless the launcher copies them or rehomes those paths.

5. Running writers in a separate checkout changes recovery semantics. Phase
   recovery must diff the safe worktree and either keep that safe worktree as the
   continuing run root or explicitly copy/merge approved changes back into the
   original checkout.

6. `PWD=<safe-symlink>` is a partial mitigation only. Shell builtins can honor
   it, but Python and git still expose canonical paths. R2-1+ should be treated
   as a tactical probe-backed unblocker, not as the durable fix.

## Recommendation

Go directly toward R2-3-via-worktree as the structural fix, with one narrow
probe gate before spending effort on R2-1+.

R2-1+ remains useful only if the live Claude P2 probe shows that the model uses
relative paths once `pwd` prints the safe symlink. Even if that probe passes, it
should ship only with an explicit escalation rule: any canonical-path leak
diagnostic moves the launcher to the real safe worktree path.

Do not implement the tool-result rewriting interposer now. It is heavier than
the current evidence justifies, depends on undocumented hook behavior if done in
hooks, and would require stream-frame manipulation if done in the launcher.
Instead, add a diagnostic tripwire first.

## Implementation-Readiness Decisions

These decisions resolve the gaps that would otherwise block swarm execution.

1. Failure kind: declare `canonical_path_leaked_in_tool_result` before wiring
   the tripwire into recovery.

   - `kind`: `canonical_path_leaked_in_tool_result`
   - `category`: `permission`
   - `retry_class`: `human_gate`
   - `operator_title`: `Canonical source path leaked to writer`
   - `operator_message`: `A prompt or tool result exposed a path under the
     sensitive source checkout. Do not retry the same workspace mode; rerun from
     the safe-worktree launcher path.`
   - `required_evidence`: `transcript_diagnostics`, `command_metadata`,
     `sensitive_path_excerpt`

   On failed/no-artifact attempts, this kind should override
   `writer_tool_denied_no_artifacts` when the transcript contains a precise
   canonical source root in inputs or tool results, or bare `/.claude/` in
   path/command tool inputs. On otherwise successful attempts, record the same
   signal as a warning until a separate policy says success should be blocked.

2. Worktree granularity: the Round 2 launcher fix uses one continuing
   run-scoped execution worktree. Existing `add_unit_worktree()` remains a
   per-unit helper and should not be reused for this first slice because it
   writes under the source repo. Candidate 6 later adds per-unit or per-phase
   isolation worktrees on top of the run execution root when parallel execution
   needs them.

3. Branch policy: do not use detached worktrees for the first slice. Create or
   reuse a named run execution branch:
   `swarm/<run-id>/execution`. The base commit is the prepared artifact's
   `git_base_sha`; fall back to `git rev-parse <git_base_ref>` only if
   `git_base_sha` is missing in older artifacts. If the worktree or branch
   already exists, validate that it belongs to the same run and base before
   reusing it. Do not reset an existing branch silently.

4. Cleanup policy: every run worktree gets a manifest at
   `<data-dir>/worktrees/<run-id>/manifest.json`. Completed and adopted
   worktrees may be removed by an explicit CLI command; failed, blocked,
   conflicted, or unadopted worktrees are preserved by default. Add a dry-run
   first UX:
   `bin/swarm worktrees cleanup-run <run-id> [--apply]`.
   The manifest records `run_id`, source roots, safe roots, branch, base sha,
   project subdir, copied artifacts, adoption state, created time, and last-used
   time.

5. Integration UX: add an explicit dry-run first adoption command:
   `bin/swarm worktrees adopt-run <run-id> [--apply]`. The dry run lists changed
   files, blocked paths, and destination paths in the original source checkout.
   First slice adoption is copyback of scope-approved changed files, not a git
   merge into the user's checkout. `--apply` performs only the audited copyback
   described by the dry run.

6. Execution workspace mode name: use `safe-worktree`. Keep existing modes
   `real`, `safe-symlink`, and `disabled` intact for compatibility.

7. Dirty source policy: define "relevant dirty source" as any tracked or
   untracked, non-ignored path under the project subdir reported by:
   `git status --porcelain=v1 --untracked-files=all -- <project-subdir>`.
   Ignore repo-visible run artifacts that are already copied through the
   artifact manifest. First slice behavior is fail-closed with
   `launcher_workspace_error`, listing the dirty paths and telling the operator
   to commit/stash or use a future explicit patch-overlay mode.

8. Environment contract: `_run_real_claude()` must merge `os.environ.copy()`,
   set `PWD` to the safe project root, set `OLDPWD` only when a previous safe
   value is known, and pass `env=...` to `subprocess.Popen`. The current code
   passes `cwd` but no `env`.

9. Resolver edge cases: first slice supports normal git worktrees and the
   current monorepo-subdir shape. It must fail closed with a clear
   `launcher_workspace_error` for unsupported submodules, unresolved git
   top-levels, worktree paths resolving under `~/.claude`, or sparse-checkout
   states it cannot faithfully reproduce. Empty `git rev-parse --show-prefix`
   is valid and means the project root is the git top-level. Path comparisons
   must use resolved paths and account for macOS `/var` versus `/private/var`
   aliases.

## Relationship To Auditable Worktree Choreography

This is the same architectural move as Candidate 6, scoped down to the launcher
hardening problem.

The durable-run candidate says to isolate execution in worktrees, preserve diffs,
scope-check changes, and integrate through an auditable path. The sensitive-path
fix supplies a concrete forcing function: the execution worktree must be outside
`~/.claude`, because that makes the safe path the real path.

The implementation should therefore be designed as the first slice of Auditable
Worktree Choreography, not as a one-off launcher workaround.

## Implementation Plan

### Phase 0: Probe And Cheap Wins

Run the live P2 probe before writing R2-1+ code:

1. Launch a tiny Claude writer from the safe symlink workspace with `PWD` set to
   the safe symlink.
2. Ask it to create a harmless file using only relative paths.
3. Inspect whether its first `Write` path is relative/safe or canonical.

Regardless of the probe result:

1. Scrub any README or prompt-visible text that includes the canonical
   `~/.claude/plugins/marketplaces/...` path.
2. Add the Round 2 transcript regression for
   `writer_tool_denied_no_artifacts`. Do not assume the live transcript is still
   present; if it is unavailable, synthesize a minimal redacted fixture with the
   observed `<tool_use_error>` shape and a `Write` tool use.
3. Add `canonical_path_leaked_in_tool_result` to `failure_taxonomy.py` with the
   category and retry policy declared above.
4. Add a post-run transcript diagnostic tripwire that reports
   `canonical_path_leaked_in_tool_result` when inputs or tool results contain
   precise canonical source roots, or when path/command tool inputs contain
   bare `/.claude/` (including Bash `command` strings).

The first tripwire can be post-run. True streaming fail-fast can follow later
when the launcher moves from `--output-format json` to `stream-json`.

### Phase 1: Safe Worktree Resolver

Add an execution-workspace resolver that can derive:

1. Source project root: existing `repo_root`, for example
   `.../mstefanko-plugins/swarm-do`.
2. Git top-level: `git rev-parse --show-toplevel`, for example
   `.../mstefanko-plugins`.
3. Project subdir inside the git top-level: `git rev-parse --show-prefix`, for
   example `swarm-do/`.
4. Safe worktree top-level under the swarmdaddy data dir, for example
   `~/.local/share/swarmdaddy/worktrees/<run-id>/repo`.
5. Safe project root:
   `~/.local/share/swarmdaddy/worktrees/<run-id>/repo/swarm-do`.

This resolver should reject a safe root that still resolves under `~/.claude`.
It should also record all resolved paths in `command.json` and attempt evidence,
while ensuring prompt-visible content uses only the safe project root.

The resolver should live alongside `execution_workspace.py` or in a new
`execution_worktree.py` module. It should not change `worktrees.add_unit_worktree`
for the first slice. That helper is per-unit and currently writes under the
source checkout.

### Phase 2: Materialize The Safe Checkout

Create the safe worktree from the parent git repository, not from the `swarm-do`
subdirectory.

Recommended first slice:

1. Create a run-scoped branch `swarm/<run-id>/execution` and worktree at
   `<data-dir>/worktrees/<run-id>/repo`.
2. Launch from `<data-dir>/worktrees/<run-id>/repo/swarm-do`.
3. Base the branch on `prepared_plan.git_base_sha`. Use
   `prepared_plan.git_base_ref` only as a fallback resolver for older artifacts.
4. Copy the required ignored run artifacts into the safe project root,
   preserving their relative paths.
5. Record copied artifact paths, source paths, and hashes in execution metadata.

Copying the current run artifacts is the lowest-risk first slice because it
preserves existing context-renderer contracts. Rehoming prepared artifact paths
to the external data dir can be a later cleanup.

The required repo-visible artifact copy set is:

1. `data/runs/<run-id>/prepared_plan.v1.json`
2. `data/runs/<run-id>/prepared.md`
3. `data/runs/<run-id>/inspect.v1.json`
4. Every descriptor path in `prepared_plan.work_unit_artifacts[*].path`, usually
   `data/runs/<run-id>/work_units/*.work_units.v2.json`
5. `data/runs/<run-id>/checkpoint.v1.json`, when present
6. `data/runs/<run-id>/phase_sessions.v1.json`, when phase sessions already
   exist
7. `data/runs/<run-id>/phase_recovery/worktree-baseline.json`, when present

Do not copy `phase_launches/`, `phase_results/`, or `phase_handoffs/` into the
safe project root as runtime state. Those live under the external data dir and
are already the writer's target paths. Copy them only if a specific compatibility
test proves a prompt/context renderer still reads the repo-visible mirror.

Dirty source-checkout policy must be explicit. A fresh worktree from `HEAD` will
not include uncommitted local changes. The launcher should either:

1. Block when the source checkout has relevant dirty files.
2. Or, in a later mode, apply an explicit, recorded patch overlay into the safe
   worktree.

For the first implementation, prefer blocking except for known generated
run-artifact paths. Silent omission of dirty source changes would create a
misleading execution environment.

### Phase 3: Launcher Wiring

Wire `claude-print` phase execution to use the safe project root as the process
cwd and prompt-visible repo root.

Required behavior:

1. `cwd` for the Claude process is `<safe-worktree>/swarm-do`.
2. `_run_real_claude()` passes `env=os.environ.copy()` merged with `PWD` set to
   `<safe-worktree>/swarm-do`. `OLDPWD` is set only when a previous safe value is
   known.
3. Prompt/context paths point at safe paths or relative paths.
4. `command.json` records:
   - Source git top-level.
   - Source project root.
   - Safe git worktree root.
   - Safe project root.
   - Project subdir.
   - Execution workspace mode: `safe-worktree`.
   - Copied ignored artifacts.
   - Run execution branch.
   - Run worktree manifest path.

After this phase, transcript probes should show:

1. `pwd` reports the safe project root.
2. `python3 -c 'import os; print(os.getcwd())'` reports the safe project root.
3. `git rev-parse --show-toplevel` reports the safe parent worktree.
4. Directory `Read` errors do not expose the canonical plugin path.

### Phase 4: Recovery And Diagnostics

Update phase recovery to treat the safe project root as the execution root for
that attempt.

Required behavior:

1. Diff and changed-file detection run inside the safe worktree.
2. Scope checks interpret changed files relative to the project subdir
   `swarm-do/`.
3. Attempt evidence includes the safe worktree branch, commit base, changed-file
   list, and transcript diagnostic result.
4. The canonical-path tripwire scans prompt/tool-result transcript content and
   emits `canonical_path_leaked_in_tool_result` when a sensitive path leaks on a
   failed/no-artifact attempt. On successful attempts it records a warning field
   instead of changing the success status.

This tripwire is diagnostic only. It should not rewrite tool output.

### Phase 5: Integration Semantics

Use one safe worktree as the continuing repo root for the whole phase-session
run. This resolves the per-run versus per-unit ambiguity for the Round 2 fix.
The existing per-unit worktree helpers are not part of this first slice.

Recommended first slice:

1. Keep subsequent phases in the same run-scoped safe worktree so phase N+1 sees
   changes from phase N.
2. Preserve the worktree on failure, conflict, or scope violation.
3. At the end of the run, expose `bin/swarm worktrees adopt-run <run-id>` as a
   dry-run integration report. It must list changed files, blocked paths,
   source/destination roots, and the command needed to apply.
4. Require `bin/swarm worktrees adopt-run <run-id> --apply` to copy the
   scope-approved changed files back to the source checkout.
5. Add `bin/swarm worktrees cleanup-run <run-id>` as a dry-run cleanup report.
   Require `--apply` to remove a completed/adopted worktree.
6. Do not check out integration branches in the user's original source checkout.

The broader Auditable Worktree Choreography follow-up should add a dedicated
integration worktree under the data dir. That avoids mutating the user's active
checkout while still allowing branch merges and conflict manifests.

### Phase 6: Candidate 6 Expansion

Once launcher hardening is stable, extend the same primitives into the full
Auditable Worktree Choreography capability:

1. Per-unit or per-phase isolated branches when parallel execution requires it.
   These branch from, or merge back into, the run execution branch rather than
   replacing it.
2. Data-dir-owned per-unit worktree roots. Do not use the current
   `.swarm-do/worktrees` location when the source checkout is sensitive.
3. Dedicated integration worktree under the data dir.
4. Scope-check manifests before merge.
5. Conflict evidence manifests with exact files, branches, and commands.
6. Operator-visible adoption commands.
7. Cleanup policies for completed, failed, and preserved worktrees.

## Test Plan

Add focused tests before or alongside the implementation:

1. Taxonomy: `failure_taxonomy.py` knows
   `canonical_path_leaked_in_tool_result` with category `permission`,
   retry class `human_gate`, and the required evidence listed above.
2. Git mapping: a fixture where the project root is `parent/swarm-do` verifies
   correct git top-level, prefix, safe worktree root, safe project root, and
   mode `safe-worktree`.
3. Top-level project mapping: an empty `git rev-parse --show-prefix` fixture
   verifies that repos without a subdir use the safe git worktree as the safe
   project root.
4. Sensitive source path: a fixture under a fake `.claude/plugins/...` path
   verifies that the safe worktree resolves outside `.claude`.
5. Unsupported edge cases: submodule and sparse-checkout fixtures fail closed
   with `launcher_workspace_error` until explicitly supported.
6. Branch commitment: worktree creation uses `prepared_plan.git_base_sha`, names
   `swarm/<run-id>/execution`, and refuses to reset an existing mismatched
   branch or worktree.
7. Ignored artifacts: a fixture with ignored `data/runs/<run-id>/...` verifies
   that exactly the required copy set lands in the safe project root.
8. Launcher metadata and env: `command.json` records source and safe roots, the
   run execution branch, manifest path, and copied artifacts. The Popen test
   asserts both `cwd=<safe-project-root>` and `env["PWD"]=<safe-project-root>`.
9. Prompt safety: prompt-visible content does not contain the canonical source
   project root or source git top-level.
10. Transcript tripwire: the Round 2 or synthetic redacted transcript emits
    `writer_tool_denied_no_artifacts`; adding a precise source-root
    tool-result excerpt or a bare `/.claude/` path/command input emits
    `canonical_path_leaked_in_tool_result`.
11. Diff recovery: edits made inside `<safe-worktree>/swarm-do` are detected
    relative to the project subdir and written to attempt evidence.
12. Dirty source policy: relevant dirty tracked and untracked non-ignored files
    under the project subdir block with a clear operator error listing paths.
13. Concurrent runs: two run ids create distinct worktree roots and branches
    without path or branch collisions.
14. Adoption UX: `bin/swarm worktrees adopt-run <run-id>` dry-run lists changed
    files, blocked paths, source/destination roots, copyback operations, and the
    `--apply` command.
15. Cleanup UX: `bin/swarm worktrees cleanup-run <run-id>` dry-run preserves
    failed/unadopted worktrees and removes only completed/adopted worktrees when
    `--apply` is used.

Gate and DoD coverage:

1. Gates 1-3 are covered by taxonomy and transcript tripwire tests.
2. Gate 4 is covered by ignored-artifact copy tests.
3. Gate 5 is covered by diff recovery tests.
4. DoD 1-2 are covered by git mapping, sensitive source path, launcher env, and
   prompt safety tests.
5. DoD 3 is covered by ignored-artifact copy tests.
6. DoD 4 is covered by diff recovery and attempt evidence tests.
7. DoD 5 is covered by taxonomy and transcript tripwire tests.
8. DoD 6 is covered by continuing-root tests.
9. DoD 7 is covered by adoption UX tests.
10. DoD 8 is covered by cleanup UX tests.

## Decision Gates

1. If P2 fails, skip R2-1+ and implement the safe worktree path directly.
2. If P2 passes, R2-1+ may ship as a short-lived unblocker only with the
   canonical-path tripwire enabled.
3. Any `canonical_path_leaked_*` diagnostic escalates to the safe worktree
   launcher path when the run is still using R2-1+. If it appears under
   `safe-worktree`, block with evidence and investigate the leak channel.
4. Any implementation that cannot preserve ignored run artifacts in the safe
   checkout is not ready for writer reruns.
5. Any implementation that leaves recovery diffing the original source checkout
   is not ready for multi-phase durable runs.
6. Any implementation without an explicit `adopt-run` dry run and cleanup dry
   run is not ready for operator use.
7. Any implementation that silently ignores relevant dirty source files is not
   ready for swarm execution.

## Definition Of Done

The Round 2 fix is complete when:

1. A writer phase launches from a real safe checkout outside `~/.claude`.
2. Shell, Python, git, and tool error paths observed by the writer report the
   safe checkout path.
3. Prepared run artifacts are available inside the safe project root.
4. Writer changes are detected from the safe worktree and recorded in attempt
   evidence.
5. A failed/no-artifact attempt with a canonical-path transcript leak produces
   `canonical_path_leaked_in_tool_result` with category `permission` and retry
   class `human_gate`.
6. Later phases continue from the same run-scoped safe worktree.
7. `bin/swarm worktrees adopt-run <run-id>` dry-runs the integration with changed
   files, blocked paths, source/destination roots, copyback operations, and the
   apply command.
8. `bin/swarm worktrees cleanup-run <run-id>` dry-runs cleanup and preserves
   failed, blocked, conflicted, or unadopted worktrees by default.
