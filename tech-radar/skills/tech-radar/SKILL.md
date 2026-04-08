---
name: tech-radar
description: "Scan trending repos, plugins, and ecosystem tools against your tech stack and produce a ranked Obsidian note."
allowed-tools: ["WebSearch", "Read", "Write", "Bash", "Glob"]
author: mstefanko
---

# Tech Radar

USE THIS SKILL when the user says: "tech radar", "scan for tools", "what's trending", "new tools", "tech scan", "run a radar scan", "/tech-radar".

## Overview

Scans the web for trending repositories, Claude Code plugins, and developer tools. Filters results against your configured tech stack and produces a grouped, ranked Obsidian note.

**Not a scoring formula.** Results are grouped by relevance tier and sorted by popularity. You make the judgment calls.

## Config

Reads `~/.tech-radar.json` (created by `/tech-radar:setup`).

Schema:
- `stack.backend` — array of backend tech keywords (e.g., ["ruby", "rails", "mysql", "rspec"])
- `stack.frontend` — array of frontend tech keywords (e.g., ["stimulus", "turbo", "bootstrap", "esbuild"])
- `stack.infra` — array of infra keywords (e.g., ["docker", "caddy"])
- `stack.migrating_from` — tech you're moving away from (e.g., ["coffeescript", "backbone"])
- `stack.migrating_to` — tech you're moving toward (e.g., ["stimulus", "turbo", "bootstrap 5"])
- `interests` — additional topic keywords (e.g., ["healthcare", "hipaa", "hotwire"])
- `min_stars` — minimum GitHub stars to include (default: 1000)
- `installed_plugins` — list of installed Claude Code plugins (to flag in output)
- `last_scan` — ISO date of last scan run

Output path: reads `vault_path` and `notes_dir` from `~/.obsidian-notes.json`. No `output_dir` in tech-radar config.

If config is missing, tell the user to run `/tech-radar:setup`.

## Scan Process

See `/tech-radar:scan` command and `resources/search-queries.md` for query templates.

## Grouping Rules

After collecting search results:
1. **Discard** results without a GitHub/registry URL or below `min_stars`
2. **Dedup** same project found across multiple searches
3. **Group by relevance:**
   - **Direct fit** — matches `backend`, `frontend`, or `migrating_to` keywords
   - **Adjacent** — matches `interests` or `infra`, or is a Claude Code plugin
   - **General** — developer tool, no specific stack match
4. **Sort by popularity within group** (star tiers: 1k-5k / 5k-20k / 20k+)
5. **Flag installed plugins** from config
6. **Cap at 30 results total**

## Error Handling

- If a WebSearch call fails, continue with remaining results
- Report which searches succeeded/failed at top of output
- If zero results after filtering, say so explicitly

## Output Format

Write to `{vault_path}/{notes_dir}/{YYYY-MM-DD}-tech-radar.md` with frontmatter:

```yaml
type: note
project: tech-radar
date: {today}
tags: [tech-radar, {timeframe}]
```

Include: executive summary (3-5 bullets), then tables grouped by tier. Each row: Project | What | Stars | URL | Verdict. Adjacent/Plugins table adds an "Installed?" column.

Also print a short summary to the conversation after writing the file.
