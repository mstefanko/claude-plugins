# swarm-do Telemetry Ledgers

Append-only JSONL ledgers that record every swarm invocation and its downstream
observations. This is the authoritative reference for the ledger contract as shipped
in Phase 9a. For design rationale, sequencing, and the operator-console view over
these ledgers, see `docs/plan.md` §1.8 (what to track) and §1.9 (storage architecture).

The ledger table below is generated — do not hand-edit inside the markers; run `python3 -m swarm_do.telemetry.gen docs --write` to regenerate it from the LEDGERS registry.

---

<!-- BEGIN: generated-by swarm_do.telemetry.gen docs -->
| Ledger | Filename | Schema | Fallback count |
|--------|----------|--------|----------------|
| adjudications | adjudications.jsonl | `swarm-do/schemas/telemetry/adjudications.v2.schema.json` | 2 |
| finding_outcomes | finding_outcomes.jsonl | `swarm-do/schemas/telemetry/finding_outcomes.schema.json` | 1 |
| findings | findings.jsonl | `swarm-do/schemas/telemetry/findings.v2.schema.json` | 2 |
| knowledge | knowledge.jsonl | `swarm-do/schemas/telemetry/knowledge.schema.json` | 1 |
| observations | observations.jsonl | `swarm-do/schemas/telemetry/observations.schema.json` | 1 |
| outcomes | outcomes.jsonl | `swarm-do/schemas/telemetry/outcomes.schema.json` | 1 |
| run_events | run_events.jsonl | `swarm-do/schemas/telemetry/run_events.schema.json` | 1 |
| runs | runs.jsonl | `swarm-do/schemas/telemetry/runs.v2.schema.json` | 2 |
<!-- END: generated-by swarm_do.telemetry.gen docs -->

---

## Ledger types

The registered ledger files live under `${CLAUDE_PLUGIN_DATA}/telemetry/`:

### `runs.jsonl` — one row per `swarm-run` invocation

Records the execution envelope: timing, backend, model, effort, prompt identity, token
usage, exit outcome, and writer/reviewer verdicts. Fields that are not yet observable
(e.g., `input_tokens`, `estimated_cost_usd`) are written as JSON `null` rather than
omitted — this keeps downstream aggregations honest without requiring `COALESCE` on
missing keys.

Schema: `runs.v2.schema.json#v2` for decomposed/unit-aware rows, with
`runs.schema.json#v1` retained for legacy fallback.

Key fields: `run_id`, `timestamp_start`, `timestamp_end`, `backend`, `model`,
`effort`, `role`, `prompt_bundle_hash`, `config_hash`, `preset_name`,
`pipeline_name`, `pipeline_hash`, `exit_code`, `schema_ok`, `wall_clock_seconds`,
`writer_status`, `review_verdict`.

### `findings.jsonl` — one row per finding emitted by a review role

Reviewer agents emit structured findings (type errors, boundary violations, security
issues, etc.). Each finding references its parent run via `run_id` and carries a
`stable_finding_hash_v1` for deduplication across runs.

**Write path (Phase 9b + 9b-claude):** `bin/extract-phase.sh` reads
`agent-codex-review` JSON findings and Claude-style `agent-review` /
`agent-code-review` markdown, then appends one row per finding. The extractor is
fail-open (`exit 0` on any error) and is wired into `swarm-run` after supported
review roles with a non-blocking guard. Unsupported roles are skipped with a logged
warning.

**Stable hash algorithm (`stable_finding_hash_v1`):**
`sha256("{file_normalized}|{category_class}|{floor(line_start/10)}|{short_summary}")`
where `file_normalized` is produced by `bin/_lib/normalize-path.sh` (strips worktree
prefix so main-repo and worktree paths hash identically). `duplicate_cluster_id` is
always null on append — stamped by the Phase 9e indexer post-hoc.

Schema: `findings.schema.json#v1` (frozen) — for new rows written by the Phase 9b
extractor, see `findings.v2.schema.json#v2` which adds `stable_finding_hash_v1`,
`duplicate_cluster_id`, and `short_summary`. Phase 10a run IDs are strict ULIDs; older
findings may still reference legacy Phase 9a run IDs.

### `outcomes.jsonl` — append-only, one row per **phase verdict** (Phase 9a ledger — frozen)

Records the phase-level verdict for a swarm run: did the phase pass, fail, or require
re-run? Written by the Phase 9a telemetry path. **This ledger is frozen** — its schema
and write path are stable from Phase 9a and are not extended by later phases.

Schema: `outcomes.schema.json#v1`

### `finding_outcomes.jsonl` — append-only, one row per **per-finding maintainer action** (Phase 9d ledger)

Records what happened to an individual finding after the run: hotfix within 14 days,
follow-up issue/PR, acknowledged, closed as won't-fix, etc. This is a **separate ledger**
from `outcomes.jsonl` — do not confuse the two:

| Ledger | Granularity | Written by | Phase |
|---|---|---|---|
| `outcomes.jsonl` | One row per phase verdict | Phase 9a path | 9a (frozen) |
| `finding_outcomes.jsonl` | One row per per-finding maintainer action | `swarm-telemetry join-outcomes` | 9d |

Populated by `bin/swarm-telemetry join-outcomes` (manual invocation). The joiner uses a
±10 line window for hotfix correlation and a 14-day window measured from the finding
timestamp (PR merge timestamp via `gh api` fallback). Supports `--dry-run`.

Schema: `finding_outcomes.schema.json#v1`

### `adjudications.jsonl` — append-only, blinded verdict rows

