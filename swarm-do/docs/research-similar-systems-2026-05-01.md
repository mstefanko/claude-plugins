# Research Memo: Industry Patterns for SwarmDaddy's State / Drift / Recovery Pain

Date: 2026-05-01
Audience: SwarmDaddy maintainers
Scope: Map SwarmDaddy's eight concrete pains (multi-phase JSON state, self-referencing hashes, drift detection, drift recovery, ad-hoc /tmp surgery, audit-only events, no run aggregate, idempotent retry, worktree manifests) onto how mature workflow engines, build systems, and git tooling solve them — and recommend what to adopt.

Constraint: SwarmDaddy ships as a Claude Code plugin. Single operator, single machine, no daemon, fast cold-start, durable to crashes. Anything requiring a server is out.

---

## A. Workflow engines

**Temporal.** Stores execution as a strictly ordered event history (`History` table in MySQL/Postgres/Cassandra) — current state is always a deterministic projection of replayed events. Workers re-execute workflow code from history on every retry; "drift between attempts" is impossible by construction because the workflow code is the only source of decisions and side effects re-derive from events. Recovery is `reset` (rewind history to a chosen event) or `signal`/`update` (apply an external transition). Core requires the Temporal server (Go) — embedding is not realistic. Reference: `service/history/workflow/mutable_state_impl.go` and the `WorkflowReset` API.

**Airflow.** State lives in a Postgres metadata DB; DAG runs and TaskInstances have explicit states (`scheduled`, `queued`, `running`, `success`, `failed`, `up_for_retry`, `up_for_reschedule`). "World changed" is handled crudely — a `clear` operation marks a TI for retry; `mark_success` overrides. Recovery surface is a CLI (`airflow tasks clear`) and the web UI. Requires scheduler + DB + executor running; not embeddable for a CLI tool.

