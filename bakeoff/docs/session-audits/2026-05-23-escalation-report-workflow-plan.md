# Escalation report workflow plan — 2026-05-23

This plan covers the artifact and reporting workflow for sessions where a
source `/bakeoff:run` is followed by one or more `bakeoff escalate` runs. It is
based on the 2026-05-23 run set indexed by
`docs/session-audits/2026-05-23-consolidated-plan.md`.

## Problem

The current artifact model is structurally sound: escalations are separate run
directories and the source run is not mutated. The weak point is discoverability.
A later operator who wants to reconstruct the full story must already know to
scan all `runs/*/manifest.json` files for `source_run_id`, then manually open
source reports, escalation reports, and triage artifacts.

The common workflow should be easy:

1. Start from one source run, or from a small set of source runs.
2. Pull the source report and triage state.
3. Pull every child escalation report.
4. Pull escalation triage state when present.
5. See missing, stale, failed, or zero-selected triage warnings.
6. Produce one consolidated operator-facing report for fixing the real issues.

## Evidence

Relevant run graph:

| Source run | Type | Child escalation runs |
|---|---|---|
| `2026-05-23-e57e` | compare | `2026-05-23-95b9` dispute, Gemini |
| `2026-05-23-bb94` | compare | `2026-05-23-ee29` dispute, Gemini |
| `2026-05-23-871b` | analyze | `2026-05-23-0aee` dispute, Codex |
| `2026-05-23-fddc` | gather/code-review | `2026-05-23-276a` witness, Gemini; `2026-05-23-b6f3` dispute, Gemini |

Confirmed facts:

- Escalations are separate runs, not source-run subdirectories. This matches the
  CLI reference contract that escalation writes a new run directory and does not
  mutate the source run.
- Forward links exist. Escalation reports contain a `Source Run` section, and
  escalation manifests carry `source_run_id`, `source_type`,
  `escalation_mode`, and triage summary fields.
- Reverse links are not surfaced. Source reports and source manifests do not
  list later child escalations. `bakeoff show` prints only the selected report
  plus triage state hints, and `bakeoff ls` does not show source/escalation
  relationship columns.
- Historical escalation reports contain raw Go `map[...]` literals in body
  lists and summary text, especially in `95b9`, `0aee`, and `b6f3`.
- Code-review escalation triage can run but select zero source findings, because
  the triage finder indexes `F-NNN` items and ordinary report sections, not
  `D-NNN` dispute points under `Dispute Assessment`.
- `source-run.json` snapshots do not include source triage artifacts. They
  fingerprint source decision/report/provider artifacts but omit
  `triage/status.json`, `triage/final.json`, and `triage/triage.md`.

Primary files to inspect before implementation:

- `internal/commands/showcmd/show.go`
- `internal/commands/lscmd/ls.go`
- `internal/manifest/manifest.go`
- `internal/commands/escalatecmd/escalate.go`
- `internal/report/report.go`
- `internal/triage/state.go`
- `docs/cli-reference.md`
- `runs/2026-05-23-{e57e,95b9,bb94,ee29,871b,0aee,fddc,276a,b6f3}/`

## Recommended artifact model

Keep escalation reports where they are: `runs/<escalation-id>/report.md`.

Do not move them under the source run. The non-mutating source-run contract is a
good property. It prevents historical source artifacts from changing after a
follow-up run and keeps escalation runs independently addressable by `run_id`.

Instead, add discoverability surfaces that derive relationships by scanning
manifests for `source_run_id`.

## Planned changes

### 1. Related-runs surface

Add a related-runs summary to `bakeoff show <source-run-id>`:

```text
related escalations:
  2026-05-23-95b9  dispute  gemini  escalation_advisory_supported  triage:no
```

For an escalation run, show the source run and sibling escalations:

```text
source run: 2026-05-23-e57e
sibling escalations:
  2026-05-23-95b9  dispute  gemini  escalation_advisory_supported  triage:no
```

Implementation notes:

- Scan `opts.Out` for manifests with `type == "escalation"` and
  `source_run_id == <selected-run>`.
- For an escalation run, read its own `source_run_id`, then scan for all
  escalations with the same source.
- Do not mutate the source run.
- Keep output compact by default; a future flag can expand into full paths.

Verifier:

- Add show-command tests with one source run and two child escalations.
- Assert source `show` lists both children.
- Assert escalation `show` lists its source and sibling.

### 2. JSON/listing support

Extend `bakeoff ls --json` rows for escalation runs with:

- `source_run_id`
- `source_type`
- `escalation_mode`
- `added_provider`

Optionally add source rows with:

- `child_escalation_count`
- `child_escalations`

For tabular `bakeoff ls`, avoid making the default table too wide. Prefer a
new filter first:

```text
bakeoff ls --source-run 2026-05-23-fddc
```

Verifier:

- Add `lscmd`/manifest projection tests proving relationship fields appear in
  JSON and source-run filtering works.

### 3. Bundle/report command

Add an explicit command for the reconstruction workflow:

```text
bakeoff bundle RUN_ID
```

or:

```text
bakeoff report RUN_ID --with-escalations
```

Output should include:

1. Source run header and decision.
2. Source report path and triage state.
3. Source triage summary or missing/stale/failed warning.
4. Child escalation table.
5. Each child escalation report path, decision, mode, provider, and triage state.
6. Escalation triage summary or warning.
7. A final "operator next steps" block:
   - run missing triage where appropriate,
   - rerun stale triage,
   - inspect zero-selected triage,
   - open consolidated report if written to disk.

A later extension can write a Markdown rollup artifact:

```text
runs/<source-id>/related-report.md
```

If that file is added, it should be explicitly derived/regenerable and should
not become part of the immutable source-run core contract.

Verifier:

- Fixture with one source and two child escalations.
- Assert bundle output includes source report, source triage state, both child
  reports, child triage states, and zero-selected warning when applicable.

### 4. Escalation report formatting

Finish the structured formatter for escalation item lists and summary lists.

Known shapes to support:

- `{id, resolution, evidence}`
- `{id, answer, verdict}`
- `{id, rationale}`
- `{point_id, evidence}`
- `{claim, description}`
- string items

Required behavior:

- No rendered report should contain `map[`.
- `D-NNN`/`F-NNN`/`R-NNN` identifiers should be bold when present.
- Evidence should render as a labeled continuation line.
- Unknown map shapes should still render deterministically as structured JSON,
  not Go's `%v` map format.

Verifier:

- Unit tests in `internal/report/report_test.go`.
- Fixture tests for dispute, witness, and independent escalation render paths.
- Re-render historical reports for `95b9`, `0aee`, and `b6f3` and confirm no
  `map[` remains.

### 5. Source triage snapshot for escalations

Extend escalation metadata so a future bundle can explain the source state at
the time of escalation.

Options:

- Add source triage fields to `source-run.json`.
- Or write a sibling `source-triage.json`.

Recommended fields:

- `state`
- `stale_inputs`
- `status_path`
- `final_path`
- `triage_md_path`
- hashes for `triage/status.json`, `triage/final.json`, and `triage/triage.md`
  when present
- `item_count`
- `item_counts_by_classification`

Verifier:

- Escalation command test where source has triage.
- Assert source triage metadata is included.
- Assert missing source triage is represented explicitly, not omitted silently.

### 6. Escalation triage semantics

Pick one behavior and make it visible:

Option A — index `D-NNN` dispute points as triage source findings.

- Pros: dispute escalations with material resolved points can be triaged.
- Cons: triage schema currently expects source findings; this broadens the
  concept from source report findings to escalation assessment items.

Option B — treat zero-selected escalation triage as intentional.

- Pros: smaller change.
- Cons: still less useful when escalation discovered actionable material.

Minimum acceptable fix:

- When triage selected zero findings, surface that clearly in report/show/bundle:
  "triage completed; no triageable report findings were selected."

Verifier:

- Run against a dispute report containing `D-NNN` items.
- Assert either selected D-items appear in triage input, or zero-selection is
  explicitly marked in the output and manifest.

## Suggested execution order

1. Escalation report formatting. Small, high-visibility, already reproduced.
2. Related-runs surface in `show` and `ls --json`. Unlocks discovery.
3. Bundle/report command. Turns discovery into a one-command workflow.
4. Source triage snapshot. Improves historical reconstruction.
5. Escalation triage semantics. Needs product decision, but the warning path can
   ship first.

## Definition of done

- Starting from `2026-05-23-fddc`, one command can reveal both child escalations
  (`276a`, `b6f3`) and their triage states.
- Starting from `2026-05-23-b6f3`, one command can reveal source run `fddc` and
  sibling escalation `276a`.
- No newly rendered escalation report contains raw `map[` output.
- Bundle/report output calls out missing, stale, failed, and zero-selected
  triage states.
- The source run remains immutable; all reverse relationships are derived from
  manifests or generated rollup artifacts.
