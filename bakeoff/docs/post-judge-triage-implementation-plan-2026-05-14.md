# Post-Judge Triage for Bakeoff — Implementation Plan

Date: 2026-05-14
Status: implemented in v1 scope
Scope: `bakeoff` CLI, post-run verification/triage of judge reports

## Decision

Add an explicit post-judge triage command:

```text
bakeoff triage <run-id> [--out runs] [--force] [--dry-run] [--quiet]
bakeoff show <run-id> [--out runs] --triage
```

Triage does not mutate `decision.json` or `report.md`. It can be run explicitly,
and `code-review` facet research runs auto-triage after successful research
unless `research --no-triage` or `rerun --no-triage` is used.

## Artifacts

```text
runs/<run-id>/triage/
  prompt.txt
  status.json
  source_finding_filter.json
  finding_index.json
  citation_checks.json
  last-message.txt  # Codex only, when --output-last-message is supported
  stdout.txt        # non-dry-run only
  stderr.txt        # non-dry-run only
  final.json        # non-dry-run success only
  triage.md         # non-dry-run success only
  repair-*.txt/json # optional format-retry artifacts
```

`finding_index.json` is written for legacy reports that need synthesized
`LEGACY-F-*` identifiers. `source_finding_filter.json` records selected findings
and findings skipped as non-actionable or out-of-facet.

## Behavior

- Reports render stable `F-001`, `F-002`, ... IDs in display order.
- New `meta.json` files record the original `cwd` and hashes for
  `decision.json`, `report.md`, and `work-order.json`.
- The triage harness extracts local `path:line` and `path:start-end`
  citations from the report, decision, provider finals, and judge results.
- Citation checks are anchored to the original `cwd` recorded in `meta.json`,
  falling back to the current directory with a caveat, and recorded with
  statuses such as `ok`, `missing_file`, `line_out_of_range`, and `path_escape`.
- The triage provider receives normalized artifacts plus citation checks and
  must emit structured `<final_json>`.
- `--dry-run` writes the prompt, status, citation checks, and source filter
  without invoking a provider.
- `bakeoff ls` displays `triage:<no|dry_run|yes|stale>`.

## Non-Goals

- No automatic code edits.
- No automatic issue creation.
- No mutation of judge outputs.
- No general `research --triage` flag in v1; auto-triage is limited to the
  `code-review` facet path.
