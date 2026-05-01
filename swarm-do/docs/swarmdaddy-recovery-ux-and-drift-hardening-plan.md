# SwarmDaddy Recovery UX & Drift-Hardening Plan

**Owner:** TBD
**Status:** Revised — pre-beads, post-analysis
**Created:** 2026-05-01
**Last revised:** 2026-05-01 (analysis pass corrections applied — see addendum below)
**Trigger run:** `01KQF2CF61YV7SYVREEWRE4GFB` (Phase 2 redo + post-Phase-2 dispatch failure)

---

## 0. Analysis pass addendum (2026-05-01)

Three parallel agents reviewed this plan against the source code and against industry patterns. Their reports:

- [`swarmdaddy-recovery-ux-and-drift-hardening-analysis.md`](./swarmdaddy-recovery-ux-and-drift-hardening-analysis.md) — work-breakdown / acceptance criteria / gap surfacing.
- [`architecture-assessment-2026-05-01.md`](./architecture-assessment-2026-05-01.md) — code walk + refactor verdict (file:line evidence).
- [`research-similar-systems-2026-05-01.md`](./research-similar-systems-2026-05-01.md) — industry patterns (Temporal / Dagster / Bazel / Nix / dbt / jj) + Python library picks.

### 0.1 Headline corrections (applied in revised body below)

1. **§3.4.1 row 2 was factually wrong — struck.** Both deep agents independently confirmed `prepared_plan_sha` hashes `prepared.md` (the markdown derivative, `prepare.py:668, 676`), **not** `prepared_plan.v1.json`. Mutating `git_base_sha` in the JSON envelope cannot drift `prepared_plan_sha`. The "compute twice / exclude-self-field deterministic round-trip" anxiety in the original draft was solving a non-problem. Bug 3 in §10 collapses into Bug 2.
2. **Co-ship a `PreparedArtifactWriter` seam (~200 LoC, ~1 week)** — see §3.4 Layer A revision. Without a single owner of the *embedded ↔ sidecar bytes ↔ descriptor.sha* triple, the next operator writes `refresh-git-base-v2.py`. This is the rotten-beam fix the architecture assessment names as the highest-leverage in-scope refactor.
3. **§8.9 (upstream `git_base_sha` writer guard) promoted from backlog to P0** — without one writer + fence test, the dispatch primitive can be re-bypassed. Now part of Bug 2's PR.
4. **§8.6 / §8.7 / §8.8 promoted from Hardening into Recovery-UX** — pre-pump preflight, audit-trail events, and `_reset_phase_to_pending` field-coverage audit are tightly coupled to recovery commands. Without §8.8 in the Recovery-UX epic, `phases reset --hard` ships with the same field gap that made `/tmp/reset-phase2.py` necessary.
5. **§3a is a hard dependency on Bug 2's PR, not parallel cleanup.** Replacement-before-delete + fixture-capture-before-delete are gating. The §10 paired-task wording elided fixture-capture; now explicit.
6. **`phases doctor` needs probe-error isolation as an explicit acceptance criterion** — once §8.6's pre-pump preflight calls `doctor` implicitly, a panic in any one of the four probes panics the pump. Each probe must return a `probe_error` finding, never raise. Added to §6.
7. **Multi-file atomicity contract documented for implementers** — POSIX `rename` is per-file. The correct recipe across `prepared_plan.v1.json` + N sidecars + `phase_sessions.v1.json` (+ possibly `inspect/*.json`) is: snapshot-to-`.bak` → write-to-`.tmp` → sequential `os.replace` → restore-on-fail. Documented in §3.4.

### 0.2 Verdict on the strategic question

**Foundation, not duct-tape — with one rotten beam.** The six-file state shape, two-root XDG/repo split, and JSON-Schema-validated event log are defensible for a single-operator local CLI. The rot is one missing seam — coupled-invariant ownership for embedded artifact ↔ sidecar ↔ descriptor.sha — and the §3.4 `PreparedArtifactWriter` retires it in ~1 week. Total scope of this plan as revised: ~3 weeks across `prepare.py`, `execution_worktree.py`, plus new `prepared_artifact_writer.py` and `phase_doctor.py`. `phase_pump.py` is not refactored.

### 0.3 Open architectural question — see §12

The two architectural agents disagreed on the bigger storage question (SQLite + pydantic vs. status quo JSON-files-with-validators). That decision is **out of scope for this plan** but tracked as a follow-on research epic in §12. We are not deferring this plan to wait on it.

---

## 1. Executive summary

Two distinct failures hit the same run inside a single hour, and both required out-of-band manual surgery (worktree teardown, manifest deletion, branch deletion, JSON edits, custom Python scripts, manual pump) to recover. Both bugs share the same anti-pattern: a strict validator hard-aborts on legitimate-but-uncoordinated state drift, with no programmatic recovery path. The plan addresses:

1. **The two bugs** — surgical code fixes, plus targeted regression tests.
2. **The missing user surface** — a small set of new `swarm` CLI subcommands and Claude-plugin slash commands so users never need to drop into `git worktree remove --force`, `rm manifest.json`, ad-hoc Python scripts, or `sed` again.
3. **The shared anti-pattern** — a classification policy (auto-recover vs. interactive choice vs. hard-abort) and a hardening backlog covering every other site that fails closed when a structured recovery would be safe.

The aim: when something legitimate-but-disruptive happens (user edits source between phases, base ref bumped, lease expires), the harness recognizes it and either fixes it silently with an audit event, or surfaces a single yes/no question to the user. Manual JSON editing should never be the right answer.

---

## 2. Bug 1 — Worktree base-SHA drift aborts dispatch

### 2.1 Symptom
Phase pump fails with:
```
existing run worktree manifest does not match this run/base: base_sha
```
…surfaced as `launcher_workspace_error` in `phase_pump.py`.

