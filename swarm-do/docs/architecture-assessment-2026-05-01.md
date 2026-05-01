# SwarmDaddy Run-Orchestration Architecture Assessment

**Date:** 2026-05-01
**Author:** agent-deep-analysis
**Scope:** `swarm-do/py/swarm_do/pipeline/` (prepare, phase_sessions, execution_worktree, phase_pump, run_state)
**Trigger:** `swarm-do/docs/swarmdaddy-recovery-ux-and-drift-hardening-plan.md` (draft, 2026-05-01)
**Question:** Is this layer foundation-ready or duct-tape that needs a refactor underneath?

---

## Executive verdict (one paragraph)

The run-orchestration layer is **mostly foundation, with one rotten beam and a partly-mistaken plan trying to brace it**. The state shape (six JSON files across two roots, each with its own validator) is defensible — the files are append-mostly, atomically written via `os.replace`, and bounded by run-id; this is not where the bug surface lives. The actual rot is shallower: there is no code-level seam that owns the *coupled* invariant "embedded artifact bytes <-> on-disk sidecar bytes <-> descriptor.sha", and `git_base_sha` is denormalized into 5+ places that only stay coherent because nobody has yet written a tool that mutates one without the others — until `/tmp/refresh-git-base.py` did. Fix that one seam (a `PreparedArtifactWriter` that owns the embedded<->sidecar<->sha triple) and the duct-tape disappears; you do **not** need SQLite, you do **not** need event sourcing, and you do **not** need a `RunState` aggregate as P0. The plan is correct in instinct (build a sanctioned `prepare refresh-base` primitive, classify validators Tier-A/B/C, ship a `phases doctor` coordinator) but contains one **factually incorrect** claim — the "self-referencing `prepared_plan_sha`" framing in section 3.4.1 is wrong — and it under-scopes the upstream guard that would prevent the next `/tmp/*.py` script from being invented. **Ship the plan with two amendments and one small refactor co-shipped.** No deferral. No big-bang rewrite.

---

## 1. Assumptions audit

| Assumption (made by plan or implied) | Verdict | Evidence |
|---|---|---|
| `prepared_plan_sha` is self-referencing (file records hash of itself) | **WRONG** | `prepare.py:668` emits `prepared.md` (canonical plan markdown). `prepare.py:676` computes `prepared_sha = _sha256_bytes(prepared_text.encode("utf-8"))` over that markdown. `check_stale` at `prepare.py:2042-2046` re-hashes `prepared_plan_path` which IS `prepared.md` (`prepare.py:668`), not the JSON artifact. The artifact JSON is at `_artifact_path` -> `data/runs/<run-id>/<_ARTIFACT_NAME>` and its bytes are never self-hashed. |
| Bumping `git_base_sha` in the artifact JSON breaks `prepared_plan_sha` | **WRONG** (follows from above) | `prepared_plan_sha` hashes `prepared.md`, which `/tmp/refresh-git-base.py` does not touch. The plan's "second latent bug" in section 3.4.1 row 2 and the third P0 ticket in section 10 (`bug: out-of-band git_base_sha rewrite invalidates self-recorded prepared_plan_sha`) describe a failure mode that **cannot occur from the script alone**. |
| Embedded `artifact` != on-disk sidecar after a base bump | **CORRECT** | `prepare.py:1280-1286`: `embedded = descriptor.get("artifact")` then `if embedded != artifact: raise`. `_verify_hashed_sidecar` (`prepare.py:1300-1318`) hashes the sidecar file; SHA passes because file unchanged, but the `dict ==` check at 1282 fails on the bumped `git_base_sha` field. |
| `_validate_existing_manifest` hard-aborts on base drift | **CORRECT** | `execution_worktree.py:859-874`. `expected` includes `base_sha` (L868); `mismatched` set built by literal equality (L870); raises `RunExecutionWorktreeError` (L872). No tier classification. |
| `check_stale` checks four drift surfaces in one pass | **CORRECT** | `prepare.py:2012-2090`. Sources: `source_plan_sha` (L2038), `prepared_plan_sha` (L2046), `git_base_sha` (L2053), `phase:<id>` cache_key (L2078-2087). |
| Every dispatch hop already calls `check_stale` + sidecar hashes | **CORRECT** | `phase_sessions.py:1196` calls `check_stale` inside `_load_accepted_prepared`; `phase_sessions.py:1202` calls `_verify_sidecar_hashes` (L1211-1224 — SHA per descriptor). Called from `claim_next_phase` (L415), `phase_status` (L299), `init_phase_sessions` (L171). |
| State writes are atomic (NamedTemporaryFile + fsync + os.replace) | **CORRECT** | `prepare.py:1462-1492`, `run_state.py:176`, `execution_worktree.py:_atomic_write_bytes` L1392. All three modules import or re-implement the same idiom. |
| Run event log is append-only JSONL with schema validation | **CORRECT** | `run_state.py:57-78`. `append_run_event` writes `telemetry/run_events.jsonl`; `validate_run_event` enforces schema. |
| `git_base_sha` lives in 5+ persisted places | **CORRECT** | (1) `prepared_plan.v1.json` top-level (`prepare.py:813`); (2) every `work_unit_artifacts.<phase>.artifact.git_base_sha` (`prepare.py:758`); (3) on-disk sidecar bytes at `data/runs/<run-id>/work_units/*.json` (also via L758 — same dict written to disk); (4) `~/.local/share/swarmdaddy/worktrees/<run-id>/manifest.json` field `base_sha` (`execution_worktree.py:846`); (5) integration manifest (`execution_worktree.py:441, 663`); plus inspect.v1.json transitively. |
| `phase_sessions.v1.json` records `prepared_plan_sha` | **CORRECT, but it's the prepared.md SHA** | `phase_sessions.py:240` copies `prepared["prepared_plan_sha"]` into state. That value is the markdown SHA from `prepare.py:676`, not a JSON-bytes self-hash. Plan section 3.4.2 instruction "recompute and rewrite, otherwise the next pump rejects" is **only correct if `prepared.md` is rewritten**, which it should not be during a base bump. |

