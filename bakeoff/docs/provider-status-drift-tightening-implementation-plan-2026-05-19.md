# Provider status drift tightening — implementation plan (2026-05-19)

## Context

A bakeoff `analyze` run on the question "can provider status drift across
`research --json`, `manifest.json`, `ls --json`, and `runs verify --json`?"
landed: run id `2026-05-19-f4f5`, winner `codex`, basis `atomic_count` (swap
disagreement on judge passes, resolved correctly).

- Report: `runs/2026-05-19-f4f5/report.md`
- Manifest: `runs/2026-05-19-f4f5/manifest.json`
- Work order: `provider-status-projection-drift.work-order.json`

The run answered the work-order question (yes, drift is structurally possible
today; 145 file:line citations; F-006/F-009 proposed a two-line fix in
`manifest.providerSummaries`). This plan chooses the lower-blast-radius F-010
variant for the status field: keep the existing raw `status` value and add
`compact_status`.

The run audit also surfaced four launcher-level tightening items (T1-T4). All
five items below have been verified against source by a follow-up agent — the
file:line anchors here are confirmed.

## Items

### F-009 / F-010: shared-contract fix — `manifest.providerSummaries` projection

**Problem.** `manifest.providers.<id>` exposes 9 fields; `decision.provider_statuses.<id>` exposes 14; the research-summary projection uses compacted status strings. Four projections of "claude's status" exist in this single run's outputs, none derived from a shared type.

**Anchor.** `internal/manifest/manifest.go:211-243` (the `providerSummaries`
inline map). Compaction helper already exists at
`internal/summary/summary.go:126-134` (`summary.CompactStatus`).

**Decision.** Use F-010, not the F-009 status-value flip. Keeping
`manifest.providers.<id>.status` raw avoids breaking external consumers that
already read that field as a runner status enum.

**Change spec.** Inside `providerSummaries` (`manifest.go:226-239`):

1. Keep `"status": statusInfo["status"]` unchanged.
2. Add `"compact_status": summary.CompactStatus(statusInfo["status"])`.
3. Copy passthrough fields from `StatusWithoutPayload`
   (`internal/artifact/artifact.go:54-78`): `exit_code`, `output_bytes` (as a
   separate field — do **not** fold into `stdout_bytes`), `stderr_truncated`,
   `stdout_truncated`, `stdout_observed_bytes`, `stderr_observed_bytes`,
   `scope_enforcement`, `stderr_path`. Use the existing `compactNilMap` to
   elide nils.

No new exported types. Do not add redundant `raw_status` while `status` remains
raw.

**Done when.** `manifest.providers.<id>` carries the same per-provider field
set as `decision.provider_statuses.<id>` (modulo the unrelated `io` /
`output_cap` / `format_retry` blocks), `status` remains the raw runner status,
and `compact_status` matches the compacted form used by `research --json`.

---

### T1: console `basis=` vs JSON `spine_tiebreak`

**Problem.** Heartbeat console output prints `winner=<x>, basis=<tiebreak>`,
but the on-disk `decision.json` for research runs only carries
`spine_tiebreak: "..."`. No `basis` key exists in research-mode JSON. (Build
mode uses `selection_basis` — different concept, same word.)

**Anchors.**
- Console literal: `internal/commands/researchcmd/run.go:498-507`
  (`fmt.Sprintf("winner=%s, basis=%s", winner, basis)`).
- JSON field: `internal/decision/decision.go:165`
  (`out["spine_tiebreak"] = tiebreak` — research path).
- Build-mode console uses `decision["selection_basis"]` at
  `internal/commands/buildcmd/report.go:293` — already keyed correctly, do not
  touch.

**Change spec.** Rename the console literal from `basis=` to
`spine_tiebreak=` in `researchcmd/run.go:507` so the label matches the JSON
key one-for-one. Do **not** add a `"basis"` alias to research `decision.json`
— `basis` everywhere else (build mode, docs) refers to `selection_basis`.

**Done when.** A grep across the codebase shows no `basis=` console literal
emitted by research mode; the user-visible label and on-disk key for the
research tiebreak share one name.

---

### T2: manifest passthrough fields (subsumed by F-009 above)

