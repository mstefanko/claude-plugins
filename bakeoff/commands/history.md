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

1. Run the CLI-rendered history command:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" ls --history --limit <limit> [--out <dir>] [--facet <id>] [--triage-state <state>] [--type <type>]
   ```

   Pass `--out`, `--facet`, `--triage-state`, and `--type` through to the CLI.
   The CLI owns manifest scanning, `finished_at` sorting, limiting, summary
   extraction, and Markdown-table rendering. Do not parse `bakeoff ls --json`,
   read `work-order.json`, inspect provider prompts, or re-render rows in the
   model unless the user asks for a custom view the CLI cannot produce.

2. Return the CLI output directly. Keep the final response short; the table is
   the answer.

## Empty And Error States

If the list is empty, the CLI prints:

```text
No Bakeoff runs found under <out-dir>.
```

If no rows remain after filters, the CLI reports no matching runs.

If the command fails with an unknown `--history`, `--limit`, or `--type` flag,
tell the user to run `/bakeoff:setup` so the bundled CLI is rebuilt or updated.
