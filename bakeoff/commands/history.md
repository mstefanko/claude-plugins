---
description: List recent Bakeoff runs with enough context to pick a run id
argument-hint: "[limit] [--out runs] [--facet ID] [--triage-state STATE] [--type TYPE]"
allowed-tools: Read, Glob, Grep, Bash(${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff ls:*), Bash(bakeoff ls:*)
---

# /bakeoff:history

List recent Bakeoff runs so the user can quickly copy or reference a run id.
This command is read-only. Do not run providers, triage, rerun, edit patches,
or inspect long artifacts unless the user asks for a specific run afterward.

Apply the shared Bakeoff skill contract.

## Preflight

Run first:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli" --check
```

If this exits `2`, stop and tell the user:

```text
Run /bakeoff:setup to build the bundled Bakeoff Go CLI into plugin data, or set
BAKEOFF_GO_BINARY. Go 1.24+ is required for the default setup path.
```

## Arguments

Parse `$ARGUMENTS`.

Supported arguments:

- optional first positional integer `limit`; default `10`;
- `--out <dir>`; default `runs`;
- `--facet <id>`;
- `--triage-state <no|dry_run|yes|stale>`;
- `--type <gather|compare|analyze|build>`.

Reject unknown flags, missing flag values, non-integer limits, and limits less
than `1`. Keep the error short and show the supported shape:

```text
/bakeoff:history [limit] [--out runs] [--facet ID] [--triage-state STATE] [--type TYPE]
```

## Flow

1. Run the manifest-backed list command:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" ls --json [--out <dir>] [--facet <id>] [--triage-state <state>]
   ```

   Pass only `--out`, `--facet`, and `--triage-state` through to the CLI.
   Apply `--type` locally after parsing the JSON.

2. Parse the JSON response. It has this shape:

   ```json
   {"schema_version":1,"out_dir":"runs","runs":[]}
   ```

3. Sort rows by parsed `finished_at` descending. Accept RFC3339 values with
   either `Z` or an offset such as `+00:00`. Put missing or unparseable
   timestamps after dated rows. Tie-break by `run_id` descending.

4. Apply the `--type` filter when present, then limit the result count.

5. For each displayed row only, resolve the run directory:

   - if `manifest_path` is present, use its parent directory;
   - else if `report_path` is present, use its parent directory;
   - else use `<out_dir>/<run_id>`.

6. Read `<run-dir>/work-order.json` when present. Use the first non-empty value
   from:

   - `goal`;
   - `background`;
   - first string entry in a `background` array.

   Collapse whitespace and truncate the summary to about 100 characters. Do
   not read provider prompts by default; they are generated artifacts and can be
   very long.

7. Render a compact Markdown table:

   ```text
   | finished | run id | type | facet | decision | triage | summary |
   ```

   Use `-` for missing facet or summary. Use a local datetime style for
   readability when that is easy; otherwise preserve the stored timestamp.

8. End with a short next-action hint:

   ```text
   Open one with `/bakeoff:inspect <run-id>`.
   ```

## Empty And Error States

If the list is empty, say:

```text
No Bakeoff runs found under <out-dir>.
```

If no rows remain after filters, name the filters and say no matching runs were
found.

If `work-order.json` is missing or invalid for a row, still show the row with
summary `-`. Do not fail the whole command.

If the `bakeoff ls --json` output is truncated or cannot be parsed, stop and
ask the user to narrow the query with `--out`, `--facet`, `--triage-state`, or
`--type`; do not present a partial history as authoritative.
