# §12 Open Architectural Question — SQLite vs. JSON-Files-with-Validators

**Date:** 2026-05-01
**Author:** follow-on research (parent plan §12)
**Question:** Should SwarmDaddy's run-state move from JSON-files-with-validators onto SQLite, and if so when?
**Stance:** Single recommendation, with an explicit trigger condition. Not a menu.
**Status:** Research → Recommendation. Not yet a beads epic.

---

## TL;DR

**Yes — but stage it. Not now, not never. Not big-bang.**

1. **Ship the parent plan first as written** (§1–§11 of `swarmdaddy-recovery-ux-and-drift-hardening-plan.md`). `PreparedArtifactWriter` is required either way; it becomes the migration seam if we go to SQLite, or the durable JSON owner if we don't. **Nothing in §12 changes the §1–§11 work.**
2. **Adopt SQLite for run-state incrementally, starting with the worktree manifest.** Worktree manifest first (smallest blast radius, highest pain — it's the entry point for Bug 1). Then per-work-unit sidecars + prepared plan envelope. Then phase sessions. Five total tables across two databases (repo-visible + user-machine), not one giant schema. ~6–8 weeks of focused work spread over 2–3 quarters.
3. **Some files stay JSON forever.** `run_events.jsonl` (append-only audit log), `prepared.md` (markdown derivative), and config files do not migrate. SQLite is not a goal; it's a tool for the *coupled-mutation* surfaces.
4. **The trigger that promotes this from "P3 follow-on epic" to "P1 next-quarter work" is bug-class telemetry from the parent plan's recovery-UX surface.** If we keep finding new flavors of cross-file drift after `PreparedArtifactWriter` ships, the migration is justified. If we don't, it's YAGNI.

The architecture-assessment is right that *this plan does not need SQLite*. The research memo is right that *the durable foundation does*. Both can be true, and the sequencing falls out naturally.

---

## 1. Why the original two-agent split is partly false

The architecture-assessment and the research memo disagree about SQLite. Read carefully, they actually disagree about **scope and timing**, not about the destination.

| | Architecture-assessment | Research memo |
|---|---|---|
| Does the parent plan need SQLite to ship? | No — `PreparedArtifactWriter` is enough. | No — incremental path runs alongside the plan. |
| Is SQLite the right long-term shape? | Not addressed; the assessment only argues against doing it *now* as part of this plan. | Yes — Dagster/Prefect local mode pattern. |
| Does anything in the plan get harder if SQLite ships later? | No. | No. |
| Is there a coupled-mutation bug class beyond Bug 2? | Acknowledges `git_base_sha` lives in 5+ places — same coupling pattern. | Names it as the central pain. |

**Where they actually disagree:** the assessment treats "kilobytes of state, append-mostly, run-scoped" as evidence the file shape is fine. The memo treats *the same facts* as evidence SQLite is cheap (small DB, embedded, no scaling concern). Neither side is wrong about the facts; they're weighing different costs.

The unstated cost the assessment lands on: **migration churn against existing tests and the "I can `cat` a run's state to debug it" affordance.** Both real, both well-mitigated by an incremental path that the assessment doesn't address because it was answering a different question (should *this plan* defer for a refactor — no).

So the synthesis is straightforward: ship the plan, then revisit. The §12 work is real, just sequenced after.

---

## 2. SQLite is already in this codebase — context the parent debate missed

The parent debate framed SQLite as a net-new dependency. It is not. Within this same marketplace today:

- `tech-radar/scripts/tech_radar/db.py` (~470 LoC) — full SQLite via `sqlite_utils`, with WAL mode, FTS5, schema migrations. The operator-facing pattern is `sqlite3 ~/.tech-radar/radar.db` — the "I can debug the state from a shell" affordance is preserved.
- `swarm-do/py/swarm_do/telemetry/` — already SQLite-backed for telemetry ledgers. The same `swarm-do` package the plan covers.
- `swarm-do/py/swarm_do/pipeline/mem_prime.py:6` — `import sqlite3` directly. SwarmDaddy's pipeline already reads SQLite (claude-mem store) as part of phase prep.
- `swarm-do/py/swarm_do/pipeline/validation.py:148` — `MEM_PRIME_ADAPTERS = {"dispatch_file", "local_sqlite"}`. SQLite is already an adapter the pipeline knows how to dispatch through.

The cost of "do we adopt SQLite" was already paid. Each new SQLite surface within `swarm-do` is N+1 against an existing dependency, not 0+1 against an empty contract. This materially changes the cost calculus the architecture-assessment used.

It also means the team has a worked example: `sqlite_utils.Database(path)` + `PRAGMA journal_mode=WAL` + `ensure_schema()` is the local idiom. Anyone reading `tech-radar/scripts/tech_radar/db.py` can copy the pattern in a day.

---

## 3. What problem(s) does SQLite actually solve here?

The parent plan's bug surface clusters into four pain shapes. SQLite is a clean answer to two of them, a partial answer to one, and a non-answer to the fourth.

### 3.1 Pain A — Multi-file atomicity (SQLite eliminates)

Today: §3.4.0 of the parent plan documents a hand-rolled write-ahead log — snapshot → stage → commit → verify → rollback across N files. This is the largest piece of failure-mode code in `PreparedArtifactWriter` and gets unit tests parametrized over every phase failing (§3.5 Test 4).

With SQLite: `BEGIN IMMEDIATE; UPDATE prepared_plan SET git_base_sha = ?; UPDATE work_units SET artifact_json = ? WHERE phase_id = ?; COMMIT;` — atomic by the engine, no rollback code, no stage/commit/verify ladder, no `.bak-` files cluttering disk.

This is the highest-leverage single win. The atomicity recipe is correct for the file-based world; it's also ~150 LoC of failure-mode code that doesn't need to exist if the storage primitive is transactional. **POSIX `rename` is per-file. SQLite is per-transaction. The mismatch between what we need (atomic across N files) and what the filesystem gives us (atomic per file) is the structural reason this code exists.**

### 3.2 Pain B — Coupled-invariant ownership (SQLite eliminates the *class*; `PreparedArtifactWriter` retires the current instance)

Today: `git_base_sha` is denormalized into 5+ places (top-level prepared plan, every embedded `work_unit_artifacts.<phase>.artifact`, every sidecar file, worktree manifest, possibly inspect.v1.json). The parent plan's §8.9 fence test prevents one specific re-emergence of out-of-tree writers for `git_base_sha`. But the *class* of bug — coupled fields drifting because one writer skipped a sibling — is open-ended. The next coupling that emerges (e.g., `prepared_plan_sha` if the markdown emit path forks, `branch` if execution branch naming evolves, `source_plan_sha` if plan content gets mutated mid-run) needs its own writer + its own fence test.

With SQLite: foreign keys + CHECK constraints encode the coupling at the schema level. If `prepared_plans.git_base_sha` is the only column for that field, there *cannot* be a denormalized copy to drift from. Schema migration becomes the ceremony that adds new couplings; the existence of the `PreparedArtifactWriter` pattern means a writer-per-coupling is ceremony you don't have to repeat.

This is the strategic argument. `PreparedArtifactWriter` is correct *for one invariant.* The question is whether you build `PreparedArtifactWriter`, then `PhaseSessionWriter`, then `WorktreeManifestWriter`, then `InspectArtifactWriter` — or you spend the same effort once on a schema. Three writers in, the schema is cheaper.

### 3.3 Pain C — Drift detection / recovery surface (SQLite is partial — schema helps; recovery UX is still recovery UX)

Today: four hand-rolled `check_stale` surfaces, four validators that need to stay coherent, error messages that read like mid-stack tracebacks unless explicitly improved (§8.6, §8.10).

With SQLite: schema constraints catch some failures earlier (the *write* fails, not the *read*). But the user-facing recovery UX — `phases doctor`, `phases redo`, the `AskUserQuestion` interactive UI — is needed regardless. SQLite reduces the validator footprint from "JSON-Schema + dict equality + per-field comparison" to "row equality + FK enforcement"; it does not retire the doctor command. The plan's §6 + §7 work ships unchanged.

### 3.4 Pain D — `/tmp/*.py` ad-hoc surgery (SQLite weakly helps; sanctioned commands are the actual fix)

Today: operators reach for `/tmp/refresh-git-base.py` because there's no sanctioned `swarm` command. The parent plan retires this with `swarm prepare refresh-base` + the `/swarmdaddy:redo` slash command, regardless of storage.

With SQLite: the *failure mode* changes — operators would reach for `sqlite3 state.db` instead of `vim prepared_plan.v1.json`. That's better in some ways (transactional, queryable) and worse in others (no schema validation on raw SQL writes — SQLite CHECK constraints help but are not airtight). **The actual fix is sanctioned recovery commands, which the plan already provides. SQLite is a hygiene improvement, not the lever.**

### 3.5 Pain E — Run-state aggregation (SQLite eliminates outright)

Today: `phases status`, `phases doctor`, `/swarmdaddy:status` all need to assemble a coherent picture from 5+ files across 2 roots. Each command ends up open-coding the join.

With SQLite: `SELECT * FROM runs r JOIN phases p ON ... JOIN worktrees w ON ... WHERE r.id = ?` returns the whole run in one round-trip. `phases status --json` is a query, not an assembler.

This is the smallest pain in scope (the existing assemblers work fine), but the largest pain in *future cost* — every new doctor probe, every new TUI panel, every new audit query writes new JSON-walking code today and a new query tomorrow.

---

## 4. What SQLite does NOT solve

To prevent scope creep:

- **Self-referencing hashes.** The architecture-assessment confirmed this is a phantom problem: `prepared_plan_sha` hashes `prepared.md`, not the JSON envelope. SQLite would not have prevented the misunderstanding that motivated `/tmp/refresh-git-base.py`'s breakage; clearer documentation and the `PreparedArtifactWriter` seam would.
- **Worktree-vs-source git drift.** The Bug 1 fix (`_classify_manifest_drift`, auto-rebuild on `BASE_DRIFT_SAFE`) is logic, not storage. The manifest table replaces the JSON file, but the classifier code is identical. Worktrees themselves are git state; SQLite cannot make `git rev-list <base>..<execution>` go away.
- **Recovery UX.** `phases doctor`, `/swarmdaddy:redo`, the slash UI — all unchanged.
- **The `/tmp` script habit.** Sanctioned commands are the fix. SQLite makes ad-hoc surgery slightly more structured (transactions, schema) but does not retire the habit on its own.
- **JSON-Schema validation of prepared artifacts on the wire.** The artifact-as-bytes still has a schema; pydantic v2 (or attrs+cattrs) replaces hand-rolled validators with declarative ones, but that's an orthogonal adoption — same value with or without SQLite.

If the migration sells itself as solving Pain A and Pain B (and incidentally Pain E), it pays for itself. If it sells itself as solving everything, it loses.

---

## 5. The five-table sketch

This is what migration *looks like*, not a final schema. Two databases reflect the existing two-root constraint (`<repo>/data/runs/` is repo-visible artifacts under git; `~/.local/share/swarmdaddy/` is user-machine state). Splitting the database respects the existing boundary; collapsing into one violates it.

### Database 1: `<repo>/data/runs/<run-id>/state.db` (repo-visible)

```sql
-- prepared plan envelope (replaces prepared_plan.v1.json's structured rows;
-- prepared.md stays as a sibling file because it's the markdown derivative)
CREATE TABLE prepared_plans (
    run_id          TEXT PRIMARY KEY,
    schema_version  INTEGER NOT NULL DEFAULT 1,
    source_plan_sha TEXT    NOT NULL,
    prepared_plan_sha TEXT  NOT NULL,         -- SHA of prepared.md, kept consistent
    git_base_ref    TEXT    NOT NULL,
    git_base_sha    TEXT    NOT NULL,         -- single source of truth for base
    accepted_at     TEXT,                     -- ISO8601, null until accept
    created_at      TEXT    NOT NULL,
    plan_envelope_json TEXT NOT NULL          -- residual fields (migration cushion)
);

-- per-work-unit (replaces data/runs/<id>/work_units/*.json)
CREATE TABLE work_units (
    run_id          TEXT NOT NULL,
    phase_id        TEXT NOT NULL,
    idx             INTEGER NOT NULL,
    artifact_json   TEXT NOT NULL,            -- full pydantic-validated artifact
    artifact_sha    TEXT NOT NULL,            -- generated/maintained by one writer
    plan_context_sha TEXT NOT NULL,
    cache_key       TEXT NOT NULL,
    PRIMARY KEY (run_id, phase_id),
    FOREIGN KEY (run_id) REFERENCES prepared_plans(run_id) ON DELETE CASCADE,
    CHECK (artifact_sha = artifact_sha)       -- placeholder; real CHECK lives in app
);

-- inspect artifacts (replaces data/runs/<id>/inspect/*.json)
CREATE TABLE inspect_artifacts (
    run_id          TEXT NOT NULL,
    inspect_id      TEXT NOT NULL,
    artifact_json   TEXT NOT NULL,
    artifact_sha    TEXT NOT NULL,
    PRIMARY KEY (run_id, inspect_id),
    FOREIGN KEY (run_id) REFERENCES prepared_plans(run_id) ON DELETE CASCADE
);
```

### Database 2: `~/.local/share/swarmdaddy/runs/<run-id>/state.db` (user-machine)

```sql
-- phase lifecycle (replaces phase_sessions.v1.json)
CREATE TABLE phase_sessions (
    run_id          TEXT NOT NULL,
    phase_id        TEXT NOT NULL,
    status          TEXT NOT NULL,            -- pending|in_progress|failed|...
    attempt         INTEGER NOT NULL DEFAULT 0,
    lease_owner     TEXT,
    lease_expires_at TEXT,
    started_at      TEXT,
    last_error      TEXT,
    last_failure_kind TEXT,
    next_retry_at   TEXT,
    blocked_reason  TEXT,
    blocked_at      TEXT,
    retry_policy_decision TEXT,
    evidence_path   TEXT,
    prepared_plan_sha TEXT NOT NULL,          -- copy of prepared.md SHA at acceptance
    session_json    TEXT NOT NULL,            -- residual fields (migration cushion)
    PRIMARY KEY (run_id, phase_id),
    CHECK (status IN ('pending','in_progress','failed','blocked','needs_input',
                      'retry_pending','retry_scheduled','complete'))
);

-- worktree manifest (replaces worktrees/<run-id>/manifest.json)
CREATE TABLE worktrees (
    run_id          TEXT PRIMARY KEY,
    path            TEXT NOT NULL,
    branch          TEXT NOT NULL,
    base_sha        TEXT NOT NULL,
    adoption_state  TEXT NOT NULL DEFAULT 'unadopted',
    source_repo_root TEXT NOT NULL,
    safe_run_id     TEXT NOT NULL,
    project_subdir  TEXT,
    schema_version  INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    CHECK (adoption_state IN ('unadopted','adopted','archived'))
);
```

### What does NOT migrate

- `~/.local/share/swarmdaddy/runs/<run-id>/telemetry/run_events.jsonl` — append-only audit log. JSONL is the right shape; SQLite would buy nothing and lose the "tail -f" affordance and the single-writer-multiple-reader discipline that JSONL enforces by file shape. Keep as JSONL.
- `data/runs/<run-id>/prepared.md` — markdown derivative consumed by humans and agents. Stays as a file. Its SHA lives in the `prepared_plans` table.
- Config files (`config.toml`, etc.) — out of scope.

### Cross-database boundaries

The two databases are independent. Cross-database invariants (e.g., `phase_sessions.prepared_plan_sha` matches `prepared_plans.prepared_plan_sha`) are checked by application code, not by FK — same shape as today, just with the values living in rows instead of file fields. The boundary is the same boundary `_repo_visible_run_dir` enforces today (see `prepare.py:1416` per the architecture assessment).

---

## 6. The incremental path (refined from the research memo)

Seven steps, each shippable, each reversible until the last. Spread over 2–3 quarters at normal cadence, ~6–8 weeks of focused engineering at compressed cadence.

Sequenced for **maximum-pain-first** so each step proves itself before the next. Recovery-UX from the parent plan ships in parallel with — or before — Step 1.

### Step 0 — Parent plan ships (§1–§11). [Pre-requisite, ~3 weeks]

Bug 1 + Bug 2 fixed. `PreparedArtifactWriter` extracted. Recovery-UX CLI + slash commands shipped. Telemetry on the recovery-UX surface starts collecting bug-class data (which probes find issues, how often, what shape).

**Decision gate:** after 1–2 quarters of recovery-UX in operation, look at the bug rate and bug shape. If the bug rate is dominated by *new* coupled-mutation drift the `PreparedArtifactWriter` doesn't cover, proceed to Step 1. If bugs cluster elsewhere (UX, validation messaging, lease management), pause this epic — SQLite is YAGNI.

### Step 1 — Worktree manifest only. [~1 week, 1 file, 1 schema]

Smallest blast radius, highest pain (Bug 1 entry point). Migrate `manifest.json` → `worktrees` table in `~/.local/share/swarmdaddy/runs/<id>/state.db`. `_validate_existing_manifest` becomes a SELECT + CHECK; `_classify_manifest_drift` (from parent plan §2) operates on a row, not a dict.

**Acceptance signal:** Bug 1's regression tests pass against the SQLite-backed implementation. The hand-rolled atomic-write idiom in `execution_worktree.py:1392` retires for this surface — `BEGIN; UPDATE worktrees SET base_sha = ? WHERE run_id = ?; COMMIT;` replaces `_atomic_write_bytes`.

### Step 2 — Per-work-unit sidecars + prepared plan envelope. [~2 weeks, ~3 files affected]

The Bug 2 surface. `data/runs/<run-id>/work_units/*.json` and `prepared_plan.v1.json` envelope migrate into the repo-visible `state.db`. `PreparedArtifactWriter` becomes a façade over a single SQL transaction; the multi-file atomicity recipe (parent plan §3.4.0) retires.

**Acceptance signal:** the §3.4.0 unit tests parametrized over every failure point are deleted; replaced by a single "BEGIN/ROLLBACK on exception" test. The `.bak-before-refresh-base-<utc-iso>` files retire — `BEGIN; ... ROLLBACK;` is the audit trail. The §8.9 fence test transforms from "no other module writes git_base_sha" (greppable contract) into "the column is private to one DAO class" (compile-time-ish contract — schema scope + module imports).

### Step 3 — Phase sessions. [~1.5 weeks]

`phase_sessions.v1.json` → `phase_sessions` table in user-machine `state.db`. `_reset_phase_to_pending`'s field-coverage problem (parent plan §8.8) becomes "all columns set to their defaults via UPDATE" — the field set is enumerated by the schema, not by hand, so the next operator who adds a phase-state field cannot accidentally leave it out of reset.

**Acceptance signal:** the field-coverage audit test for `_reset_phase_to_pending` simplifies to "every column with a default has a default applied on reset" — a property test, not a fixture-comparison test.

### Step 4 — Inspect artifacts (if they exist on the migrated path). [~0.5 week]

Per parent plan §3.4.2 open question Q2: confirm whether `inspect.v1.json` carries `git_base_sha`. If yes, migrate alongside Step 2. If no, this step is a no-op.

### Step 5 — pydantic v2 schemas as the row shape. [~1.5 weeks, can parallelize with Steps 1–4]

Replace hand-rolled JSON validators with pydantic v2 models. `model_validate_json` for read, `model_dump_json` for write. The validator pipeline (`check_stale`, `_verify_dispatch_sidecars`, etc.) becomes "construct the model and let pydantic raise" + "compare model to expected fields."

This step is **independently valuable** even without SQLite. It can ship before Step 1 (replacing JSON-validators-for-files with pydantic-models-for-files) and the same models then carry into the SQL migration. **If §12 stalls at the decision gate after Step 0, ship Step 5 anyway** — pydantic v2 is the better validator regardless.

### Step 6 — `phases status` + `phases doctor` query consolidation. [~1 week]

The doctor coordinator (parent plan §6) shipped against JSON files in Step 0. After Steps 1–4, rewrite the probes to use SQL queries. The probe-error-isolation acceptance criterion (§6) is preserved by per-probe try/except harnesses around the queries.

**Acceptance signal:** `swarm phases doctor --json` returns a single `SELECT ... JOIN ...` round-trip instead of N file reads. Cold-start cost drops from "open and parse N JSON files" to "open one SQLite handle + run one query."

### Step 7 — Schema migrations + `swarm rollout repair` / `swarm rollout abandon`. [~1 week]

Land Alembic (or a hand-rolled `schema_versions` table — Alembic is overkill until there's a second migration) for SQLite schema evolution. Add `swarm rollout repair` / `swarm rollout abandon` as transactional verbs over the new schema, modeled on `jj op restore` / `jj op abandon` from the research memo. These are the verbs that retire the *next* class of `/tmp` script.

**Acceptance signal:** introducing a new column to `phase_sessions` ships as a migration script + one PR, not as a hunt for every JSON reader that touched the field.

---

## 7. Cost / value table (revised, with already-paid-cost factored in)

The architecture-assessment cited "4–6 weeks" for SQLite migration; the research memo cited "~2 weeks of focused work, Dagster's ~800 LoC blueprint." Both are right for different scopes. The breakdown:

| Step | Effort | Bug-class retired | Reversible? |
|---|---|---|---|
| 0 — Parent plan | ~3 weeks | Multi-file atomicity (Bug 2 instance), worktree drift hard-abort (Bug 1) | n/a |
| 1 — Worktree manifest | ~1 week | Atomic-write boilerplate for one file | Yes (revert PR; old code path stays valid) |
| 2 — Sidecars + envelope | ~2 weeks | Multi-file atomicity (the *class*), §3.4.0 recipe retires | Yes, but expensive (test fixtures churn) |
| 3 — Phase sessions | ~1.5 weeks | `_reset_phase_to_pending` field-coverage class | Yes |
| 4 — Inspect artifacts | ~0.5 week | Same class as Step 2 (if applicable) | Yes |
| 5 — pydantic v2 | ~1.5 weeks | Hand-rolled JSON-Schema validator drift | Yes (independently shippable) |
| 6 — Query consolidation | ~1 week | Cold-start parse cost; ad-hoc joins | Yes |
| 7 — Migrations + rollout verbs | ~1 week | Schema-evolution friction | Yes |
| **Subtotal Steps 1–7** | **~8.5 weeks** | | |
| **Through Step 4 (the high-value cliff)** | **~4 weeks** | | |

The architecture-assessment's "4–6 weeks" estimate matches **Steps 1–4** — i.e., the genuinely high-value subset. The research memo's "~2 weeks" matches **Step 2 alone** — the keystone migration. Both estimates are right for what they describe.

**The high-value cliff is at end of Step 4 (~4 weeks from migration start).** After that, the §3.4.0 multi-file atomicity recipe is dead code, the §8.9 fence test is enforced by schema scope, the cold-start parse cost is half what it was, and `phases doctor` is a query. Steps 5–7 are nice-to-haves; Step 5 (pydantic) is independently valuable even if SQLite stalls.

---

## 8. Library choice (2026-grade)

The research memo recommends `sqlite3` stdlib + `pydantic` v2. The local example (`tech-radar`) uses `sqlite_utils` (simonw). Trade-offs:

| Library | Pro | Con | Verdict |
|---|---|---|---|
| `sqlite3` (stdlib) | No new dep; what `mem_prime.py` already uses | Verbose schema/migration code; no upsert helpers | **Baseline. Use directly for narrow, hot paths.** |
| `sqlite_utils` (Simon Willison) | Already in use by `tech-radar`; fast schema iteration; clean upsert API; FTS5 helpers | New dep for swarm-do (existing in tech-radar but not swarm-do) | **Recommended for schema setup + ad-hoc operator queries.** Same pattern as the existing tech-radar code. |
| `pydantic` v2 | Declarative validation, fast Rust core, JSON dump/load, IDE support | Heavier cold-start than attrs+cattrs; non-trivial dep | **Recommended for row shape + validator replacement.** The cold-start hit is real but pays back across 6+ JSON validator surfaces. |
| `attrs` + `cattrs` | Lighter cold-start; mature | Less ergonomic for nested JSON-with-validators | **Fallback only** if pydantic cold-start measurably hurts CLI startup. Benchmark first; the architecture-assessment's "fast cold-start budget" concern is real and worth a 5-minute measurement before committing. |
| `SQLAlchemy` Core | Mature, query builder | Overweight for this scale | **Skip.** Out of proportion to needs. |
| `Alembic` | Migration framework | Skip until Step 7 — overkill until there's a second schema version | **Defer to Step 7.** |
| `pluggy` | Validator-tier plugin pattern from research memo | Real value only if validator suite grows past ~6 surfaces with extension points | **Skip.** Use a flat list of validator functions and a tier enum. The pluggy adoption is research memo's tier-2 recommendation; the assessment's "naming contribution, not typing contribution" critique applies here too. |

**Recommended stack:** `sqlite_utils` for DAO + schema, `pydantic` v2 for row models + validation, `sqlite3` stdlib for hot paths where `sqlite_utils` overhead matters. This matches the existing `tech-radar` codebase conventions and adds one new dep (`pydantic`) to `swarm-do`. Cold-start budget measurement is a Step 0.5 task.

---

## 9. Counter-arguments (and rebuttals)

**"I want to `cat prepared_plan.v1.json` to debug."** Preserved via `sqlite3 state.db .dump | less` or `sqlite-utils rows state.db prepared_plans` (already used by tech-radar). The affordance changes shape, not capability. Operators learn one new command; in exchange they get `sqlite3 state.db "SELECT phase_id, status, attempt FROM phase_sessions"` — better than hand-walking JSON.

**"Two-root constraint blocks SQLite."** It does not — two databases respect the boundary. The architecture-assessment's verification table cell on this (§3 row Q7) is the weakest part of its case. "SQLite would need two databases or violate the boundary" — yes, two databases. That's fine. The boundary is `<repo>` vs. `~/.local/share/`, not "all state in one place."

**"Test fixtures churn."** Real cost — every test that creates JSON fixtures needs to create SQLite fixtures. Mitigated by: (a) most tests can use an in-memory `:memory:` DB; (b) a small fixture helper (`make_run_state(run_id, ...)` returning a populated DB) replaces the existing JSON-file-tree builders 1-for-1; (c) the migration is incremental, so test churn is per-step, not all at once.

**"What if we never write `/tmp/refresh-git-base.py` again — was the migration worth it?"** This is the right question. The honest answer: if the recovery-UX surface from §1–§11 is enough to retire the `/tmp` script habit AND no new coupled-mutation bugs emerge after `PreparedArtifactWriter` is in place, then yes — SQLite is YAGNI and we should not migrate. **The migration is conditional on the bug-class telemetry showing continuing pain.** This is what the §12.2 "we are not deferring this plan to wait on it" framing already implies; we're just being explicit that the same logic applies in reverse — don't migrate to retire bugs that aren't happening.

**"Event sourcing is the more elegant answer."** Both source agents agree: don't event-source. The hybrid (events table + projected tables in same transaction) is what Dagster does and is cheap once SQLite is in place. The pure event-sourcing model — readers replay the log on every command — is Temporal-grade complexity for no benefit at SwarmDaddy's single-operator scale. Reject.

**"We could just keep adding `XxxWriter` classes."** True for two or three couplings. False for ten. The `PreparedArtifactWriter` pattern scales linearly (one class per coupled-mutation surface, one fence test per class); the schema pattern scales sublinearly (one schema, N tables, FK enforcement is free). The crossover is around 3–4 couplings. We're at 1 today (`git_base_sha`), with `prepared_plan_sha` and `branch` as plausible next entrants. Crossover is plausibly within a year of recovery-UX shipping; that's the trigger condition.

---

## 10. Decision criteria for Step 1 promotion (concrete trigger)

After parent plan ships and recovery-UX has 1–2 quarters of operation, promote §12 from "follow-on epic" to "P1 next-quarter work" if **any** of:

- Two or more new bug reports describing coupled-mutation drift on fields *other than* `git_base_sha` (i.e., the pattern recurs despite `PreparedArtifactWriter`).
- A second `PreparedArtifactWriter`-shaped class is proposed in a PR for a different invariant (the writer-per-coupling tax becomes visible).
- The `phases doctor` cold-start cost measurably exceeds budget (parse-N-JSON-files becomes a UX issue at ~10+ runs in the data dir).
- A user-visible feature requires a cross-run query (e.g., "which runs are stuck on Phase 2 across the project?") that JSON-walking makes painful.
- Test suite parametrization for the §3.4.0 atomicity recipe has grown to be a maintenance burden.

If **none** of these fire after a quarter or two of recovery-UX operation, the migration is YAGNI. Keep `PreparedArtifactWriter` as the JSON-files owner and revisit at a longer horizon (or never).

---

## 11. Recommendation

1. **Ship the parent plan as written.** §1–§11 unchanged. `PreparedArtifactWriter` co-shipped.
2. **File the §12 follow-on epic as P3 today, with the four child issues already named in §12.3** of the parent plan, plus a new explicit child for Step 5 (pydantic v2 adoption — independently shippable).
3. **Add Step 5 (pydantic v2 schemas) as a P2 candidate independently of the SQLite question.** The research memo is right that schema-as-code retires the validator drift class regardless of storage. This is the cheapest single durability win after the parent plan.
4. **Set the §12 promotion review for ~3–6 months after recovery-UX ships.** Use the Step-1 promotion criteria above as the explicit gate. Tag a beads issue with a target date and the gate criteria so it's not a vague follow-up.
5. **Pre-bake the seam.** When implementing `PreparedArtifactWriter`, structure its public API so a future SQLite implementation is a drop-in (`load() -> dict`, `begin() -> Txn`, `commit()`). The architecture-assessment's sketch already does this; lock that shape in and document it as deliberately migration-friendly. **This is the only §12 work that should bleed into the parent plan PR — and it costs nothing because the assessment's API was already designed this way.**
6. **Pick the library stack now, even if not used yet.** Document the recommendation (`sqlite_utils` + `pydantic` v2) in the §12 epic so the next operator does not re-litigate. Run a 30-minute cold-start benchmark before locking pydantic v2 in.

The durable foundation is SQLite for run-state, with append-only logs as JSONL, with markdown derivatives as files. We can ship the right foundation in stages without disrupting what's working.

---

## 12. References

- Parent plan: [`swarmdaddy-recovery-ux-and-drift-hardening-plan.md`](./swarmdaddy-recovery-ux-and-drift-hardening-plan.md) §12.
- Architecture assessment: [`architecture-assessment-2026-05-01.md`](./architecture-assessment-2026-05-01.md) §2 verdict + §9 three-bucket breakdown.
- Industry research: [`research-similar-systems-2026-05-01.md`](./research-similar-systems-2026-05-01.md) §F three recommendations.
- Local SQLite precedent (this marketplace): `tech-radar/scripts/tech_radar/db.py` (470 LoC, `sqlite_utils` + WAL + FTS5 pattern).
- Local SQLite precedent (this package): `swarm-do/py/swarm_do/telemetry/` (telemetry ledgers), `swarm-do/py/swarm_do/pipeline/mem_prime.py:6` (`import sqlite3`).
- Dagster blueprint (cited in research memo): `dagster/_core/storage/runs/sqlite/sqlite_run_storage.py` and `..._event_log/sqlite_event_log_storage.py`.
- Prefect 2 local-mode SQLAlchemy + Alembic pattern: `PrefectHQ/prefect/src/prefect/server/database/`.
- jj operation log model: `jj-vcs/jj/lib/src/op_store.rs` (per research memo §C).
