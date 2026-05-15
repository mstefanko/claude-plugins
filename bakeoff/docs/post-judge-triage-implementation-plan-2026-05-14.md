# Post-Judge Triage for Bakeoff — Implementation Plan

Date: 2026-05-14
Status: implemented in v1 scope
Scope: `bakeoff` CLI, post-run verification/triage of judge reports

## Decision

Add an explicit post-judge triage command:

```text
bakeoff triage <run-id> [--out runs] [--force] [--dry-run]
bakeoff show <run-id> --triage
```

Triage is opt-in. It does not mutate `decision.json` or `report.md`, and it is
not wired into `research --triage` in v1.

## Artifacts

```text
runs/<run-id>/triage/
  prompt.txt
  status.json
  finding_index.json
  citation_checks.json
  stdout.txt        # non-dry-run only
  stderr.txt        # non-dry-run only
  final.json        # non-dry-run success only
  triage.md         # non-dry-run success only
```

`finding_index.json` is written for legacy reports that need synthesized
`LEGACY-F-*` identifiers.

## Behavior

- Reports render stable `F-001`, `F-002`, ... IDs in display order.
- New `meta.json` files record the original `cwd` and hashes for
  `decision.json`, `report.md`, and `work-order.json`.
- The triage harness extracts local `path:line` and `path:start-end`
  citations from the report, decision, provider finals, and judge results.
- Citation checks are performed by the harness before the provider call and
  recorded with statuses such as `ok`, `missing_file`, `line_out_of_range`,
  and `path_escape`.
- The triage provider receives normalized artifacts plus citation checks and
  must emit structured `<final_json>`.
- `bakeoff ls` displays `triage:<no|yes|stale>`.

## Non-Goals

- No automatic code edits.
- No automatic issue creation.
- No mutation of judge outputs.
- No automatic triage after research.
- No `research --triage` in v1.