### 2.2 Root cause
`materialize_run_execution_worktree()` at `swarm-do/py/swarm_do/pipeline/execution_worktree.py:169` reads the per-run manifest at `~/.local/share/swarmdaddy/worktrees/<run-id>/manifest.json`. If a manifest exists, `_validate_existing_manifest` (line 859) does a hard equality compare across `run_id`, `source_*`, `safe_*`, `project_subdir`, `branch`, and `base_sha`, and raises `RunExecutionWorktreeError` for any mismatch. The validator conflates two semantically different conditions:

| Field class | Mismatch meaning | Right action |
|---|---|---|
| Identity (`run_id`, `source_*`, `safe_*`, `project_subdir`) | Real corruption / misuse | Hard abort |
| Base/branch (`base_sha`, `branch`) | Source repo edited or replanned since last run | Rebuild worktree |

`_create_run_worktree` (line 782) shares the same shape — aborts if the execution branch already exists, regardless of whether discarding it is safe.

### 2.3 Fix
Replace the single validator with a classifier that returns one of:

- `MATCH` → reuse, fall through.
- `IDENTITY_MISMATCH` → preserve current behavior, hard abort.
- `BASE_DRIFT_SAFE` → no commits ahead of recorded `base_sha` on the execution branch **and** worktree clean **and** `adoption_state == "unadopted"` → auto-rebuild: `git worktree remove --force`, `git branch -D <execution-branch>`, delete manifest, then call `_create_run_worktree`. Append a `worktree_rebuilt` event to the run event log.
- `BASE_DRIFT_UNSAFE` → execution branch has commits ahead of recorded base, or working tree dirty, or already adopted → raise a typed `RunExecutionWorktreeRebuildRequired` carrying the diagnosis. The pump translates this into a `needs_input` phase status with the same payload, so the slash-command UX can surface "discard / archive / abort."

The load-bearing safety check is `git rev-list <recorded base_sha>..<execution branch>` — a non-empty result means there is unadopted work and we must not silently rebuild.

### 2.4 Tests (regression contract)
Add to `swarm-do/py/swarm_do/pipeline/tests/test_execution_worktree.py`:

1. `materialize_run_execution_worktree` called twice with different `git_base_sha` and a clean execution branch → second call rebuilds, returns the new safe checkout, emits `worktree_rebuilt` event.
2. Same setup but with a writer commit on the execution branch → second call raises `RunExecutionWorktreeRebuildRequired` with `unadopted_commits=[<sha>]`.
3. Identity mismatch (`run_id` differs) → still `RunExecutionWorktreeError` (hard abort preserved).

---

## 3. Bug 2 — Embedded prepared-dispatch artifact drift (out-of-band base bump)

### 3.1 Symptom
After Phase 2, the dispatch fails with:
```
swarm: do --prepared: prepared dispatch:
  work_unit_artifacts[0].artifact does not match sidecar
```
…on every phase, on every retry.

### 3.2 Root cause (confirmed — script identified)

The `prepared_plan.v1.json.bak-before-git-base-refresh` backup was produced by **`/tmp/refresh-git-base.py`** — a one-off helper script created during the 2026-04-30 sensitive-path-write-block investigation (see `swarm-do/docs/investigations/2026-04-30-sensitive-path-write-block.md` §"Helper artifacts created during the investigation", line 456, plus the §"Round 2 re-pump evidence" callout at line 307).

The script's logic (verbatim from `/tmp/refresh-git-base.py`):

```python
def replace_git_base(node, new_sha):
    count = 0
    if isinstance(node, dict):
        for k, v in list(node.items()):
            if k == "git_base_sha" and isinstance(v, str):
                if v != new_sha:
                    node[k] = new_sha
                    count += 1
            else:
                count += replace_git_base(v, new_sha)
    elif isinstance(node, list):
        for item in node:
            count += replace_git_base(item, new_sha)
    return count
```

A recursive walk of the prepared plan that updates **every** occurrence of `git_base_sha`. That means it bumps both:

- The top-level `git_base_sha` in `prepared_plan.v1.json` (`c9a3d96 → 870f821`).
- Every embedded `work_unit_artifacts.<phase>.artifact.git_base_sha` field.

…but it does **not** rewrite the on-disk sidecar files at `data/runs/<run-id>/work_units/*.json`, and does **not** update the per-descriptor `sha` field. The script's docstring (*"Use this when the prepared artifact is stale because code commits landed after the run was prepared but the plan content itself is still valid for re-dispatch"*) describes the intended use case correctly; the implementation just missed half the coupled state.

**Consequence:** every future operator who reaches for the same script will reproduce the trap. The script lives in `/tmp` so it's session-local on this machine, but the *pattern* — one-off Python helpers created mid-debug to unblock stuck runs — is the real failure mode. The investigation note enumerates four such helpers (`/tmp/refresh-git-base.py`, `/tmp/reset-phase2.py`, `/tmp/swarm-perm-probe.sh`, `/tmp/swarm-perm-probe2.sh`); none of them have a sanctioned `swarm` equivalent yet.

In `swarm-do/py/swarm_do/pipeline/prepare.py:1283`:
```python
embedded = descriptor.get("artifact")
if embedded is not None and embedded != artifact:
    raise ValueError("prepared dispatch: work_unit_artifacts[N].artifact does not match sidecar")
```
`_verify_hashed_sidecar` (line 1303) computes the actual SHA and compares to `descriptor["sha"]` — both hash the unchanged file content, so the SHA gate passes. `_read_json_object` then parses the file fresh, and the structural compare against the freshly-edited `embedded` blows up by exactly one field (`git_base_sha`).

### 3.3 Important design correction
A prior draft of this plan recommended dropping the embedded equality check on the theory that the SHA gate is sufficient. That is **wrong**. The SHA gate hashes the file; the embedded check is the only gate that catches the case where someone (or some script) edits the embedded copy in place without touching the on-disk sidecar. Removing it would silently allow the dispatch to proceed with a writer that reads the unchanged sidecar from disk — defeating the integrity contract. **Keep the embedded check. The fix is upstream.**

### 3.4 Fix — three layers