Monthly blinded adjudication pass — a human (or dedicated adjudicator role) reads
findings without knowing the backend that produced them and records `TP | FP |
Ambiguous`. Used to calibrate precision over time.

Schema: `adjudications.schema.json#v1`

### `run_events.jsonl` — append-only orchestration event sidecar

Records checkpoint, resume, handoff, retry, drift, and merge-conflict events
without changing frozen `runs.v1` rows. Rows are joinable by `run_id`; rows that
carry `bd_epic_id` also provide the recovery mapping from telemetry run identity
back to the BEADS epic/run issue.

Schema: `run_events.schema.json#v1`

### `observations.jsonl` — hook/subprocess observation rows

Records low-level tool and stop/exit observations from hooks or subprocess traps
without launching a second LLM observer session. The schema intentionally allows
`null` for fields that are not available in every event source.

Schema: `observations.schema.json#v1`

### `knowledge.jsonl` — advisory extracted facts

Records opt-in, adjudicated run-close facts for bounded future priming. This is
an advisory ledger only; it is not a resume state store and is not required for
orchestration decisions.

Schema: `knowledge.schema.json#v1`

### `provider-findings.json` — per-run external provider artifact, not a ledger

`bin/swarm-stage-mco` writes one normalized provider-findings artifact under the
swarm run artifact directory. This file is intentionally not appended to
`${CLAUDE_PLUGIN_DATA}/telemetry/` yet; it is the experimental contract used to
evaluate whether external provider stages deserve promotion into the pipeline DSL.

Schema: `provider_findings.schema.json#v1-draft`

Key provider fields: `provider`, `provider_count`, `selected_providers`,
`detected_by`, `consensus_score`, `consensus_level`, `source_artifact_path`,
and `provider_error_class`.

---

## v1 freeze convention

Each schema carries a `$id` that ends in `#v1`, e.g.:

```
"$id": "https://mstefanko-plugins/swarm-do/telemetry/runs.schema.json#v1"
```

The `#v1` suffix is the freeze marker. The **filename is also immutable** — once a
v1 schema ships, the file is never overwritten. Future breaking changes (field
removals, type narrowing, additionalProperties changes) must create a new file:

```
runs.v2.schema.json    (new file, new $id ending in #v2)
```

Non-breaking additions (new nullable fields) may land in v1 only if
`additionalProperties: false` is not violated — in practice this means v1 is already
closed and any meaningful change gets a v2. When in doubt, create v2.

---

## Where `runs.jsonl` is written

```
${CLAUDE_PLUGIN_DATA}/telemetry/runs.jsonl
```

`CLAUDE_PLUGIN_DATA` is set by the Claude Code harness at plugin load time (typically
`~/.claude/plugin-data/mstefanko-plugins/swarm-do`). The directory
`${CLAUDE_PLUGIN_DATA}/telemetry/` is created by `bin/swarm-run`'s EXIT trap on first
write (`mkdir -p`). No manual setup is required.

---

## Fail-open discipline

Ledger writes must **never** block the pipeline. `swarm-run` wraps the entire telemetry
block in a fail-open guard:

```sh
{ ... telemetry write ... } || {
  echo 'swarm-run: telemetry write failed (non-fatal)' >&2
  true
}
```

The EXIT trap captures the original exit code (`FINAL_RC=$?`) before running the
telemetry block and re-emits it at the end (`exit "$FINAL_RC"`). If the ledger write
fails — due to a missing `CLAUDE_PLUGIN_DATA`, a read-only filesystem, or a `jq`
error — the pipeline exits with the backend's exit code, not with `1`. A warning is
emitted to stderr. No data is lost from the actual swarm work.

---

## `schema_ok` field — writer-attested in Phase 9a

`schema_ok: true` in a Phase 9a row meant **writer-attested structural conformance**,
not validator-confirmed. Phase 10a adds `swarm-validate` for preset/pipeline gates and
tightens new `runs.jsonl` rows to strict ULIDs plus pipeline identity fields. Older
rows can still be treated as legacy writer-attested data during index rebuilds.

---

## `run_id` pattern — strict ULID as of Phase 10a

The v1 `runs.schema.json` now accepts only `run_id` values matching
`^[0-9A-HJKMNP-TV-Z]{26}$`. `bin/swarm-run` generates these through the shared
`swarm_do.telemetry.ids.new_ulid()` helper so `runs.jsonl` and `findings.jsonl`
share the same identifier shape.

Rows written before Phase 10a may still carry the relaxed Phase 9a timestamp-hex
shape. Treat those as legacy rows when rebuilding derived indexes.

---

## Cross-references

- `docs/plan.md §1.8` — full field-by-field ledger specification and invariants
- `docs/plan.md §1.9` — two-tier storage architecture (JSONL truth + SQLite derived index)
- `docs/plan.md §1.10` — preset/pipeline registry and its telemetry integration point
- `bin/_lib/hash-bundle.sh` — produces the `prompt_bundle_hash` field
- `bin/_lib/normalize-path.sh` — produces `file_normalized` for `stable_finding_hash_v1` input
- `bin/swarm-run` — writer to `runs.jsonl` (EXIT trap, fail-open guard); wires `extract-phase.sh` after codex step
- `bin/extract-phase.sh` — writer to `findings.jsonl` (codex-only; fail-open; Phase 9b)
- `bin/swarm-telemetry` — reporter and write utility (Phase 9c read-only; Phase 9d adds `join-outcomes`); `query`, `report`, `dump`, `validate`, `join-outcomes` subcommands; see `swarm-do/README.md §bin/swarm-telemetry` for full usage
