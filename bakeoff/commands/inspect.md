---
description: Inspect Bakeoff run ledgers and reports
argument-hint: "[latest|run-id] [--out runs] [--list] [--verify] [--triage-dry-run] [--triage-force]"
allowed-tools: Read, Glob, Grep, Bash(${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff show:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff ls:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff runs verify:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff triage:*), Bash(bakeoff show:*), Bash(bakeoff ls:*), Bash(bakeoff runs verify:*), Bash(bakeoff triage:*)
---

# /bakeoff:inspect

Inspect existing Bakeoff run ledgers and reports. Read-only inspection is the
default.

Apply the shared Bakeoff skill contract, especially the competitive build
handoff language.

## Preflight

Run first:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli" --check
```

If `--check` reports no provisioned CLI, run without `--check` only after
telling the user that this may build `dist/bakeoff` from source when Go is
available.

## Arguments

Default run id is `latest` for read-only operations.

Supported actions:

- no flags: `"${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" show <run-id> [--out <dir>]`
- `--list`: `"${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" ls [--out <dir>]`
- `--verify`: `"${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" runs verify <run-id> --json [--out <dir>]`
- `--triage-dry-run`: `"${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" triage <run-id> --dry-run [--out <dir>]`
- `--triage-force`: `"${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" triage <run-id> --force [--out <dir>]`

Only run triage when the user explicitly supplies `--triage-dry-run` or
`--triage-force`.

## Summary

Summarize the relevant artifacts:

- `decision.json`;
- `report.md`;
- `diagnostics.json` for build runs when present;
- triage artifacts and state when present;
- selected build patch artifact when `decision.json.canonical_winner` is
  non-null:
  `<out>/<run-id>/providers/<winner>/build/diff.patch`.

For build runs, repeat that the handoff is the Bakeoff report plus the selected
provider patch artifact. Do not apply, edit, combine, synthesize, commit, switch
branches, or publish patches from inspection.
