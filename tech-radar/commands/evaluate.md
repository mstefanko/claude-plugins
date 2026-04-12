---
description: "Prepare pending repos for Claude evaluation and save verdicts"
argument-hint: "[pending | save]"
---

# Tech Radar Evaluate

Prepare pending repos for Claude evaluation or save verdict results back to the database.

## Subcommands

### `pending` (default)

Show repos from the latest scan that need Claude verdicts:
```
~/.claude/plugins/marketplaces/mstefanko-plugins/tech-radar/scripts/tech-radar evaluate pending
```

Returns JSON with `pending_count`, `projects` (stack context), and `repos` array. Each repo includes stars, delta, category, matched projects/keywords, HN context, and previous verdict if any.

### `save`

Save Claude's verdicts back to the database. Reads JSON from stdin:
```
echo '$VERDICTS_JSON' | ~/.claude/plugins/marketplaces/mstefanko-plugins/tech-radar/scripts/tech-radar evaluate save
```

Each verdict in the JSON array must have: `full_name`, `verdict_text`, `project_relevance`. Optionally: `reddit_validation`.

## Process

This command is typically called automatically by `/tech-radar:scan` during Phase 3 (Reddit validation) and Phase 4 (write report). It can also be used standalone to re-evaluate repos from a previous scan.

1. Run `evaluate pending` to get the list of repos needing verdicts
2. Use the repo data + project context to write verdicts
3. Run `evaluate save` to persist verdicts to the database
