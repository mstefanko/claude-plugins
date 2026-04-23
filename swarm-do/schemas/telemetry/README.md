# swarm-do Telemetry Ledgers

Append-only JSONL ledgers that record every swarm invocation and its downstream
observations. This is the authoritative reference for the ledger contract as shipped
in Phase 9a. For design rationale, sequencing, and the operator-console view over
these ledgers, see `docs/plan.md` §1.8 (what to track) and §1.9 (storage architecture).

---

## Ledger types

Four files live under `${CLAUDE_PLUGIN_DATA}/telemetry/`:

### `runs.jsonl` — one row per `swarm-run` invocation

Records the execution envelope: timing, backend, model, effort, prompt identity, token
usage, exit outcome, and writer/reviewer verdicts. Fields that are not yet observable
(e.g., `input_tokens`, `estimated_cost_usd`) are written as JSON `null` rather than
omitted — this keeps downstream aggregations honest without requiring `COALESCE` on
missing keys.

Schema: `runs.schema.json#v1`

Key fields: `run_id`, `timestamp_start`, `timestamp_end`, `backend`, `model`,
`effort`, `role`, `prompt_bundle_hash`, `config_hash`, `exit_code`, `schema_ok`,
`wall_clock_seconds`, `writer_status`, `review_verdict`.

### `findings.jsonl` — one row per finding emitted by a review role

Reviewer agents emit structured findings (type errors, boundary violations, security
issues, etc.). Each finding references its parent run via `run_id` and carries a
`stable_finding_hash_v1` for deduplication across runs.

**Write path (Phase 9b):** `bin/extract-phase.sh` reads `agent-codex-review` findings.json
and appends one row per finding. The extractor is fail-open (`exit 0` on any error)
and is wired into `swarm-run` after the codex step with `|| true`. Claude reviewer
format is undefined and deferred (9b-claude). Non-codex roles are skipped with a
logged warning.

**Stable hash algorithm (`stable_finding_hash_v1`):**
`sha256("{file_normalized}|{category_class}|{floor(line_start/10)}|{short_summary}")`
where `file_normalized` is produced by `bin/_lib/normalize-path.sh` (strips worktree
prefix so main-repo and worktree paths hash identically). `duplicate_cluster_id` is
always null on append — stamped by the Phase 9e indexer post-hoc.

Schema: `findings.schema.json#v1` (frozen) — for new rows written by the Phase 9b
extractor, see `findings.v2.schema.json#v2` which adds `stable_finding_hash_v1`,
`duplicate_cluster_id`, and `short_summary`, and relaxes `run_id` to match runs.v1.

### `outcomes.jsonl` — append-only, one row per observed maintainer action

Records what happened to a finding after the run: was it fixed, acknowledged,
closed as won't-fix? Populated by the nightly enricher (Phase 9d), not by `swarm-run`
directly.

Schema: `outcomes.schema.json#v1`

### `adjudications.jsonl` — append-only, blinded verdict rows

Monthly blinded adjudication pass — a human (or dedicated adjudicator role) reads
findings without knowing the backend that produced them and records `TP | FP |
Ambiguous`. Used to calibrate precision over time.

Schema: `adjudications.schema.json#v1`

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

`schema_ok: true` in a Phase 9a row means **writer-attested structural conformance**,
not validator-confirmed. `swarm-run` sets `schema_ok=true` unconditionally when the
telemetry row is successfully constructed and appended. Real schema validation (via
`swarm-validate` against these JSON Schema files) lands in **Phase 10a**. At that point
the indexer may retroactively mark older rows or the validator may gate new rows.
Until Phase 10a ships, treat `schema_ok` as "the writer believed this row was well-formed".

---

## `run_id` pattern — relaxed in Phase 9a, strict ULID in Phase 10a

The v1 `runs.schema.json` accepts `run_id` values matching `^[0-9A-Z_-]{1,64}$` — a
relaxed pattern that covers the current timestamp-hex generator in `swarm-run`. This
was a deliberate Phase 9a choice: generating valid Crockford-base32 ULIDs in portable
shell requires `openssl rand`, which was not verified available in all environments.

Phase 10a (`mstefanko-plugins-utu`) will migrate to strict ULIDs and tighten the
pattern to `^[0-9A-HJKMNP-TV-Z]{26}$`. Existing `runs.jsonl` rows will remain valid
under the relaxed pattern; the indexer will tag non-ULID rows for backfill.

---

## Cross-references

- `docs/plan.md §1.8` — full field-by-field ledger specification and invariants
- `docs/plan.md §1.9` — two-tier storage architecture (JSONL truth + SQLite derived index)
- `docs/plan.md §1.10` — preset/pipeline registry and its telemetry integration point
- `bin/_lib/hash-bundle.sh` — produces the `prompt_bundle_hash` field
- `bin/_lib/normalize-path.sh` — produces `file_normalized` for `stable_finding_hash_v1` input
- `bin/swarm-run` — writer to `runs.jsonl` (EXIT trap, fail-open guard); wires `extract-phase.sh` after codex step
- `bin/extract-phase.sh` — writer to `findings.jsonl` (codex-only; fail-open; Phase 9b)
- `bin/swarm-telemetry` — read-only reporter (Phase 9c); `query`, `report`, `dump`, `validate` subcommands; see `swarm-do/README.md §bin/swarm-telemetry` for full usage
