---
name: tech-radar
description: "Scan trending repos, plugins, and ecosystem tools against your tech stack and produce a ranked Obsidian note."
allowed-tools: "WebSearch,Read,Write,Bash,Glob"
author: mstefanko
---

# Tech Radar

USE THIS SKILL when the user says: "tech radar", "scan for tools", "what's trending", "new tools", "tech scan", "run a radar scan", "/tech-radar".

## Overview

Scans the web for trending repositories, Claude Code plugins, and developer tools. Filters results against your registered projects' tech stacks and produces a grouped, ranked Obsidian note.

**Not a scoring formula.** Results are grouped by which project they're relevant to, then sorted by popularity. You make the judgment calls.

## Config

Reads `~/.tech-radar.json` (created/updated by `/tech-radar:setup`). **Setup is optional** — scan works without it, you just lose project-specific grouping.

Setup auto-discovers git repos from common locations (`~/`, `~/code/`, `~/projects/`, etc.) and lets the user pick which to register. Use `--list` to view registered projects, `--remove <name>` to remove one.

Schema:
```json
{
  "projects": {
    "myorthomd-web": {
      "path": "/Users/mstefanko/myorthomd-web",
      "stack": {
        "backend": ["ruby", "rails", "mysql", "rspec"],
        "frontend": ["stimulus", "turbo", "bootstrap", "esbuild"],
        "infra": ["docker", "caddy"],
        "migrating_from": ["coffeescript", "backbone", "jquery", "bootstrap 4"],
        "migrating_to": ["stimulus", "turbo", "bootstrap 5", "es6"]
      }
    },
    "enovis-plugins": {
      "path": "~/.claude/plugins/marketplaces/enovis-plugins",
      "stack": {
        "backend": ["bash", "node", "typescript", "sqlite"],
        "frontend": [],
        "infra": [],
        "migrating_from": [],
        "migrating_to": []
      }
    }
  },
  "interests": ["healthcare", "hipaa", "hotwire", "claude-code"],
  "min_stars": 1000,
  "installed_plugins": ["claude-mem", "context-mode", "obsidian-notes"],
  "last_scan": null
}
```

- `projects` — registry of projects, each with a name, path, and stack breakdown. Added incrementally via `/tech-radar:setup`.
- `interests` — global topic keywords that apply across all projects
- `min_stars` — minimum GitHub stars to include (default: 1000)
- `installed_plugins` — Claude Code plugins to flag in output
- `last_scan` — ISO date of last scan run

Output path: reads `vault_path` and `notes_dir` from `~/.obsidian-notes.json`. No `output_dir` in tech-radar config.

## No-Config Mode

If `~/.tech-radar.json` doesn't exist, scan still runs:
- Uses `interests` defaults: `["developer-tools", "claude-code"]`
- Runs generic queries (no stack-specific filtering)
- Groups results as "General Dev Tools" and "Plugins" only
- Suggests running `/tech-radar:setup` at the end for better results next time

## Scan Process

See `/tech-radar:scan` command and `resources/search-queries.md` for query templates.

## Grouping Rules

After collecting search results:
1. **Discard** results without a GitHub/registry URL or below `min_stars` (Claude Code plugins are exempt from `min_stars` — most have low star counts)
2. **Dedup** same project found across multiple searches
3. **Group by project relevance:**
   - For each registered project, check if the result matches that project's `backend`, `frontend`, `migrating_to`, or `infra` keywords
   - A result can appear under multiple projects if relevant to both
   - **Plugins** — Claude Code plugins get their own section
   - **General** — developer tools that don't match any specific project
4. **Sort by popularity within each group** (star tiers: 1k-5k / 5k-20k / 20k+)
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

Sections:
1. **Key Takeaways** — 3-5 actionable bullets
2. **For {project-name}** — one section per registered project, with results tagged to that project's stack
3. **Plugins** — Claude Code plugin discoveries
4. **General Dev Tools** — everything else

Each table row: Project | What | Stars | URL | Verdict. Plugin tables add an "Installed?" column.

Also print a short summary to the conversation after writing the file.