---

## 2. Recommendation (one direction, not a menu)

**Ship the plan, with these amendments, plus one small refactor co-shipped.**

### Amendments to the plan

**A1. Drop the "self-referencing `prepared_plan_sha`" framing.** The plan's section 3.4.1 row 2 is factually wrong about the on-disk shape. Delete the "compute twice or exclude-self-field" speculation. The third P0 ticket in section 10 (`bug: out-of-band git_base_sha rewrite invalidates self-recorded prepared_plan_sha`) describes a failure mode that doesn't exist as written; either repurpose it as "harden `prepared_plan.v1.json` JSON-bytes integrity" or drop it. **This matters because building a refresh primitive against a phantom invariant produces dead code that later operators will copy.**

**A2. Promote section 8.9 (`prepare refresh-base` upstream guard) from a hardening backlog item to a P0 child of the recovery-UX epic.** This is the only real foundation question raised by Bug 2: the codebase has no enforced seam that says *"all `git_base_sha` writes go through one writer."* Without that guard, the next operator will write `/tmp/refresh-git-base-v2.py` regardless of `swarm prepare refresh-base` shipping. The guard test (section 9 fence test) is the actual contract that matters.

### Co-shipped refactor: `PreparedArtifactWriter` (~1 week, 2 files touched)

Extract the embedded-artifact + sidecar + descriptor.sha write triple into a single class at `swarm-do/py/swarm_do/pipeline/prepared_artifact_writer.py`. Surface area:

```python
class PreparedArtifactWriter:
    def __init__(self, run_id, *, data_dir, repo_root): ...
    def load(self) -> dict: ...                    # current payload
    def begin(self) -> "PreparedArtifactTxn": ...   # context manager - atomic across all sidecars + artifact
class PreparedArtifactTxn:
    def update_git_base_sha(self, new_sha: str) -> None: ...
    def replace_descriptor_artifact(self, phase_id, artifact: dict) -> None: ...
    def commit(self) -> None: ...                   # writes sidecars first, recomputes shas, writes artifact last; on any failure restores from backup
```

The atomicity contract from plan section 3.4 ("whole-run atomic, restore from backup on partial failure") becomes a property of this class, not a property re-derived in every CLI subcommand. `swarm prepare refresh-base` is a 20-line caller. `prepare_plan_run` migrates onto it (so the seam exists from prepare time forward, not just at refresh time). The section 8.9 fence test asserts no other module writes `git_base_sha` into `prepared_plan.v1.json`; that test only passes if every writer routes through this class.

This is the minimum refactor that retires the duct-tape pattern. Anything smaller leaves section 8.9 as a hope rather than a constraint.

### What you do NOT need to do

