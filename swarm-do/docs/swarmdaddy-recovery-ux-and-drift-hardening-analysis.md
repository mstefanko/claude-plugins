# Analysis — SwarmDaddy Recovery UX & Drift-Hardening Plan

**Plan under analysis:** `swarm-do/docs/swarmdaddy-recovery-ux-and-drift-hardening-plan.md`
**Reviewer:** agent-analysis (parallel-of-1, no competitive frame)
**Date:** 2026-05-01
**Status:** COMPLETE — recommendation: ship Recovery-UX epic, but fix one factual error in §3.4.1 row 2 and re-sequence §3a/§8.6-8 before tickets are filed.

---

## 0. Verdict in one paragraph

The plan is fundamentally sound. Both bugs are real, the classifier-based fix
for Bug 1 is correct, the atomic primitive for Bug 2 is correct, and the §4
Tier-A/B/C taxonomy generalizes the right anti-pattern. **However, §3.4.1
row 2 contains a factual error about how `prepared_plan_sha` is computed that,
if implemented as written, will produce a self-referencing chicken-and-egg
loop that does not actually exist in the code.** Fixing that one row collapses
the entire "compute twice or exclude-self-field" complexity the plan flags as
a risk, and probably collapses Bug 3 into Bug 2. Two smaller sequencing
corrections round it out. Ship after those edits.

---

## 1. Assumptions verified against source

All file:line references confirmed against the codebase as of `870f821`:

- **VERIFIED — `_validate_existing_manifest` (`execution_worktree.py`)** does a
  flat dict compare across `run_id`, `source_git_root`, `source_project_root`,
  `safe_git_worktree_root`, `safe_project_root`, `project_subdir`, `branch`,
  `base_sha`. Plan's §2.2 conflation claim (identity vs. base/branch fields)
  is correct. The §2.3 classifier is a clean fit.

- **VERIFIED — `check_stale()` (`prepare.py:2012`)** returns `StaleReason` with
  exactly four drift keys: `source_plan_sha`, `prepared_plan_sha`,
  `git_base_sha`, `phase:<id>`. Plan's §3.4.1 table matches the surface.

- **VERIFIED — embedded vs. sidecar validator (`prepare.py:1283`)** raises
  `prepared dispatch: work_unit_artifacts[N].artifact does not match sidecar`.
  The SHA gate (`_verify_hashed_sidecar`, line 1303) hashes the sidecar file;
  the structural compare hashes the in-memory dict against
  `descriptor["artifact"]`. Plan's §3.3 "keep the embedded check; the fix is
  upstream" is correct.

- **VERIFIED — phase_sessions.py guard (`phase_sessions.py:1252-1253`)** raises
  `PhaseSessionError("phase-session prepared_plan_sha does not match accepted
  prepared artifact")`. Plan's §3.4.2 callout is correct: refresh-base must
  rewrite `phase_sessions.v1.json`'s `prepared_plan_sha`.

- **VERIFIED — /tmp scripts still on disk:** `/tmp/refresh-git-base.py` and
  `/tmp/reset-phase2.py` both exist. Investigation note exists at the cited
  path. §3a is actionable.

- **VERIFIED — no existing `phases doctor`, `phases reset`, `phases redo`,
  `worktrees reset`, `worktrees status`, or `prepare refresh-base` subcommand.**
  CLI has `preset`, `pipeline`, `providers`, `mode`, `status`, `rollout`. The
  recovery surface is genuinely greenfield. Existing slash commands in
  `swarm-do/commands/`: `do.md`, `prepare.md`, `resume.md`, etc. — no
  `:status`, `:redo`, `:repump`. Plan's "additive, no breaking changes"
  framing holds.

- **CORRECTED — §3.4.1 row 2 self-coherence claim is wrong.** See §2 below.

---

## 2. Critical correction — §3.4.1 row 2 (`prepared_plan_sha`) does NOT have a self-coherence problem

The plan asserts that `/tmp/refresh-git-base.py` "changes the file's bytes
(bumping `git_base_sha`) but never updates the recorded `prepared_plan_sha`
field, so the file's actual sha drifts from its self-recorded sha." From this
the plan derives a "compute twice or exclude-self-field" deterministic
round-trip concern.

**This is wrong.** Read the actual code:

- **`prepare.py:127, 176-177, 197-199`** — `prepared_plan_path` is a separate
  derivative file: the canonical-plan **markdown body**
  (`canonical_plan_text(phases)` at line 674), written via
  `(root / prepared_rel).write_text(prepared_text, ...)` at line 834. It is
  **not** `prepared_plan.v1.json`. The two have different file paths and
  different content types.

- **`prepare.py:676`** — `prepared_sha = _sha256_bytes(prepared_text.encode("utf-8"))`.
  This hashes the markdown body, not the JSON envelope.

- **`prepare.py:2046`** — `check_stale` row 2 does
  `_sha256_file(prepared_plan_path) != artifact["prepared_plan_sha"]`, where
  `prepared_plan_path` resolves to the canonical markdown derivative.

In other words: `prepared_plan_sha` is the SHA of a **different file** (the
canonical-plan `.md`) than the one `/tmp/refresh-git-base.py` mutates (the
`.v1.json` envelope). Bumping `git_base_sha` inside `prepared_plan.v1.json`
mathematically cannot drift `prepared_plan_sha`, because the source bytes
that hash feeds on never moved.

**What this means for the plan:**

1. There is no chicken-and-egg, no "compute twice," no "exclude-self-field
   protocol." The implementer should **not** burn time on that contour. The
   row 2 cell collapses to: *no-op for refresh-base, as long as the
   canonical markdown derivative on disk is unchanged*.

2. The plan's §3.4 step 6 (`_verify_dispatch_sidecars` post-condition) and
   §3.5 test 7 (`check_stale` post-condition returns `None`) are still the
   right contract — they will trivially pass once row 2 is correctly
   understood.

3. Bug 3 in §10 (`bug: out-of-band git_base_sha rewrite invalidates
   self-recorded prepared_plan_sha`) **likely does not exist as described**.
   Before filing it, reproduce it: the symptom the operator probably saw is
   `phase-session prepared_plan_sha does not match accepted prepared
   artifact` from `phase_sessions.py:1253` — which is a *different* drift
   surface (state-vs-artifact, not file-vs-recorded-sha) and is correctly
   covered by §3.4.2's `phase_sessions.v1.json` rewrite. **Recommend
   merging Bug 3 into Bug 2 with the §3.4.2 fix as the resolution, and
   removing §3.4.1 row 2's "compute twice or exclude-self-field" caveat.**

4. **One real residual risk** the plan correctly flags is whether any code
   path in `prepare.py` recomputes `prepared_plan_sha` by re-canonicalizing-
   and-hashing the source plan vs. by reading the markdown derivative file.
   Both paths converge to the same value at prepare time, but if a caller
   does a fresh-canonicalize, an in-place edit of the `.md` (which
   refresh-base must NOT do) would break the contract. **Test 6
   (recurring-cycle test) should explicitly verify `prepared_plan_path`
   (the markdown file) is byte-identical before and after refresh-base.**
   That single assertion replaces the entire "self-coherence" mechanism.

This is the most consequential analysis finding. The plan as written
implements an imaginary problem with a real cost; the fix is one paragraph
of plan text.

---

## 3. Sequencing — Recovery UX before Hardening is correct

Recovery-UX (P1) before Hardening (P2) is right:

- The trigger run (`01KQF2CF61YV7SYVREEWRE4GFB`) is *currently stuck*. §5
  immediate remediation is a manual workaround until §3.4 ships. Operators
  hitting this need a rescue lever first; broader auto-recovery (§4
  Tier-A/B/C across every validator) benefits from telemetry the recovery
  commands will produce.

- Recovery-UX has direct dependencies on Bug 1/Bug 2 fixes (the classifier
  and atomic primitive are *consumed* by `phases doctor` and `phases redo`).
  Hardening §8 has 13 independent items, most of which do not depend on the
  recovery commands existing. Reversing the order would delay the rescue
  lever for no reason.

- One nuance: §8.6 (pre-pump preflight calling `phases doctor` implicitly)
  and §8.7 (audit-trail events) are tightly coupled to the recovery
  commands. **Pull §8.6 and §8.7 forward into the Recovery-UX epic as
  terminal children** — they're the contract that makes auto-recovery
  visible, and they're trivial after `doctor` exists. Leaving them in §8
  risks shipping `doctor` without the audit trail, which is the
  invisibility the plan rightly complains about today.

