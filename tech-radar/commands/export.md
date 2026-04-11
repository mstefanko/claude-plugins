---
description: "Export scan results to Obsidian markdown"
argument-hint: "[--date YYYY-MM-DD] [--output PATH]"
---

# Tech Radar Export

Export scan results to an Obsidian-formatted markdown note.

## Process

Run via Bash:
```
$CLAUDE_PLUGIN_ROOT/scripts/tech-radar export [--scan-id ID] [--output PATH]
```

- `--date`: Export a specific scan by date, e.g. `--date 2026-04-10` (defaults to latest)
- `--output`: Write to a specific path (defaults to `{vault_path}/{notes_dir}/{YYYY-MM-DD}-tech-radar.md`)

Reads `~/.obsidian-notes.json` for vault path. If missing, prints to stdout.

The export produces the same markdown format as `/tech-radar:scan` Phase 4, but from existing database data — no new API calls needed. Useful for re-exporting after adding annotations or re-evaluating verdicts.