- **Not SQLite.** The state is small (kilobytes per run), append-mostly, run-scoped. Foreign keys are not the problem; *coupled mutators* are. Migrating to SQLite turns one file-per-concept into one connection-per-process and introduces locking semantics you don't have today. Cost: 4-6 weeks, churns every test fixture in `swarm-do/py/swarm_do/pipeline/tests/`, breaks the "I can `cat` a run's state to debug it" property that is genuinely useful. Buys: foreign-key enforcement of a coupling that the `PreparedArtifactWriter` covers in 200 lines.
- **Not event sourcing.** The current event log is correct as an audit log. Inverting it (events as truth, JSON as projection) requires every reader to replay the log, which doubles startup cost and triples test complexity. The `run_events.jsonl` schema validation already gives you the audit trail you need. Cost: >=8 weeks, rewrites every reader. Buys: time travel that you don't use and reproducibility that the existing SHAs already give you.
- **Not a `RunState` aggregate.** Tempting; premature. The aggregate's value is exactly the `PreparedArtifactWriter`'s value, and trying to make one class own *all* the run's state means it depends on `phase_sessions.py` (different root, different lifetime) and `execution_worktree.py` (different root again, with side effects on git). Decouple later if a second coupling emerges; do not pre-build it.
- **Not a base `Validator` class with `tier()`/`recover()` methods.** The plan's Tier-A/B/C taxonomy is a *naming* contribution, not a *typing* contribution. Tagging existing validators with a tier in their docstring + extracting a helper for the rebuild path in `execution_worktree.py` covers 90% of the value. Adding ABCs to a working validator zoo is the kind of refactor that looks neat in review and decays in production.

### Why not the alternative ("defer the plan, big-bang refactor first")

The plan's Bug 1 fix (section 2: classify worktree drift, auto-rebuild on `BASE_DRIFT_SAFE`) is correct as stated, ships in `execution_worktree.py` only, and would not be made easier by any of the four refactors above. Deferring it means staying broken on legitimate user behavior (commit between phases). The plan's Bug 2 fix is correct in principle; my amendment A1 prevents you from coding to a phantom invariant. There is no scenario where holding off the plan to land a bigger refactor is net-positive for the user.

---

## 3. Verification summary (CoV Phase 4 results)

| # | Question | Answer (verbatim source) | Verdict |
|---|---|---|---|
| 1 | Is `prepared_plan_sha` actually self-referencing as the plan claims? | `prepare.py:676`: `prepared_sha = _sha256_bytes(prepared_text.encode("utf-8"))` where `prepared_text = canonical_plan_text(phases)`. `prepared_plan_path` is `prepared.md` (`prepare.py:668`), not the JSON. | **CONTRADICTS plan** |
| 2 | Does `_verify_dispatch_sidecars`'s embedded!=sidecar check actually catch the `/tmp` script's failure mode? | `prepare.py:1280-1286`: reads sidecar, dict-compares to `descriptor["artifact"]`, raises with `"work_unit_artifacts[N].artifact does not match sidecar"`. SHA gate at L1313-1318 doesn't help because file content unchanged. | **CONFIRMS plan** |
| 3 | Are atomic writes implemented consistently? | `prepare.py:1462-1492` (`_atomic_json_write`): NamedTemporaryFile in same parent, fsync, os.replace. Same idiom in `run_state.py:176` and `execution_worktree.py:1392`. | **CONFIRMS** |
| 4 | Does the codebase already have a single seam for "all `git_base_sha` writes"? | `prepare.py:758`: `artifact["git_base_sha"] = git_base_sha` (in-loop sidecar build at prepare time). `prepare.py:813`: `"git_base_sha": git_base_sha` (top-level, prepare time). No other writer in-tree — but `/tmp/refresh-git-base.py` proves nothing prevents an out-of-tree writer. **No fence test exists.** | **CONFIRMS need for section 8.9 promotion** |
| 5 | Does `_load_accepted_prepared` already run the validators? | `phase_sessions.py:1196` calls `check_stale`; `phase_sessions.py:1202` calls `_verify_sidecar_hashes` (`phase_sessions.py:1211-1224`, hashes every work-unit sidecar). Called on every `claim_next_phase` (L415). | **CONFIRMS** — the doctor command can be a thin wrapper, not a new validator |
| 6 | Does the worktree manifest validator distinguish identity from base drift? | `execution_worktree.py:859-874`: single dict, single `mismatched` list, single raise. No classification. Plan's fix is correct shape. | **CONFIRMS plan** |
| 7 | Could SQLite replace the file-per-concept layout cheaply? | Files: 6 across 2 roots (`<repo>/data/runs/<id>/` and `~/.local/share/swarmdaddy/`). Two-root constraint reflects "repo-visible artifacts" vs. "user-machine state" — encoded in `_repo_visible_run_dir` (`prepare.py:1416`) and `resolve_data_dir`. SQLite would need two databases or violate the boundary. | **CONTRADICTS the SQLite case** |
| 8 | Could events replace JSON files as source of truth? | `run_events.jsonl` is audit-only today. Readers (`phase_status`, `pump_phases`, `claim_next_phase`) all read JSON, not events. Switching invariant requires rewriting every reader; nothing in the plan needs it. | **CONTRADICTS event-sourcing case** |
| 9 | Is `_reset_phase_to_pending` field coverage genuinely thin vs. `/tmp/reset-phase2.py`? | `phase_sessions.py:1331-1343`: clears 11 fields (status, 5 lease fields, last_error, next_retry_at, blocked_reason, retry_policy_decision, blocked_at, evidence_path). Plan section 8.8 says script clears 30+. Confirmed gap. | **CONFIRMS plan** |
| 10 | Does the recovery-UX layer's `phases doctor` need to consolidate validators or just call them? | All four validators (`check_stale`, `_verify_dispatch_sidecars`, `_verify_sidecar_hashes`, `_validate_existing_manifest`) are pure functions or near-pure. `doctor` can call each, collect findings, rank — no consolidation required. | **CONFIRMS plan's "coordinator" framing** |

