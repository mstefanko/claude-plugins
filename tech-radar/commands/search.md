---
description: "Search repos and verdicts via full-text search"
argument-hint: "<query>"
---

# Tech Radar Search

Search repos and verdicts in the tech radar database using FTS5 full-text search.

## Process

Run via Bash:
```
$CLAUDE_PLUGIN_ROOT/scripts/tech-radar search "<query>"
```

Searches across repo names, descriptions, and verdict text. Returns matching repos with stars, category, and verdict summary.

Display results to the user in a readable format. If no results, suggest broadening the query or running `/tech-radar:scan` to populate data.