Listed here for traceability — the missing fields are
`exit_code`, `output_bytes`, `stderr_truncated`, `stdout_truncated`,
`stdout_observed_bytes`, `stderr_observed_bytes`, `scope_enforcement`,
`stderr_path`. All eight land as part of the F-009/F-010 change above; ship as
one commit.

---

### T3: `meta.facet` (object) vs `manifest.facet_id` (string)

**Problem.** `meta.json` carries the full facet object under `facet`;
`manifest.json` hoists the id to a top-level `facet_id`. Same concept, two
key names, two shapes.

**Anchors.**
- Meta: `internal/artifact/artifact.go:198` (`"facet": facetMap(wo.Facet)`),
  persisted at `artifact.go:215`.
- Manifest struct: `internal/manifest/manifest.go:142`
  (`FacetID *string \`json:"facet_id"\``); also written at `manifest.go:77`,
  loaded at `manifest.go:124`, used by `legacyLSRow` at `manifest.go:521`.
- Consumer: `internal/commands/lscmd/ls.go:93` reads `row["facet_id"]`.

**Change spec.** Do **not** rename keys — `lscmd` and any downstream parser of
`manifest.json` would break. Add a one-line doc comment on
`manifest.go:142` stating that `facet_id` is the hoisted `meta.facet.id`.
Document the relationship in `docs/work-orders.md` if not already covered.

**Done when.** A reader of either file can see, without grepping, that the two
fields refer to the same thing.

---

### T4: report-table `Stderr` column conflates capped vs observed bytes

**Problem.** `report.md`'s Provider Status table shows the on-disk (capped)
`stderr_bytes` in the Stderr column, and surfaces `stderr_observed_bytes`
only via a free-text note in the Notes column. Same drift class as F-001 —
this time in the human surface.

**Anchor.** `internal/report/report.go:157-209` `renderProviderStatusTable`;
notes blob at `report.go:181-183`.

**Change spec.** When `stderr_truncated` is true, format the cell as
`humanBytes(stderr_bytes) + " (obs " + humanBytes(stderr_observed_bytes) +
")"` and drop the corresponding "stderr observed" entry from the Notes
column. Apply the same treatment to stdout for symmetry. No table-schema
change; readers can still consume the column as a single string.

**Done when.** The Stderr column is self-describing on truncation; the Notes
column no longer duplicates observed-bytes data.

---

### F-004: contract test to lock invariants

**Anchor (proposed).** New test under `internal/manifest/` or `internal/summary/`.

**Change spec.** Build a tiny fixture run (or reuse an existing artifact) and
assert that for each provider id:

- The set of keys in `manifest.providers.<id>` is a superset of a hard-coded
  contract list.
- `manifest.providers.<id>.status` is one of the raw `runner.Status` enum
  values.
- `manifest.providers.<id>.compact_status` is one of the values returned by
  `summary.CompactStatus`.
- Where the same field appears in both `manifest.providers.<id>` and
  `decision.provider_statuses.<id>`, the values agree.

This is a regression bar for any future projection edit.

**Done when.** The test runs in CI and fails fast on field drift.

## Ordering

1. **T1** — one-line literal rename in `researchcmd/run.go`. Zero risk.
   Ship first so drift audits read cleanly.
2. **F-009/F-010 + T2 (single PR)** — touches one function
   (`providerSummaries`). Keep raw `status`, add `compact_status`, copy
   passthrough fields.
3. **T4** — report-renderer change. Independent of the others.
4. **F-004 contract test** — after F-009/F-010 + T2 land, so it locks in the
   new shape rather than the old.
5. **T3** — doc comment only; can land any time, lowest priority.

## Compatibility concerns

- **T1, T4, T3:** none (console / markdown / doc comment).
- **F-009/F-010 / T2:** `manifest.json` gains new optional keys — additive,
  safe for key-lookup consumers, would break strict JSON-schema validators.
  No `schema_version` field exists in `manifest.go` today; if one is added
  later, bump it as part of F-004.
- **Status compatibility:** this plan intentionally avoids the F-009
  `status` value flip. Existing readers continue to see the raw runner status
  at `manifest.providers.<id>.status`; new readers can use
  `compact_status`.

## Run pointer

- Run: `runs/2026-05-19-f4f5/`
- Report sections: F-001..F-011 referenced by id
- Triage: not yet run; `bakeoff triage 2026-05-19-f4f5` if a deeper read is
  wanted before any of the above lands.