---

## 4. Contradictions found and how resolved

- **C1 (plan section 3.4.1, section 10): `prepared_plan_sha` is self-referencing.** False. Resolved by amendment A1: delete the "compute twice or exclude-self-field" guidance and the third P0 ticket. The refresh primitive does **not** need to recompute or rewrite `prepared_plan_sha` because that field hashes `prepared.md`, which the operation does not touch. Verifying this: a regression test should assert that after `prepare refresh-base`, `_sha256_file(prepared.md)` is unchanged and equals `payload["prepared_plan_sha"]`. If that ever fails, the operation has overstepped its scope.
- **C2 (plan section 3.4.2): "rewrite `prepared_plan_sha` in `phase_sessions.v1.json`."** Should be a no-op for a base bump. If `prepared.md` is unchanged, `prepared_plan_sha` is unchanged, and `phase_sessions.py:1252` keeps passing. Resolved: drop this bullet from the refresh primitive's checklist. Keep the section 3.4.2 bullets for the worktree manifest's `base_sha` and the inspect_artifact sidecar — those are real coupling.
- **C3 (plan section 10): three P0 tickets reduce to two.** Bug 2 has one root cause (script doesn't rewrite sidecars) and one user-facing symptom (`embedded != sidecar`). The "prepared_plan_sha" stream is phantom; do not file the third ticket.

## 5. Work breakdown (writer executes in this order)

1. **`PreparedArtifactWriter` extraction** — new file `swarm-do/py/swarm_do/pipeline/prepared_artifact_writer.py`. Migrate `prepare_plan_run` (`prepare.py:619-913`) to write through it. ~5 days. Anchor test: `swarm-do/py/swarm_do/pipeline/tests/test_prepared_artifact_writer.py` covers (a) round-trip prepare, (b) base bump preserves `prepared_plan_sha`, (c) atomic rollback on simulated mid-write failure.
2. **`swarm prepare refresh-base` (plan section 3.4 Layer A)** — new CLI in `prepare.py` or new module. ~3 days. Calls `PreparedArtifactWriter.begin()` -> `update_git_base_sha()` -> `commit()`. Post-condition assertion: `check_stale(payload, repo_root) is None`. Backup file `.bak-before-refresh-base-<utc-iso>` co-located with artifact.
3. **section 8.9 fence test (promoted to P0)** — `swarm-do/py/swarm_do/pipeline/tests/test_prepared_artifact_writer_seam.py`. Greps `swarm-do/py/swarm_do/pipeline/*.py` for `git_base_sha` assignments outside `prepared_artifact_writer.py` and `prepare.py:619-913` (the prepare-time emit). Fails the build if a new writer appears. ~0.5 days.
4. **Worktree drift classifier (plan section 2.3)** — modify `execution_worktree.py:859-874` (`_validate_existing_manifest`) and add `_classify_manifest_drift` returning the four-state enum; auto-rebuild on `BASE_DRIFT_SAFE`. ~2 days. Anchor tests in `tests/test_execution_worktree.py` per plan section 2.4.
5. **`swarm phases doctor`** — coordinator over `check_stale`, `_verify_dispatch_sidecars`, `_classify_manifest_drift`, lease scan. Read-only. ~3 days.
6. **`swarm phases reset --hard` field-coverage audit (section 8.8)** — extend `_reset_phase_to_pending` to clear the missing fields from `/tmp/reset-phase2.py`. ~1 day. Capture `/tmp/reset-phase2.py`'s exact field set as a fixture before deleting the script.
7. **`swarm worktrees reset/status`** — straightforward CLI shells over existing functions in `execution_worktree.py` (cleanup + manifest read). ~2 days.
8. **`swarm phases redo`** — orchestrator over (4)+(5)+(6)+pump. ~1 day.
9. **`/swarmdaddy:status`, `/swarmdaddy:redo`, `/swarmdaddy:repump`** — Claude plugin commands under `swarm-do/commands/`. ~2 days total.
10. **Diagnostic message uplift (plan section 3.4 Layer C, section 8.10)** — name conflicting fields, recommend `swarm` command. ~1 day.
11. **Tier-A/B/C taxonomy in CONTRIBUTING + audit pass over section 8 backlog** — naming/docs only, no code changes required for the taxonomy itself. ~1 day.
12. **`/tmp` script retirement** (plan section 3a) — capture fixtures, delete scripts, update investigation note. ~0.5 days. Must happen *after* (2) and (6) ship and have CI passing.

**Total: ~3 weeks of focused work for one engineer**, sequenced so the writer is never blocked and each step has a regression test that fails on `main` and passes after.

Files touched (primary): `prepare.py`, `execution_worktree.py`, `phase_sessions.py` (only `_reset_phase_to_pending`), new `prepared_artifact_writer.py`, new `phase_doctor.py`, new CLI subcommands in `cli.py`, new `commands/*.md` under `swarm-do/commands/`.

Files **not** touched: `phase_pump.py` (its callsites already work; the validators it relies on get stronger underneath), `run_state.py` (event log is correct as-is), `worktree_baseline.py`, `phase_attempts.py`, `phase_recovery.py`.

## 6. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| `PreparedArtifactWriter` migration breaks `prepare_plan_run` round-trip | Medium | Migrate behind a feature flag; run full test suite before flipping; keep old code path for one release. |
| `BASE_DRIFT_SAFE` misclassifies "branch unexpectedly clean because user already rebased" -> silent rebuild loses the rebase | Low | The `git rev-list <base>..<execution>` check (plan section 2.3) catches this — if user rebased, branch is ahead, classifier returns `BASE_DRIFT_UNSAFE`. Verified by reading the plan's safety check; correct as stated. |
| section 8.9 fence test fails on legitimate uses we haven't enumerated | Medium | Run the grep manually first, document every legitimate writer, only then make the test enforcing. |
| `phases doctor` JSON output schema becomes a public contract that's hard to evolve | Medium | Version the output (`schema_version: 1`); reuse the run_events schema validation pattern (`run_state.py:72`). |
| Operators continue to write `/tmp` scripts because the sanctioned commands miss a use case | Low (after section 8.8 audit) | Plan's CONTRIBUTING.md rule + CI lint (section 8.12) — sufficient. The ones I read (`/tmp/refresh-git-base.py`, `/tmp/reset-phase2.py`) are both covered by the new CLI surface. |

## 7. Open questions (unresolved)

- **Q1.** Does anything else write `git_base_sha` into `prepared_plan.v1.json` outside `prepare.py`? Answered "no in-tree" by my grep, but the section 8.9 fence test is the durable answer. Worth running the grep before merging the plan.
- **Q2.** Does `inspect.v1.json` (`prepare.py:669, 805`) contain a `git_base_sha` field that the refresh primitive needs to update? Plan section 3.4.2 says "verify in implementation." Quick grep answer: `inspect_payload` is built around L800-805 and I did not see `git_base_sha` there in the prepare-time loop, but I did not exhaustively read `inspect_payload`'s shape. The writer should assert this on first call.

These are confidence-trimmers, not blockers. The plan's "Verify in implementation" notes already absorb both.

## 8. Sources

- `swarm-do/py/swarm_do/pipeline/prepare.py:668` — `prepared.md` filename emit.
- `swarm-do/py/swarm_do/pipeline/prepare.py:676` — `prepared_sha` is hash of canonical plan markdown, not JSON artifact.
- `swarm-do/py/swarm_do/pipeline/prepare.py:813, 758` — only two in-tree writers of `git_base_sha`.
- `swarm-do/py/swarm_do/pipeline/prepare.py:1241-1330` — `_verify_dispatch_sidecars` + `_verify_hashed_sidecar` + `_read_json_object`.
- `swarm-do/py/swarm_do/pipeline/prepare.py:1462-1492` — atomic write idiom.
- `swarm-do/py/swarm_do/pipeline/prepare.py:2012-2090` — `check_stale`, four drift surfaces.
- `swarm-do/py/swarm_do/pipeline/execution_worktree.py:169-208` — `materialize_run_execution_worktree`.
- `swarm-do/py/swarm_do/pipeline/execution_worktree.py:782-788` — `_create_run_worktree`.
- `swarm-do/py/swarm_do/pipeline/execution_worktree.py:821-856` — `_manifest_payload`.
- `swarm-do/py/swarm_do/pipeline/execution_worktree.py:859-874` — `_validate_existing_manifest` (the Tier-C-by-default site).
- `swarm-do/py/swarm_do/pipeline/execution_worktree.py:1155-1182` — schema-validated manifest load.
- `swarm-do/py/swarm_do/pipeline/phase_sessions.py:240, 1252-1253` — `prepared_plan_sha` is sourced from prepared artifact (markdown SHA), copied; mismatch raises only on real divergence.
- `swarm-do/py/swarm_do/pipeline/phase_sessions.py:1186-1224` — `_load_accepted_prepared` calls `check_stale` + `_verify_sidecar_hashes` on every claim.
- `swarm-do/py/swarm_do/pipeline/phase_sessions.py:1331-1343` — `_reset_phase_to_pending` clears 11 fields.
- `swarm-do/py/swarm_do/pipeline/phase_pump.py:55-250` — `pump_phases` body; calls `claim_next_phase` (L123) which already runs the validator.
- `swarm-do/py/swarm_do/pipeline/run_state.py:57-78, 176` — append-only event log + atomic write idiom.

---

## 9. Three-bucket verdict

### Ship the plan as-is
- **section 2 — worktree drift classifier** (Bug 1). Correct shape. The four-state enum is right. The `git rev-list <base>..<execution>` safety check is the right load-bearing primitive. The `RunExecutionWorktreeRebuildRequired` exception ferrying a `needs_input` payload is the right hand-off to the slash UX.
- **section 3.4 Layer A — `swarm prepare refresh-base`** (with amendment A1: drop the prepared_plan_sha rewrite). The shape is correct. Whole-run atomicity, backup, recompute descriptor.sha, post-condition assertion via `check_stale`. Correct.
- **section 3.4 Layer C — diagnostic error messages.** Trivially correct.
- **section 3a — /tmp script retirement.** Correct. Delete-after-replace, capture fixtures, document policy.
- **section 4 — Tier-A/B/C taxonomy.** Correct as a naming contribution. Do not promote to ABCs.
- **section 6 — CLI surface.** Correct. `phases doctor` as the keystone is right.
- **section 7 — slash command UX.** Correct.
- **sections 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.10, 8.11a (with amendment A1), 8.12, 8.13.** All real fixes, no better answer available.
- **section 9 test gap.** All three named tests are correct; the fourth fence test should be promoted to P0 (see below).

### Ship with refactor co-shipped
- **section 8.9 (`prepare refresh-base` upstream guard).** Promote from hardening backlog to P0 child of the recovery-UX epic. Co-ship the `PreparedArtifactWriter` extraction (~1 week). The fence test in section 9 only has teeth if there is one writer to fence around.
- **section 3.4.2 — other locations of `git_base_sha`.** The list is right, but the operation that maintains them should be a method on `PreparedArtifactWriter`, not a checklist re-implemented per CLI subcommand.

### Defer the plan, refactor first
- **None.** No part of this plan is harder to land because it ships before a bigger refactor; no part is locked in by shipping it. The "self-referencing prepared_plan_sha" stream is the only place that locks in fragile shape, and amendment A1 deletes that stream entirely rather than building around it.

---

## Confidence: HIGH (~85%)
## Status: COMPLETE