**Argo Workflows.** State is a single CRD object in etcd via Kubernetes API; Argo encodes the entire workflow status (including each node's phase, outputs, hashes of inputs) into one document. Drift handling is naive — if the workflow spec is mutated, the controller treats it as a new generation. Requires Kubernetes; not relevant.

**Dagster.** State stored in `dagster.instance` storage — by default SQLite (`runs.db`, `event_log.db`, `schedule.db`) but pluggable to Postgres. Importantly: **Dagster is dual-store** — it persists structured run rows AND an event log, with run state denormalized from events for fast queries. Optimistic concurrency is on the run row's status. Recovery is `dagster run resume` and `--from-failure`. The asset materialization model handles drift cleanly: every materialization records a `data_version` (content hash of inputs) and downstream assets compare it on the next run — that is exactly SwarmDaddy's drift problem with a working answer. References: `dagster/_core/storage/runs/sqlite/sqlite_run_storage.py`, `dagster/_core/definitions/data_version.py`. **Dagster's local mode is embeddable in spirit** — SQLite-backed instance, pure Python, no daemon required when run as `dagster job execute`.

**Prefect 2.x.** Local mode uses SQLite (`~/.prefect/prefect.db`) via SQLAlchemy + Alembic migrations. State machine is explicit (`Pending → Running → Completed/Failed/Crashed/Cancelled`) with state transition handlers. Drift is mostly punted to user code. Recovery via `prefect flow-run retry`. **Most embeddable model in this list** — Prefect's local SQLite + SQLAlchemy state store is approximately what a SwarmDaddy backing store would look like.

**AWS Step Functions.** Closed-source, server-only, irrelevant for embedding — but the `History` event semantics are worth noting: every state transition is an immutable event, and "redrive" replays from the last failed event using the same input. Same idea as Temporal, simpler API.

**Verdict for A.** Only Dagster and Prefect ship a credible embeddable local-mode (SQLite + Python). Of those, **Dagster's data-version model** maps onto SwarmDaddy's drift problem better than anything else surveyed.

---

## B. Build systems

**Bazel.** Two-layer cache: a content-addressed action cache (CAS) keyed on `(action_command, input_file_hashes, env)`, and an analysis cache keyed on the same plus the `BUILD` file content hash. Drift detection is "did any input hash change" — never self-referencing. Bazel never stores its own hash inside an artifact. The analysis cache file (`server/install_base`) is keyed externally.

**Buck2.** Same pattern, smaller core; uses DICE (incremental computation engine) — every computed value carries the hash of its inputs, and `dice.compute(key)` either returns the cached value or recomputes. Inputs are content-addressed; the value never names itself.

**Nix.** The canonical answer to the self-referencing-hash problem. A `.narinfo` file describes a store path, including the path's own hash — but the hash is computed over the *content of the store path*, NOT over the narinfo file itself. The narinfo is metadata about the path, not part of what's hashed. **This is the key lesson for SwarmDaddy**: separate the *thing being hashed* from the *file recording the hash*. Nix's `nix-store --verify --check-contents` is the canonical drift-recovery flow. Reference: `nix/src/libstore/nar-info.cc`.

**dbt.** `manifest.json` is a build artifact. Each node has a `checksum` field, but the checksum is over the *source SQL file's contents*, not over the manifest entry. The manifest itself is regenerated on every `dbt parse`/`dbt compile` — it's a derived artifact, not a source of truth. State comparison is `dbt build --defer --state path/to/previous-manifest`. Reference: `dbt-core/dbt/contracts/graph/manifest.py`.

**Pants.** Like Buck2, uses an internal incremental engine with content-addressed keys. Cache keys never include themselves.

**Turborepo.** Hash inputs = `(file contents, env vars, dependencies)` → cache key. Output cache is content-addressed, separate from the key.

**Verdict for B.** **Self-referencing content hash is a known anti-pattern across every mature build system.** The fix is universal: split "the thing hashed" from "the file recording the hash". Either (a) hash a *canonical view* of the JSON with the hash field zeroed/excluded (Nix's "self-reference" handling for runtime-patched store paths uses exactly this trick — see `nix/src/libstore/references.cc`), or (b) keep the hash in a sibling sidecar file (`foo.json` + `foo.json.sha256`). Option (b) is dramatically simpler and what dbt, Bazel, and Nix's narinfo all do.

For invalidation cycles: every system above models cache-miss → recompute as a pure function of inputs. The fix for "input changed → key changed → cache miss → re-run" is *not* to make the key stable (that defeats correctness); it's to make the recompute cheap and idempotent.

---

## C. Git tooling with programmatic worktrees

**git absorb / git revise.** Both operate transiently on the working tree without a persistent manifest. They don't have SwarmDaddy's problem because they don't keep state between invocations.

**Jujutsu (jj).** *The* relevant comparison. jj treats every operation as an immutable entry in an **operation log** (`.jj/repo/op_store/`). Every state-changing command (commit, rebase, abandon, restore) appends an `Operation` referencing the previous one and a snapshot of the workspace state. `jj op log` shows the history; `jj op restore <id>` rewinds to any prior operation; `jj op abandon` discards. Crucially, the workspace's view (`.jj/working_copy/`) is a *projection* of the op log + working-copy snapshot — drift between them is detected at every command and auto-reconciled by snapshotting the working copy as a new operation. References: `jj-cli/lib/src/op_store.rs`, `jj-cli/lib/src/operation.rs`. **This model — events are SoT, current state is projected, recovery is `op restore` — is precisely what SwarmDaddy's events-vs-JSON-files split is missing.**

**Gerrit.** Stores change state in NoteDB (refs in the git repo itself: `refs/changes/...` + `refs/meta/...`). Drift between the on-server change object and the pushed commit is reconciled by `git push` semantics — the ref update is the atomic boundary. Recovery is `gerrit set-reviewers`, `gerrit review --abandon`. Not relevant for embedding.

**Phabricator's arc.** Stored a `.arcconfig` and per-revision metadata in the Phab server. Recovery was server-side `arc which` / `arc amend`. Dead project; skip.

**Per-worktree manifest hygiene.** The closest pattern: jj's per-workspace `working_copy_state` file tracks `(tree_id, parent_op_id)` and is invalidated on every `jj` invocation by snapshotting and comparing against HEAD. **The canonical pattern for "branch drifted, manifest stale"** is: don't trust the manifest as source of truth; on every command, snapshot reality (HEAD, tree hash, etc.) and reconcile. The manifest is a cache, not authority.

**Verdict for C.** jj's operation log model is directly applicable to SwarmDaddy. Tier-2 outcome: even without adopting jj, the principle "treat the worktree manifest as a cache, re-derive from `git` reality on every command" eliminates the "manifest stale" failure mode entirely.

---

## D. State storage trade-offs

| Approach | Cost | Eliminates | Fit for SwarmDaddy |
|---|---|---|---|
| **Status quo: JSON + validators** | High maintenance (4 validators today, growing) | — | Already failing |
| **SQLite (stdlib)** | One-time migration; schema thinking; ~500 LoC of DAO | Atomic multi-table writes (`BEGIN; ... COMMIT`); lost-write windows; ad-hoc /tmp surgery (operators run `sqlite3 run.db` instead); validator drift (foreign keys + CHECK constraints replace 4 hand-rolled checkers) | **Excellent.** Stdlib, single file, transactional, queryable, copy-able for snapshots. This is what Dagster and Prefect picked for local mode. |
| **Event-sourced (events SoT, state projected)** | Bigger refactor; need projection rebuild logic; harder to debug ad-hoc | Drift between event log and JSON files (since JSON files no longer exist as SoT); operator surgery (`abandon` an event instead of editing JSON) | **Good fit *combined with* SQLite** — store events in a SQLite table, project state into other tables in the same transaction. This is how jj and Dagster both work. |
| **CRDTs** | Massive complexity (Automerge, Yjs); only valuable for concurrent editors | Multi-writer conflicts | **Overkill.** Single operator, single machine. Skip. |
| **Content-addressed store (git/Nix-style)** | Conceptually heavy; needs garbage collection | Self-referencing hash problem; cache invalidation | **Useful as a sub-pattern**, not a wholesale replacement — store *artifacts* content-addressed in `.swarm-do/cas/` keyed by sha, but keep run state in SQLite. |

**Recommendation for D**: SQLite as the state store, with a small `events` table that acts as an append-only log and a set of projected tables (`runs`, `phases`, `work_units`, `worktrees`) updated in the same transaction as the event insert. This is a hybrid event-sourced + relational model — same one Dagster's `EventLogStorage` + `RunStorage` uses.

---

## E. Python libraries that fit

- **stdlib `sqlite3`** — sufficient. Python 3.12+ ships with WAL support, JSON1, and FTS5. APSW only matters if SwarmDaddy needs the streaming backup API or virtual tables; it doesn't yet.
- **`pydantic` v2** — replaces every hand-rolled JSON validator with declarative schemas. v2's `model_dump_json` and `model_validate_json` are fast (Rust core). Strong fit. `attrs` + `cattrs` is a lighter alternative if pydantic is too heavy for cold-start budget; benchmark before choosing.
- **`transitions`** — lightweight FSM library; would model phase lifecycle (`planning → preparing → executing → reviewing → done`) with explicit `before_*`/`after_*` hooks. Fit, but the value-add over a hand-written `State` enum + dispatch is modest. **Skip unless** the lifecycle grows past ~6 states with non-trivial transitions.
- **`pluggy`** (the pytest hook system) — **strong fit for the validator tier problem**. Each validator becomes a hook impl; the plugin manager lets you register tier-1 (must pass) vs tier-2 (warn-only) policies cleanly. This is exactly what pytest, tox, and datasette use it for.
- **WAL-style command logs (`dbm`, `lmdb`, `rocksdb-py`)** — overkill. SQLite WAL mode (`PRAGMA journal_mode=WAL`) gives you durable, crash-safe, transactional writes with one line of config. LMDB/RocksDB are for write-throughput regimes SwarmDaddy will never see.
- **`alembic`** — pair with SQLite for schema migrations. SwarmDaddy will need this the moment the schema lands and the first user has a stale DB.

---

## F. Verdict — three concrete recommendations

### 1. Highest-leverage adoption: SQLite as the run-state store, with pydantic schemas on top

Migrate the five+ JSON files (prepared plan, per-work-unit sidecars, worktree manifest, phase session log, run event log) into a single `~/.swarm-do/runs/<run-id>/state.db` with schema:

- `runs(id, status, created_at, ...)`
- `phases(run_id, idx, status, started_at, ...)`
- `work_units(run_id, id, status, ...)`
- `worktrees(run_id, path, base_sha, head_sha, adopted, ...)`
- `events(run_id, seq, kind, payload_json, ts)` — append-only

Pydantic models define the row shapes; CRUD goes through a thin DAO. The "refresh git base" operation that currently touches 5 files becomes one `BEGIN IMMEDIATE; UPDATE worktrees ...; UPDATE phases ...; INSERT INTO events ...; COMMIT;` — atomic by construction.

This single change retires:
- Self-referencing hash problem (no more files describing themselves; row + columns)
- 4 independent stale-checkers (replaced by FK + CHECK constraints)
- Multi-file atomicity (one transaction)
- "/tmp/*.py surgery" (operators run `sqlite3 state.db` — a known, stable interface)
- Run-state-aggregate problem (one `SELECT * FROM ... JOIN ...` returns the whole run)
- Idempotent retry (transactions are naturally idempotent if keyed on event seq)

Cost: ~2 weeks of focused work. Reference implementation: Dagster's `SqliteRunStorage` and `SqliteEventLogStorage` are ~800 LoC each and a credible blueprint.

### 2. Pattern to AVOID: full event-sourcing with state-as-pure-projection

It looks attractive (jj, Temporal, Dagster all do it) and the user is already part-way there with the run event log. **Don't do it as a wholesale replacement.** Pure projection requires either (a) replay-on-every-read (slow, complex) or (b) a snapshot-and-checkpoint mechanism (Temporal-grade complexity). For a single-operator local CLI that the user can `cat state.db` in 50ms, the operational cost is not justified. The **hybrid** — events table + projected tables in the same transaction — gets you 90% of the audit/replay value at 10% of the complexity. Adopt the hybrid; reject the purity.

### 3. Incremental refactor path (durability per effort, descending)

1. **Sidecar the self-hash.** Move every `sha256` field out of the JSON it describes into a sibling `.json.sha256` file (or compute on-the-fly from canonical JSON without storing). Day-one win, zero schema thinking. Eliminates the two-pass-write hack and the hash-excluding-self-field branch.
2. **Land SQLite + pydantic for the worktree manifest first.** It's the smallest, most contained piece of state, and it owns the worst pain (drift recovery). One table, ~5 columns, ~150 LoC. Prove the pattern.
3. **Make worktree manifest a cache, not authority.** On every command, snapshot real git state (`git rev-parse HEAD`, `git status --porcelain=v2`) and reconcile against the manifest row. If they disagree and no unadopted writer commits exist, auto-rebuild — don't hard-abort. (jj's pattern.)
4. **Migrate per-work-unit sidecars + phase session log.** Now you have one DB with 3 tables. The "refresh git base" atomic boundary lands here.
5. **Move the run event log into the same DB as an `events` table.** Same transaction as state changes. Now events become a real source-of-truth audit log, not an afterthought.
6. **Replace the four `check_stale` surfaces with one validator pipeline using `pluggy`.** Each validator returns a `(level, message)`; tier-1 fails the run, tier-2 warns. Recovery commands consume the same pipeline.
7. **Add `swarm rollout repair` / `swarm rollout abandon` CLI verbs** modeled on `jj op restore` / `jj op abandon`. They become idempotent SQL transactions; ad-hoc /tmp scripts disappear because the verbs cover their use cases.

After step 4 the "operator drops into /tmp/*.py" pain is dead. After step 7 SwarmDaddy has a recovery UX that resembles jj's, which is the gold standard for local single-operator state recovery.

---

## Citations / references

- Temporal event history: `temporalio/temporal` `service/history/workflow/mutable_state_impl.go`; reset API at `WorkflowResetter`.
- Dagster local SQLite stores: `dagster-io/dagster` `python_modules/dagster/dagster/_core/storage/runs/sqlite/sqlite_run_storage.py` and `..._event_log/sqlite_event_log_storage.py`. Data version: `_core/definitions/data_version.py`.
- Prefect 2 local SQLite: `PrefectHQ/prefect` `src/prefect/server/database/` (Alembic migrations + SQLAlchemy models).
- Nix narinfo separation: `NixOS/nix` `src/libstore/nar-info.cc`; self-reference rewriting at `src/libstore/references.cc`.
- dbt manifest checksum-of-source (not of self): `dbt-labs/dbt-core` `core/dbt/contracts/graph/manifest.py` `FileHash`.
- Bazel action cache key derivation: `bazelbuild/bazel` `src/main/java/com/google/devtools/build/lib/actions/ActionCacheChecker.java`.
- Buck2 DICE: `facebook/buck2` `dice/` crate.
- jj operation log: `jj-vcs/jj` `lib/src/op_store.rs`, `lib/src/operation.rs`; recovery in `cli/src/commands/operation/`.
- Gerrit NoteDB: `GerritCodeReview/gerrit` `java/com/google/gerrit/server/notedb/`.
- pluggy hook patterns: pytest plugin manager, datasette plugin system.

---

Word count: ~2350.