**Layer A (immediate, local, surgical):** introduce a `PreparedArtifactWriter` seam (~200 LoC, new module `swarm-do/py/swarm_do/pipeline/prepared_artifact_writer.py`) that owns the *embedded artifact JSON ↔ sidecar file bytes ↔ descriptor.sha* triple. Then add a sanctioned primitive that supersedes `/tmp/refresh-git-base.py` as a thin caller of the writer:

```
swarm prepare refresh-base <run-id> [--to-head|--to-sha SHA] [--phase N] [--dry-run]
```

`PreparedArtifactWriter` is the single seam any code mutating `git_base_sha` (or any other field shared between the embedded artifact and its sidecar) must go through — see §8.9 fence test. `prepare_plan_run` migrates onto it as part of this PR so there is exactly one writer of this triple in the codebase.

The command must do — atomically and in this order — what `/tmp/refresh-git-base.py` did, **plus** the sidecar/sha steps the script omitted. For each affected phase:

1. Resolve the target SHA (default `HEAD` of the source repo).
2. Update the top-level `prepared_plan.v1.json["git_base_sha"]` and every embedded `work_unit_artifacts.<phase>.artifact.git_base_sha`. (This is what the /tmp script already did.)
3. **For each descriptor** in `work_unit_artifacts` (via `PreparedArtifactWriter`):
   1. Write the (now-updated) embedded `artifact` JSON back to the sidecar file at `descriptor["path"]` using the canonical writer format (`indent=2`, `sort_keys=True`, trailing newline — must match `prepare.py`'s emit so SHAs are reproducible).
   2. Recompute `_sha256_file(path)` and update `descriptor["sha"]`.
4. Atomic write of `prepared_plan.v1.json`. Backup to `prepared_plan.v1.json.bak-before-refresh-base-<utc-iso>`.
5. Append a `prepared_dispatch_refreshed` event per phase to the run event log, with `phase_id`, before/after `git_base_sha`, before/after sidecar `sha`, trigger reason (`--to-head` / explicit SHA), and operator id.
6. Verify: re-run the dispatch validator (`_verify_dispatch_sidecars`) read-only as a post-condition before exiting non-zero on failure. The command must not return success while leaving the run un-dispatchable.

**Crucial:** the unit of atomicity is the *whole run*, not per-phase. If step 3 fails partway, restore from the backup and exit non-zero. A half-applied refresh is exactly the bug we're trying to retire.

#### 3.4.0 Multi-file atomicity recipe (implementer guidance)

POSIX `rename`/`os.replace` is atomic per file, not across files. The atomic-across-N-files contract that §3.4 promises must be implemented with explicit rollback because no filesystem primitive provides it. Do **not** reach for SQLite or filesystem snapshots for this — the recipe below is the right shape for the existing storage model:

1. **Snapshot phase.** For every file the operation will touch, copy `path` → `path.bak-<op>-<utc-iso>` via `shutil.copy2`. If any snapshot fails, abort before mutating anything.
2. **Stage phase.** Compute every new file body in memory. Write each to `path.tmp-<op>` (same directory, same filesystem so `os.replace` stays atomic). Compute SHAs against the staged bytes, not the eventual on-disk bytes (these match by construction, but the discipline matters).
3. **Commit phase.** Sequentially `os.replace(path.tmp-<op>, path)` across all files. Order matters only for crash-recovery readers; from a same-process failure standpoint a partial commit triggers rollback.
4. **Verify phase.** Re-run the same validators a fresh process would run (`_verify_dispatch_sidecars`, `check_stale`). On any failure, jump to rollback.
5. **Rollback phase.** Reverse the commit by `os.replace(path.bak-..., path)` for every file the op staged. Snapshots that were never committed-over are deleted.
6. **Cleanup phase.** On success, leave `.bak-...` files in place (operator audit trail, GC by separate tooling). Tmp files are removed.

This is a hand-rolled write-ahead log. It is the single largest piece of failure-mode code in `PreparedArtifactWriter` and deserves explicit unit tests for *every* phase failing. See §3.5 Test 4.

#### 3.4.1 The four `check_stale` surfaces (must all pass after refresh)

`check_stale()` (`swarm-do/py/swarm_do/pipeline/prepare.py:2012`) is what raises `prepared artifact is stale: ...` from both `do --prepared` (line 1166) and `prepare accept` (line 1918). It evaluates four independent drift sources in one pass; any one failing rejects the run. **`prepare refresh-base` must leave all four green** or it has not finished its job:

| Drift key | What it compares | What `prepare refresh-base` must do |
|---|---|---|
| `source_plan_sha` | `_sha256_file(<source plan>)` vs `artifact["source_plan_sha"]` | If the source plan file's content changed since prepare, that is a *plan content* change — not safe to auto-resolve. Surface as `needs_input` ("source plan edited; re-prepare or restore the plan"). Refresh-base alone must NOT touch this. |
| ~~`prepared_plan_sha`~~ | `_sha256_file(<prepared.md>)` vs `artifact["prepared_plan_sha"]` | **STRUCK AFTER ANALYSIS.** The original draft incorrectly described `prepared_plan_sha` as the self-recorded hash of `prepared_plan.v1.json`. It is not. `prepared_plan_sha` hashes the markdown derivative `prepared.md` (`prepare.py:668, 676`). Mutating `git_base_sha` in the JSON envelope mathematically cannot drift `prepared_plan_sha`. There is no self-referencing-hash problem to solve; the "compute twice / exclude-self-field" deterministic round-trip the draft worried about is not a real concern. `refresh-base` does not touch this field. If `prepared_plan_sha` ever does drift, the cause is `prepared.md` having been re-emitted, which is a Tier-B `needs_input` (re-prepare), the same path as `source_plan_sha` drift. |
| `git_base_sha` | `git rev-parse <git_base_ref>` vs `artifact["git_base_sha"]` | Bump the field to current HEAD (or the explicit `--to-sha`). Already what `/tmp/refresh-git-base.py` does — keep this behavior. |
| `phase:<id>` (per-phase cache_key) | Derived from `content_sha + prepared_plan_sha + plan_context_sha` | If `prepared_plan_sha` is unchanged (refresh-base does not affect it) and the source plan didn't change, the per-phase cache keys remain consistent automatically. If source plan or markdown changed, per-phase keys will fail too — same `needs_input` path. |

**Why this matters for the recurring trap.** Every commit on the source branch advances HEAD past `artifact["git_base_sha"]`, so any user who commits code during a multi-phase run will hit `git_base_sha` drift at the next phase dispatch. The /tmp/refresh-git-base.py "fixes" this once but does so without coordinating sidecars and `descriptor.sha` (Bug 2's surface), leaving the dispatch validator failing. The atomic primitive must close the cycle: after `prepare refresh-base` exits 0, a `check_stale` call against the current source state must return `None`. That is the post-condition contract.

#### 3.4.2 Other places `git_base_sha` lives (must be coherent post-refresh)

Beyond the four `check_stale` surfaces, `git_base_sha` (and adjacent base state) appears in several other persisted locations. The atomic primitive should either rewrite each, or document that the location is intentionally not maintained by refresh-base and explain why:

- `prepared_plan.v1.json` top-level `git_base_sha` — rewrite (already in scope).
- `prepared_plan.v1.json` `work_unit_artifacts.<phase>.artifact.git_base_sha` (every embedded copy) — rewrite (already in scope).
- `data/runs/<run-id>/work_units/*.json` sidecar files — rewrite the embedded artifact and recompute `descriptor.sha` (already in scope per §3.4 Layer A).
- `data/runs/<run-id>/inspect/*.json` (inspect_artifact sidecar referenced at `prepare.py:818, 1256, 1594`) — if its body holds `git_base_sha`, rewrite + update `inspect_artifact.sha` in `prepared_plan.v1.json`. **Verify in implementation.**
- `~/.local/share/swarmdaddy/runs/<run-id>/phase_sessions.v1.json` field `prepared_plan_sha` (`phase_sessions.py:240, 1252-1253`) — **no rewrite needed for `refresh-base`** because `prepared_plan_sha` hashes `prepared.md` (markdown), not the JSON envelope. `refresh-base` does not change the markdown. This field stays valid post-refresh. **Verify in implementation:** unit test asserts `phase_sessions.v1.json["prepared_plan_sha"]` is unchanged after a `refresh-base` run, and the next pump does not reject with `phase-session prepared_plan_sha does not match accepted prepared artifact`. If the test fails, the original draft was right and we missed something — investigate before shipping.
- `~/.local/share/swarmdaddy/worktrees/<run-id>/manifest.json` field `base_sha` (`execution_worktree.py:81`) — coordinate with the worktree-rebuild policy from §2. If the manifest's base differs from the new prepared base, the worktree rebuild path (Bug 1's fix) takes over from there.

`refresh-base` and the worktree-rebuild path (§2) must not fight each other: refresh-base updates the prepared artifact and `phase_sessions.v1.json`'s recorded prepared_plan_sha; the next pump observes worktree base drift and triggers the §2 auto-rebuild flow. Each owns its scope; the seam is the worktree manifest's `base_sha`.

This makes the operation idempotent, keeps both validators (sha + embedded) intact, and — critically — gives operators a single command that *can't* leave the run in the half-rewritten state the /tmp script can.

**Layer B (defensive, upstream):** any sanctioned "rewrite the prepared plan's git_base_sha" operation must call into the same atomic primitive — never write the embedded JSON without coordinating sidecars and SHAs. Audit `prepare.py`, `phase_sessions.py`, and any rebase/refresh helpers; ensure no caller bumps `git_base_sha` in `prepared_plan.v1.json` without going through the primitive.

**Layer C (diagnostic):** improve the validator's error message to enumerate the differing keys, e.g.:
```
prepared dispatch: work_unit_artifacts[2].artifact does not match sidecar
  differing keys: ['git_base_sha']
  embedded.git_base_sha = '870f821...'
  sidecar.git_base_sha = '54a90c2...'
  hint: run `swarm prepare refresh-base <run-id> --phase 2` to resync
```
A diagnostic message that names the broken state and the fix command lets the user (or an upstream agent) self-recover without spelunking.

### 3.5 Tests
1. `prepare refresh-base` with a half-rewritten artifact (matching `/tmp/refresh-git-base.py`'s output state) → file content updated, descriptor `sha` updated, dispatch validation passes on next call.
2. Same primitive run twice (idempotent) → no-op on second call.
3. Out-of-band half-rewrite → `--prepared` dispatch fails with the new diagnostic message including the differing keys and hint.
4. **Atomicity test:** simulate a write failure at each step of the §3.4.0 recipe (snapshot, stage, commit, verify) and assert the run is restored from backup with all files at their pre-op bytes. No half-applied refresh allowed in any failure mode. Parametrize over the failure point.
5. **Inverse-of-script regression test:** capture the actual artifact state produced by `/tmp/refresh-git-base.py` as a fixture, and assert `prepare refresh-base` makes the validator green without further intervention. This is the contract that guarantees the production failure won't recur. Capture this fixture **before** the script is deleted (§3a hard dependency).
6. **Recurring-cycle test:** run `prepare refresh-base`, advance HEAD by one commit, run `prepare refresh-base` again, then call `check_stale()` — expect `None`. The cycle must be idempotent across multiple HEAD-advances.
7. **`check_stale` post-condition test:** after `prepare refresh-base` returns 0, an in-process call to `check_stale(payload, repo_root=root)` must return `None` for `git_base_sha` and `phase:<id>`. (`source_plan_sha` and `prepared_plan_sha` are not touched by refresh-base; if they're stale the operator needs `re-prepare`, not `refresh-base`.)
8. **`/tmp/refresh-git-base.py` post-condition (negative test):** running the legacy script must NOT make `check_stale` return `None` (it produces sidecar/embedded drift). This locks in why the script is being retired.
9. **`prepared_plan_sha` invariance test (sanity check on the §3.4.1 row 2 strike):** assert `prepared_plan_sha` in `prepared_plan.v1.json` and in `phase_sessions.v1.json` are byte-identical before and after `prepare refresh-base`. If this test ever fails, the original draft's row-2 concern was real and the strike must be reverted — investigate the markdown emit pipeline.
10. **`PreparedArtifactWriter` exclusivity test:** import-level grep / AST scan asserts no module other than `prepared_artifact_writer.py` writes to `git_base_sha` keys in `prepared_plan.v1.json` or in any sidecar under `data/runs/`. This is the §8.9 fence test, promoted to P0 and now part of Bug 2's PR.

---

## 3a. /tmp helper-script retirement

The 2026-04-30 investigation produced four ad-hoc helpers, all still on disk:

| Script | Purpose | Sanctioned replacement (this plan) | Has-correctness-bug? |
|---|---|---|---|
| `/tmp/refresh-git-base.py` | Bump `git_base_sha` to current HEAD across the prepared plan | `swarm prepare refresh-base` (§3.4 Layer A) | **Yes — confirmed source of Bug 2 AND a second latent bug.** (a) Skips sidecar files + descriptor SHAs (the embedded-vs-sidecar drift). (b) Changes `prepared_plan.v1.json` bytes without updating its self-recorded `prepared_plan_sha`, so the next `check_stale` flips to "prepared artifact is stale: prepared_plan_sha". The script "fixes" `git_base_sha` once but breaks `prepared_plan_sha` simultaneously — operators are perpetually one staleness flavour away from blocked, which is the recurring trap. |
| `/tmp/reset-phase2.py` | Reset Phase 2 to dispatchable state (clears 30+ fields) | `swarm phases reset --phase N --hard` (§6) | Field set diverges from in-process `_reset_phase_to_pending` (`phase_sessions.py:1331`); see §8.8 |
| `/tmp/swarm-perm-probe.sh` | Probe sensitive-path guard with `bypassPermissions` | (probe-only; not a recovery action) — keep as a doc reference if useful, no replacement needed | n/a |
| `/tmp/swarm-perm-probe2.sh` | Probe sensitive-path guard variants A/B/C | (probe-only) | n/a |

**Why this matters beyond Bug 2.** Every one-off helper script created during a debug session is a footgun for the next operator who finds it. The /tmp scripts have no schema versioning, no audit trail, no idempotency guarantee, and no test coverage. They run as root-equivalent processes with full filesystem access against `~/.local/share/swarmdaddy/runs/`. The next time a similar issue appears, the discovery path is "find the old /tmp script and run it" — and inherit any latent bugs it has.

**Required actions (all gating on Bug 2's PR — not parallel cleanup):**

1. **Capture fixture before delete.** Run `/tmp/refresh-git-base.py` against a fresh prepared run, capture the resulting (broken) artifact bytes as a regression fixture under `swarm-do/py/swarm_do/pipeline/tests/fixtures/refresh_base_legacy_output/`. This fixture anchors §3.5 Test 5 (inverse-of-script regression) and §3.5 Test 8 (negative test). **Without this fixture captured, the scripts cannot be deleted.**
2. **Replace before delete.** Ship `swarm prepare refresh-base` (§3.4) and `swarm phases reset --hard` (§6) before removing the /tmp scripts. The replacements must cover the same use cases or the operator will recreate the script.
3. **Delete the broken scripts.** Once replacements ship and fixtures are captured, remove `/tmp/refresh-git-base.py` and `/tmp/reset-phase2.py` from disk and update the investigation note (`swarm-do/docs/investigations/2026-04-30-sensitive-path-write-block.md` lines 451–457) to point at the sanctioned commands.
4. **Document the policy.** Add a contributor-guide line: *"Recovery operations on `~/.local/share/swarmdaddy/` state must ship as `swarm` subcommands. Do not commit one-off /tmp helper scripts; do not link to /tmp scripts in investigation notes as the recommended fix."* New /tmp helpers are acceptable for *probes* (read-only) but never as the canonical fix path.
5. **Audit existing references.** `grep -rn '/tmp/.*\.py' swarm-do/docs/ swarm-do/role-specs/ swarm-do/agents/` and replace any remaining pointers to /tmp helpers with the sanctioned `swarm` command.

This is part of Bug 2's remediation, not orthogonal to it. Without §3a the underlying habit recurs. Sequence is **fixture-capture → replacement-ship → delete-scripts → audit-references** — same PR, same author, same review.

---

## 4. Shared anti-pattern: fail-closed-on-legitimate-drift

Both bugs are instances of: *strict validator catches legitimate-but-uncoordinated state drift, hard-aborts with no recovery path*. Other sites with the same shape (see §8). The classification policy applied uniformly:

- **Tier A — auto-recover.** Identity intact, drift is benign and reversible (no committed work at risk). Recover silently, append an audit event. Examples: worktree base drift on a clean unadopted branch; sidecar resync after a sanctioned base bump.
- **Tier B — interactive.** Drift could destroy unadopted work. Surface as `needs_input` with a small set of named options. The slash-command UX renders the question to the user.
- **Tier C — hard-abort.** Identity mismatch or invariants violated (run_id collision, file outside run dir). No safe recovery. Keep current behavior.

Every validator in the run-orchestration layer should be reviewed against this taxonomy. Today most are Tier C by default; they should be Tier A/B where the underlying state is auto-recoverable.

---

## 5. Immediate remediation for run `01KQF2CF61YV7SYVREEWRE4GFB`

Apply the agent's recommendation manually for now (until §3.4 Layer A ships):

1. Back up `prepared_plan.v1.json` → `prepared_plan.v1.json.bak-before-sidecar-resync`.
2. For each of the 7 phases, write the embedded `descriptor.artifact` back to `descriptor.path` using `indent=2`, `sort_keys=True`, trailing newline.
3. Recompute SHA-256 of each rewritten sidecar; update `work_unit_artifacts.<pid>.sha` in `prepared_plan.v1.json`.
4. Re-run `swarm-do/bin/swarm phases pump 01KQF2CF61YV7SYVREEWRE4GFB --launcher=claude-print --max-phases 1`.

This is the surgical "make the file match the field that was already updated" operation. Once §3.4 ships, the same operation is one CLI call.

---

## 6. CLI surface additions

All additive, no breaking changes. Each command exits non-zero on failure and emits structured JSON with `--json`.

```
swarm phases doctor   <run-id>
    Read-only diagnosis. Probes:
      - phase status (pending / in_progress / failed / blocked / retry_*)
      - lease (expired? owner alive?)
      - worktree state (manifest base vs. current source base, branch ahead/behind, dirty)
      - prepared dispatch (sidecar/embedded coherence per phase, sha gate)
      - artifact contract violations
    Emits a ranked list of findings, each with a single recommended `swarm` command to apply.
    JSON output is the contract for slash commands and TUI.

    **Acceptance criterion — probe error isolation (added per analysis):** each
    probe runs in its own try/except harness and reports failures as a
    `probe_error` finding rather than raising. Once §8.6's pre-pump preflight
    calls `doctor` implicitly, an exception in any one probe would otherwise
    panic the pump — exactly the failure shape this plan exists to retire.
    A panicking probe is itself a `phases doctor` finding. Test:
    inject a probe that raises and assert the other probes still emit findings
    and the command exits with structured `probe_error` JSON, not a traceback.

swarm phases reset    <run-id> --phase N [--hard]
    In-process call to _reset_phase_to_pending(); --hard also clears attempt_history,
    last_failure_kind, last_error, started_at, prompt_sha, result_path, handoff_path,
    and the rest of the field set documented in §8.8.
    Direct replacement for /tmp/reset-phase2.py — must cover the same fields the script
    cleared, or operators will fall back to the script.

swarm phases redo     <run-id> [--phase N] [--rebuild-worktree] [--launcher=claude-print]
    One-shot orchestration: doctor → optional worktree reset → phase reset → pump → status.
    Default behavior is conservative: refuses to rebuild worktree if execution branch has unadopted commits.

swarm worktrees reset <run-id> [--discard | --archive-branch] [--force]
    Atomic: git worktree remove --force, git branch -D (or rename to swarm/.../execution.archived-<ts>),
    delete manifest.json. --force required when execution branch has unadopted commits.

swarm worktrees status <run-id>
    Print: base_sha (manifest vs. source), execution branch ahead/behind manifest base,
    dirty file count, adoption_state, conflict-manifest path if any.

swarm prepare refresh-base <run-id> [--to-head|--to-sha SHA] [--phase N] [--dry-run]
    Atomic resync of embedded artifact ↔ sidecar file ↔ descriptor.sha across the whole run.
    Direct replacement for /tmp/refresh-git-base.py — must do the script's work AND the
    sidecar/sha rewrite the script omitted. Whole-run atomic; on partial failure restore
    from backup. See §3.4 Layer A.
```

The keystone is `phases doctor`. Every other command is plumbing it can recommend.

---

## 7. Slash-command UX layer (Claude plugin)

Add three commands under `swarm-do/commands/`. These are the user-facing surface; the CLI commands above are their plumbing.

### `/swarmdaddy:status [run-id]`
Wraps `phases doctor` + `phases status` + `worktrees status`. Prints a one-line summary plus a "next step" hint pointing at the exact command to run. Replaces the user's "running status manually feels weird" complaint by making it the default verb when a run is active.

Example output:
```
Run 01KQF2CF61YV7SYVREEWRE4GFB — 7 phases, 2 complete, 5 pending
  worktree:        DRIFT — manifest base 26d1f33, source HEAD c9a3d96, branch clean
  prepared:        ok
  next phase:      3 (pending, no lease)
  recommended:     /swarmdaddy:redo 3   (will rebuild worktree at HEAD, then pump)
```

### `/swarmdaddy:redo [phase]`
Calls `phases doctor`. For each finding with multiple safe options, prompts the user with `AskUserQuestion`:

> Phase 2 sidecars drifted from embedded artifacts (likely an out-of-band base bump).
> A) Resync sidecars to embedded (keep new base — intended outcome). [recommended]
> B) Restore embedded from sidecars (revert base bump).
> C) Abort and inspect.

…then executes the corresponding CLI command, captures the audit events, and reports back. This is the "single quick question, two named options" UX the user asked for.

### `/swarmdaddy:repump [phase]`
Single-keystroke wrapper for `phases pump --launcher=claude-print --max-phases=1` followed by `phases status`. The 90% path when the run is already healthy and just needs another tick.

Resume already exists at `commands/resume.md`; the doctor + redo + repump triad is the gap.

---

## 8. Hardening backlog (numbered, parallelizable)

Each item is one beads child issue under the umbrella epic.

**Items moved to Recovery-UX epic per the analysis pass:** §8.6 (pre-pump preflight), §8.7 (audit trail), §8.8 (`_reset_phase_to_pending` field coverage), and §8.9 (`prepare refresh-base` upstream guard / fence test). Each is tightly coupled to a recovery command and trivially small once that command exists. Promotion details:

- §8.6 → ships with `phases doctor` (doctor IS the preflight).
- §8.7 → ships with each recovery command that emits its own structured event (worktree-rebuild, phase-reset, prepared-dispatch-refresh).
- §8.8 → ships with `phases reset --hard` so the field coverage is locked in by the same PR. Without this, the new command ships with the same gap that birthed `/tmp/reset-phase2.py`.
- §8.9 → P0, ships with Bug 2's PR. The fence test (no module other than `PreparedArtifactWriter` writes `git_base_sha`) is what prevents the pattern from re-emerging. See §3.5 Test 10.

The remaining hardening backlog (lower priority, can ship after Recovery-UX):

1. **`_create_run_worktree:782-786`** — aborts on stale execution branch with no manifest. Apply Tier-A/B classification: branch clean & no commits ahead of base → discard; otherwise → `needs_input`.
2. **`_ensure_integration_worktree:622-634`** — aborts on dirty integration worktree. Offer `worktrees reset --integration`.
3. **Phase attempt counter vs. worktree rebuild** — when auto-rebuild fires for base drift, reset `attempt` to 0 and stamp `rebuild_reason: "base_drift"` on `attempt_history`. Otherwise the retry budget eats itself on a clean restart.
4. **Stale lease arbitration** — `phases reap`, `phases recover`, `phases cancel` all exist but are user-routed. `doctor` should pick automatically; `redo` should orchestrate.
5. **Manifest schema migration** — `_validate_existing_manifest` doesn't tolerate added/removed fields. Bump `schema_version` and add a migration path that rewrites the manifest from the current resolved state when the schema changes.
6. **Diagnostic error messages** — every `RunExecutionWorktreeError`, `PhaseSessionError`, and `prepared dispatch: ...` `ValueError` should name the conflicting fields and recommend a `swarm` command. Today most just describe the symptom.
7. **`prepared_plan.v1.json` schema validation on load** — add a JSON Schema check that catches half-rewrites at load time (e.g., assert `descriptor.artifact.git_base_sha == top.git_base_sha` for every phase, or assert the field is absent in embedded copies if it's only meant to live at the top level). The §8.9 fence test catches new writers; this catches existing files that were corrupted by old code or out-of-band edits.
8. ~~**`prepared_plan_sha` self-coherence assertion**~~ — **STRUCK after analysis.** This was based on the same misunderstanding as §3.4.1 row 2: `prepared_plan_sha` hashes `prepared.md`, not the JSON envelope, so editing the JSON in place does not drift `prepared_plan_sha`. There is no self-coherence assertion to add at the JSON-load layer.
9. **Recovery-operation policy + lint** — codify the §3a contributor rule (no /tmp helper scripts as canonical recovery paths) in `CONTRIBUTING.md` or equivalent. Add a CI lint that fails if `swarm-do/docs/` or `swarm-do/role-specs/` references any `/tmp/*.py` or `/tmp/*.sh` path as a fix instruction. Probes are exempt; recovery actions are not.
10. **Investigation-note hygiene sweep** — audit `swarm-do/docs/investigations/` for any other notes that recommend manual JSON edits, sed/awk surgery, or /tmp helpers as the official remediation. Each such note gets a follow-up ticket to surface the operation as a `swarm` subcommand. Run this sweep as part of this epic so operators always have a sanctioned path.

---

## 9. Test gap

Three regression tests anchor the contract. Each goes in `swarm-do/py/swarm_do/pipeline/tests/`.

- **Worktree base drift, clean branch** → second `materialize` call rebuilds, no errors, `worktree_rebuilt` event appended.
- **Worktree base drift, dirty branch** → raises `RunExecutionWorktreeRebuildRequired` with the unadopted-commits payload; pump translates to `needs_input`.
- **Half-rewritten prepared artifact** → dispatch fails with the new diagnostic message; running `prepare refresh-base` resolves it; subsequent dispatch passes.

Plus a meta-test asserting that no other module writes `git_base_sha` into `prepared_plan.v1.json` (fence test for §8.9).

---

## 10. Beads tickets to file

When this plan is accepted, file:

**Bugs**
- `bug: worktree base_sha drift hard-aborts dispatch instead of rebuilding` (P0, references §2).
- `bug: out-of-band git_base_sha rewrite leaves embedded artifacts inconsistent with sidecars` (P0, references §3). **PR co-ships:** `PreparedArtifactWriter` seam (§3.4 Layer A), `swarm prepare refresh-base` command (§3.4 Layer A), upstream writer guard + fence test (former §8.9, now P0), `/tmp/refresh-git-base.py` retirement with fixture capture (§3a), and the §3.5 test suite. Hard dep: §3a tasks gate this PR's merge.
- ~~`bug: out-of-band git_base_sha rewrite invalidates self-recorded prepared_plan_sha`~~ — **DROPPED after analysis.** `prepared_plan_sha` hashes `prepared.md`, not the JSON envelope; the symptom that motivated this ticket was either covered by Bug 2 (sidecar drift) or by a `phase_sessions.py:1253` mismatch caused by something other than `/tmp/refresh-git-base.py`. If a real `prepared_plan_sha` mismatch is observed in production, file a fresh ticket with the actual reproduction — do not refile this draft's framing.

**Epic — Recovery UX (P1, ships first)**
- `epic: SwarmDaddy run-recovery CLI surface and slash-command UX` (references §6 + §7)
  - child: `feat: swarm phases doctor` — includes probe-error isolation acceptance criterion (§6) and pre-pump preflight integration (former §8.6, now part of this epic).
  - child: `feat: swarm phases reset` (and `--hard` flag) — includes `_reset_phase_to_pending` field-coverage audit (former §8.8, now part of this epic). Without the audit, the new command ships with the same gap as `_reset_phase_to_pending` today.
  - child: `feat: swarm phases redo`.
  - child: `feat: swarm worktrees reset` and `worktrees status`.
  - child: `feat: swarm prepare refresh-base` — see Bug 2; this child is the user-facing wrapper, the Bug 2 PR delivers the underlying writer.
  - child: `feat: structured audit-trail events for every auto-recovery action` (former §8.7, now part of this epic). Locks in the contract that no recovery command silently mutates state.
  - child: `feat: /swarmdaddy:status` slash command.
  - child: `feat: /swarmdaddy:redo` slash command (depends on doctor + reset + worktrees reset + prepare refresh-base).
  - child: `feat: /swarmdaddy:repump` slash command.

**Epic — Drift hardening (P2, ships after Recovery UX)**
- `epic: SwarmDaddy validator drift-classification rollout` (references §4 + §8)
  - 10 children, one per remaining item in §8 (after promotions to Recovery UX).

**Hard-gate task (part of Bug 2's PR — not standalone)**
- `task: retire /tmp/refresh-git-base.py and /tmp/reset-phase2.py; update investigation note` (P1, references §3a). **Sequence: fixture-capture → replacement-ship → delete-scripts → audit-references — same PR, same author, same review.** The fixture-capture step (§3a item 1) anchors §3.5 Test 5 and Test 8 and must precede the script delete.

The recovery-UX epic ships before the hardening epic — operators need the rescue lever first; broader auto-recovery comes once we've learned from the explicit-recovery telemetry.

---

## 11. Definition of done

1. Both bugs have a regression test that fails on `main` and passes after the fix.
2. The current stuck run `01KQF2CF61YV7SYVREEWRE4GFB` completes via `swarm prepare refresh-base` + `swarm phases pump` (no manual JSON edits). Both `check_stale()` and `_verify_dispatch_sidecars()` return clean against the post-refresh state.
2a. `check_stale()` returns `None` for `git_base_sha` and `phase:<id>` immediately after `prepare refresh-base`. (`source_plan_sha` and `prepared_plan_sha` are not refresh-base's responsibility — if they're stale the operator needs `re-prepare`.)
3. `swarm phases doctor`, `swarm phases reset`, `swarm phases redo`, `swarm worktrees reset/status`, `swarm prepare refresh-base` are documented in `swarm-do/docs/` and exposed in `--help`.
4. `/swarmdaddy:status`, `/swarmdaddy:redo`, `/swarmdaddy:repump` are usable in Claude Code with no prior context-loading required (they call `doctor` to derive everything).
5. Every auto-recovery action emits an audit event visible in `phases status --events`.
6. The shared anti-pattern is documented as a heading in the contributor guide so new validators are written against the Tier-A/B/C taxonomy from day one.
7. **`/tmp/refresh-git-base.py` and `/tmp/reset-phase2.py` are removed from disk** after the sanctioned replacements ship and the regression fixtures are captured. The investigation note (`swarm-do/docs/investigations/2026-04-30-sensitive-path-write-block.md` lines 451–457 + 307) is updated to point at `swarm prepare refresh-base` and `swarm phases reset --hard` instead.
8. The recovery-operation policy from §3a is codified (CONTRIBUTING.md + the §8.9 CI lint, formerly §8.12), so a future operator under time pressure cannot point a colleague at a `/tmp/*.py` script and call it the official fix.
9. **`PreparedArtifactWriter` is the sole writer of `git_base_sha` into `prepared_plan.v1.json` and into `data/runs/<run-id>/work_units/*.json`.** Fence test (§3.5 Test 10) anchors this; the test fails the build if any other module reaches into those keys.
10. The §3.4.0 multi-file atomicity recipe (snapshot → stage → commit → verify → rollback) has unit tests that parametrize the failure point across every phase.

---

## 12. Open architectural question — deferred (needs more research)

**The two architectural agents disagreed on the bigger storage question.** This plan does not resolve it; we ship the §1–§11 work in parallel.

### 12.1 The split

- **Code-walk verdict (architecture-assessment-2026-05-01.md):** Foundation, not duct-tape. Status quo (six JSON files, two roots, atomic per-file writes, JSON-Schema-validated event log) is defensible for a single-operator local CLI. The one rotten beam is coupled-invariant ownership (`PreparedArtifactWriter` retires it in ~1 week). SQLite + event sourcing + state aggregate are each 4–8+ weeks for what a 200-LoC class buys in a week. Verdict: do not migrate.
- **Research verdict (research-similar-systems-2026-05-01.md):** SQLite + pydantic v2 is the highest-leverage single adoption. Dagster's `SqliteRunStorage` (~800 LoC blueprint) and Prefect 2's local mode both target exactly this single-operator, no-daemon profile. Replaces 5+ JSON files, 4 hand-rolled validators, and the multi-file atomicity gap with one `BEGIN; ...; COMMIT;`. The 7-step incremental refactor path can run alongside this plan; the /tmp surgery pain dies at step 4. Verdict: migrate, incrementally.

### 12.2 What the plan does about it

**Nothing — for now.** The §1–§11 work ships either way. `PreparedArtifactWriter` is required either way (it becomes the migration seam if we go to SQLite; it stays as the JSON owner if we don't). The §3.4.0 atomicity recipe is required either way (it's the contract regardless of storage).

The decision **is not blocking this plan**, and we are not deferring this plan to wait on it.

### 12.3 Follow-on research epic to file

After this plan ships (target: ~3 weeks from acceptance), open:

- `epic: SwarmDaddy state-storage architecture review (SQLite vs. status quo)` (P3, exploratory)
  - child: `research: spike a sqlite-backed RunStateView covering the worktree manifest only` — the smallest proving ground per the research memo's step 2. Surface area: 1 file, 1 schema. Goal: measurable gain or no?
  - child: `research: prototype pydantic v2 schemas for prepared_plan.v1.json + work_unit sidecars` — does schema-as-code reduce the validator footprint visibly, or just relocate it?
  - child: `research: characterize the current bug-class distribution` — of the recovery-UX epic's bugs, which would have been impossible-by-construction under SQLite + WAL? Which would not? Cost the migration against the bugs-it-prevents, not against architectural elegance.
  - child: `decision: SQLite migration go/no-go` — owners + criteria + sunset path for any decision.

The signal that informs this decision is the *post-Recovery-UX bug rate*. If the new Recovery-UX surface is enough, the migration is YAGNI. If we keep finding new flavors of cross-file drift the `PreparedArtifactWriter` doesn't cover, that's the case for SQLite.

### 12.4 Reading list

For whoever picks up the §12 epic:

- [`swarmdaddy-state-storage-sqlite-recommendation-2026-05-01.md`](./swarmdaddy-state-storage-sqlite-recommendation-2026-05-01.md) — follow-up research + recommendation for the SQLite vs. JSON state-store question.
- [`research-similar-systems-2026-05-01.md`](./research-similar-systems-2026-05-01.md) — full memo, ~2480 words.
- [`architecture-assessment-2026-05-01.md`](./architecture-assessment-2026-05-01.md) — counter-position, file:line evidence.
- Dagster `SqliteRunStorage` source (referenced by research memo) — the closest analog blueprint.
- jj (jujutsu) operation log — the closest analog for "treat the manifest as a cache, reconcile from real state on every command."