- Also pull §8.8 (`_reset_phase_to_pending` field coverage audit) into
  Recovery-UX as a sub-step of `feat: swarm phases reset`. Otherwise
  `phases reset --hard` ships with the same field-coverage gap that made
  `/tmp/reset-phase2.py` necessary.

**Action:** promote §8.6, §8.7, §8.8 into Recovery-UX. Hardening drops to
10 items.

---

## 4. §3a /tmp script retirement — hard dependency, not parallel cleanup

- **§3a item 1 (replace before delete)** is a hard dependency — Bug 2's fix
  is `swarm prepare refresh-base`, and §3a's first action is "ship that
  command before deleting the script." Same work, same ticket. Don't split.

- **§3a item 5 (capture half-rewrite state as fixture before deletion)** is
  a hard dependency on the regression test in §3.5 test 5. Capture first,
  delete second. The `task: retire /tmp/...` ticket in §10 must list this
  ordering explicitly.

- **§3a items 3 and 4 (contributor policy + grep audit + CI lint)** are
  parallelizable cleanup that can land any time after Bug 2's fix ships.
  These are §8.12 / §8.13 in Hardening. Don't block Bug 2 on them.

**Action:** rewrite §10 paired task as: *"depends on `feat: swarm prepare
refresh-base` AND `feat: swarm phases reset --hard`; blocks `epic:
drift-hardening §8.12 + §8.13`; includes regression-fixture capture as a
sub-step before file deletion."* The current §10 wording elides the
fixture-capture step.

---

## 5. `phases doctor` as keystone — verified, with one caveat

Keystone is correct:

- **`doctor` is read-only and produces a JSON contract** (§6) that every
  other command and slash-command consumes. This lets slash commands stay
  thin (render and prompt) and lets `redo` orchestrate by calling doctor
  and acting on each finding.

- **Caveat:** `doctor` probes four areas (phase status, lease, worktree,
  prepared-dispatch). These are independent producers; if one probe panics
  it should not crash the others. **Recommend explicit per-probe error
  isolation:** each probe returns either a finding or a `probe_error`
  finding; `doctor` never raises. This matters because `doctor` is the
  recovery entry point — a buggy probe must not lock the operator out of
  seeing the other three.

- **§8.6 (pre-pump preflight calls doctor)** makes isolation-or-bust
  load-bearing. If a probe panics, the pump panics too. Add probe-error
  isolation to the §6 doctor spec as an explicit acceptance criterion.

---

## 6. Sequencing within Recovery-UX epic (corrected)

Correct dependency order (each row blocks the row below):

1. `feat: swarm prepare refresh-base` (Bug 2 fix) — depends on nothing.
2. `feat: swarm worktrees reset` + `worktrees status` — depends on Bug 1
   classifier landing in `execution_worktree.py`. Bug 1 itself is a P0 bug
   not a feat; file the classifier as the bug fix, the user-surface
   wrappers consume the corrected internals.
3. `feat: swarm phases reset` (incl. `--hard`) — depends on §8.8 field
   audit (now promoted into this epic).
4. `feat: swarm phases doctor` — depends on (1)-(3) being callable so it
   can recommend them.
5. `feat: swarm phases redo` — depends on `doctor` + `worktrees reset` +
   `prepare refresh-base` + `phases reset`.
6. `feat: /swarmdaddy:status` — depends on `phases doctor`.
7. `feat: /swarmdaddy:redo` — depends on `phases redo` (CLI).
8. `feat: /swarmdaddy:repump` — depends on existing `phases pump`. Trivial.
   Ship in parallel.
9. **(promoted §8.6)** Pre-pump preflight calls `doctor` implicitly.
10. **(promoted §8.7)** Audit-trail events for every auto-recovery action.
11. `task: /tmp` script retirement (§3a, paired with B2/R3).

**Parallelizable boundaries:** R6/R7/R8 (slash commands) can ship in
parallel with each other once their CLI dependencies land. R10
(audit-trail) can land in parallel with R4-R5 if it's wired as a hook
rather than baked into the commands.

---

## 7. Risks

1. **§3.4.1 row 2 mis-implementation.** If the implementer writes the
   "compute twice or exclude-self-field" mechanism described in the plan,
   the result is dead code that adds complexity for no gain. *Mitigation:*
   strike the row 2 caveat from the plan before tickets are filed; add a
   single test asserting `prepared_plan_path` (markdown file) is byte-
   identical pre/post refresh-base. (See §2.)

2. **Atomicity claim is hard.** §3.4 promises "whole-run atomic"; the file
   set is `prepared_plan.v1.json` + N sidecars + (per §3.4.2)
   `phase_sessions.v1.json` + possibly `inspect/*.json`. POSIX `rename`
   gives per-file atomicity, not multi-file. *Mitigation:* the plan names
   the right pattern (backup + restore-on-failure), but implementers should
   structure the rewrite as: (a) snapshot all targets to `.bak-<utc-iso>`,
   (b) write all files to `.tmp` siblings, (c) `os.replace` each `.tmp`
   into place sequentially, (d) on any failure, `os.replace` each `.bak`
   back. This is the only way to get effective atomicity from POSIX.
   Document this in the ticket so implementers don't reach for SQLite or
   filesystem snapshots.

3. **Manifest schema migration (§8.5) collides with Bug 1 fix.** Bug 1's
   classifier reads existing manifests; if the schema migrates concurrently,
   the classifier may see fields it doesn't recognize. *Mitigation:* land
   Bug 1's fix first; §8.5 must add fields, not remove them, and the
   classifier should ignore unknown keys.

4. **`phases doctor` JSON contract becomes load-bearing across two epics.**
   Slash commands and `phases redo` both consume it. If the schema changes,
   both break. *Mitigation:* add `schema_version` to `doctor`'s JSON output
   from day 1, and write a contract test asserting slash commands only
   read documented fields.

5. **Backup file proliferation.** Each `prepare refresh-base` creates a
   `.bak-before-refresh-base-<utc-iso>` file. Long-running runs that
   refresh-base on every base bump accumulate dozens of backups in
   `data/runs/<run-id>/`. *Mitigation:* add `--keep-backups N` flag
   (default 3) that prunes oldest. Not a P0 — file as a §8 sub-item.

6. **Coupling concern: `phases doctor` orchestration vs. lease arbitration
   (§8.4).** The plan says "doctor should pick automatically; redo should
   orchestrate." If doctor auto-reaps a lease that a different process
   actually still holds, that's a write-conflict. *Mitigation:* doctor
   stays read-only; only `redo`/`reap` mutate; doctor's recommendation
   must include a timestamp-fenced lease check that `redo` re-validates
   before reaping.

---

## 8. Out of scope (preserves plan's bounds)

- Anything that changes how `prepared_plan_sha` is *computed* at original
  prepare time. The fix is in refresh-base, not in prepare.
- Reworking the `data/runs/<run-id>/` directory layout. The plan correctly
  treats it as fixed.
- Migrating to a non-POSIX storage backend for atomicity.
- Touching the `do --prepared` writer's reading-from-sidecar contract.
  Embedded check stays; the fix is upstream.
- Changing decompose, plan, or context-bundle phases. Drift surface is in
  prepare/dispatch/worktree only.

---

## 9. Test coverage gaps the plan misses

§9 lists three regression tests + a fence test. Add:

1. **Markdown-derivative invariance test (replaces §3.5 row 2 caveat):**
   capture `prepared_plan_path`'s bytes pre-`refresh-base`, run the
   command, assert post-bytes are byte-identical. This is the single
   contract that makes §3.4.1 row 2 trivially green.

2. **Probe-error isolation test for `phases doctor`:** monkeypatch one of
   the four probes to raise `RuntimeError`; assert `doctor` returns a
   `probe_error` finding for that probe and valid findings for the other
   three. Without this, §8.6's pre-pump preflight becomes a footgun.

3. **Atomicity-restoration test (cross-file boundary):** simulate failure
   between sidecar-rewrite and `phase_sessions.v1.json` rewrite. Verify
   all backups are restored. The plan's §3.5 test 4 only covers the
   prepared-plan↔sidecar boundary, not the cross-process-state boundary.

4. **Doctor JSON-contract test:** assert the JSON shape `doctor` emits
   matches what `/swarmdaddy:status` and `phases redo` expect. Catch
   silent breakage early.

5. **`/tmp/refresh-git-base.py` doesn't exist after delete:** simple
   `assert not os.path.exists(...)` in CI. Closes §3a item 2.

6. **`grep -rn 'git_base_sha' swarm-do/py/` audit fence test:** assert no
   module other than `prepare.py`, `prepare_refresh.py` (or wherever the
   primitive lives), and `phase_sessions.py` writes `git_base_sha` into
   any persisted JSON. Generalizes §8.9's fence test.

---

## 10. Work breakdown (execution-ready)

**Bug fixes (P0, parallel):**

- **B1 — Bug 1 (worktree drift classifier).**
  `swarm-do/py/swarm_do/pipeline/execution_worktree.py` (validate function
  + `_create_run_worktree` + new typed exception
  `RunExecutionWorktreeRebuildRequired`). Three regression tests in
  `tests/test_execution_worktree.py` per §2.4.

- **B2 — Bug 2 (atomic refresh-base primitive).** New module
  `swarm-do/py/swarm_do/pipeline/prepare_refresh.py` (suggested) with new
  function called from `prepare.py` and wired through `cli.py` as
  `cmd_prepare_refresh_base`. Steps 1-6 per §3.4 Layer A, **with §3.4.1
  row 2 simplified per §2 of this analysis** (no self-coherence dance —
  `prepared_plan_path` is a different file). Cross-file atomicity per
  Risk 2. Tests per §3.5 1-7 (drop test 8 if Bug 3 is merged into Bug 2
  per §2).

**Recovery-UX epic (P1, sequenced per §6):**

- R1 — `swarm prepare refresh-base` CLI surface (built on B2).
- R2 — `swarm worktrees reset` + `worktrees status` (built on B1).
- R3 — `swarm phases reset` (incl. `--hard`) — promote §8.8 here.
- R4 — `swarm phases doctor` (with probe-error isolation per §5).
- R5 — `swarm phases redo` (orchestration).
- R6 — `/swarmdaddy:status` slash command.
- R7 — `/swarmdaddy:redo` slash command.
- R8 — `/swarmdaddy:repump` slash command.
- R9 — pre-pump preflight (§8.6 promoted).
- R10 — audit-trail events (§8.7 promoted).
- R11 — `/tmp` script retirement (§3a, paired with B2).

**Hardening epic (P2, parallelizable, 10 items after promotions):**

- §8.1, 8.2, 8.3, 8.4, 8.5, 8.9, 8.10, 8.11, 8.11a, 8.12, 8.13. (8.6, 8.7,
  8.8 promoted to Recovery-UX.)

---

## 11. UNVERIFIED — items needing source confirmation by the implementer

These are not blockers but the implementer should verify before coding:

- **`inspect_artifact` body content (§3.4.2 row 4).** Plan flags this as
  `Verify in implementation`. Confirmed it should be verified —
  `prepare.py:805,818,834` shows `inspect_payload` is written via
  `json.dumps(inspect_payload, indent=2, sort_keys=True) + "\n"` to a
  separate `.json` file with its own sha. Implementer must read
  `inspect_payload`'s shape (likely in `mco_stage.py` or `inspect.py`) to
  determine if `git_base_sha` is in it. Not load-bearing for Bug 2 if
  absent.

- **Whether any other location stores `git_base_sha`** beyond the six the
  plan enumerates. **Recommend `grep -rn 'git_base_sha' swarm-do/py/` as
  the first step of B2 implementation.** Surprises here invalidate the
  "whole-run atomic" contract. (See test 6 above.)

- **Whether `_reset_phase_to_pending` (`phase_sessions.py:1331`) clears
  enough fields for `phases reset --hard`.** Plan says
  `/tmp/reset-phase2.py` cleared 30+ fields vs. the in-process helper's
  13. Diff the two as the first step of R3 — that's §8.8.

- **Worktree-rebuild + lease interaction.** Plan's Bug 1 fix discards the
  execution branch when `BASE_DRIFT_SAFE`. If a stale lease exists on a
  phase session for that branch, the discard removes the artifact the
  lease points at. Verify the lease-arbitration path (`phase_sessions.py`
  lease helpers) tolerates a missing branch. May surface as a §8.4
  sub-issue.

---

## Status: COMPLETE

Recommendation: merge this analysis into the plan as an appendix (or keep
as a sidecar `*-analysis.md` per local convention), strike §3.4.1 row 2's
self-coherence paragraphs, fold Bug 3 into Bug 2 unless the
phase_sessions.py symptom is reproduced as a distinct bug, promote
§8.6/§8.7/§8.8 into Recovery-UX, then file the beads tickets per §10.
After those edits the plan is execution-ready.
