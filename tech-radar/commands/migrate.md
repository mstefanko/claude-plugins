---
description: "Import history.json into the SQLite database"
---

# Tech Radar Migrate

One-time migration: import existing `~/.tech-radar/history.json` data into the SQLite database.

## Process

Run via Bash:
```
$CLAUDE_PLUGIN_ROOT/scripts/tech-radar migrate
```

This reads `~/.tech-radar/history.json` and imports all repos and scan snapshots into `~/.tech-radar/radar.db`. The migration is idempotent — running it again won't create duplicates (uses upsert).

Only needed if you have scan data from before the database refactor. New installations start with an empty database automatically.
