---
name: tech-radar
description: "Scan trending repos, plugins, and ecosystem tools against your tech stack and produce a ranked Obsidian note."
allowed-tools: "WebSearch,Read,Write,Bash,Glob"
author: mstefanko
---

# Tech Radar

USE THIS SKILL when the user says: "tech radar", "scan for tools", "what's trending", "new tools", "tech scan", "run a radar scan", "/tech-radar".

## Overview

Scans for trending repositories, Claude Code plugins, and developer tools using a hybrid architecture:

- **Python script** (`scripts/tech-radar-gather`) handles data gathering: GitHub Search API, HN Algolia API, keyword deduplication, concurrent HTTP requests, and history/diffing across scans
- **Claude** handles judgment: verdict writing, targeted Reddit validation via WebSearch, and Obsidian note rendering

The script outputs structured JSON with categorized repos, HN stories, and flags for items needing Reddit validation. Claude then synthesizes this into an actionable report.

**Not a scoring formula.** Results are grouped by which project they're relevant to, then sorted by popularity. You make the judgment calls.

## Requirements

- **GitHub auth** — needed for GitHub Search API access. Resolved automatically: `GITHUB_TOKEN` env var, then `gh auth token` (GitHub CLI). Without auth, queries are severely rate-limited. Set via `export GITHUB_TOKEN=ghp_...` or run `gh auth login`.
- **Python 3.8+** — the gathering script uses only stdlib modules (no pip install needed)
- **Bash** tool — needed to invoke the gathering script

## Config

Reads `~/.tech-radar.json` (created/updated by `/tech-radar:setup`). **Setup is optional** — scan works without it, you just lose project-specific grouping.

Setup auto-discovers git repos from common locations (`~/`, `~/code/`, `~/projects/`, etc.) and lets the user pick which to register. Use `--list` to view registered projects, `--remove <name>` to remove one.

Schema:
```json
{
  "projects": {
    "myorthomd-web": {
      "path": "/Users/mstefanko/myorthomd-web",
      "backend": ["ruby", "rails", "mysql", "rspec"],
      "frontend": ["stimulus", "turbo", "bootstrap", "esbuild"],
      "infra": ["docker", "caddy"],
      "migrating_from": ["coffeescript", "backbone", "jquery", "bootstrap 4"],
      "migrating_to": ["stimulus", "turbo", "bootstrap 5", "es6"]
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
- `phrase_queries` — optional array of multi-word terms to search as exact phrases (quoted in GitHub Search and HN Algolia). Example: `["generative UI", "design system"]`. Single-word interests don't need this — they work fine as individual keywords.
- `min_stars` — minimum GitHub stars to include (default: 1000)
- `installed_plugins` — Claude Code plugins to flag in output
- `last_scan` — ISO date of last scan run

Output path: reads `vault_path` and `notes_dir` from `~/.obsidian-notes.json`. No `output_dir` in tech-radar config.

## CLI Flags

- `--timeframe` — `weekly`, `monthly` (default), or `quarterly`
- `--source` — `all` (default), `github`, or `hn`
- `--max-repos N` — cap on main repos in output (default 20). Use `--max-repos 12` for faster weekly scans.
- `--dry-run` — use fixture data, no API calls
- `--config` — path to config file (default `~/.tech-radar.json`)
- `--history-dir` — path to history directory (default `~/.tech-radar/`)

## State Directory

`~/.tech-radar/` contains `history.json` for cross-scan persistence. The script uses this to track:
- Which repos have been seen before vs. new this scan
- Star count deltas between scans (powers the "Rising Stars" section)
- Scan count per repo (how many consecutive scans a repo appears in)

## No-Config Mode

If `~/.tech-radar.json` doesn't exist, scan still runs:
- Uses `interests` defaults: `["developer-tools", "claude-code"]`
- Runs generic queries (no stack-specific filtering)
- Groups results as "General Dev Tools", "Plugins", and "HN Highlights" only
- Suggests running `/tech-radar:setup` at the end for better results next time

## Scan Process

1. **Script gathers data** — `tech-radar-gather` queries GitHub Search API and HN Algolia API, deduplicates, categorizes, and diffs against history
2. **Claude validates via Reddit** — targeted WebSearch for items flagged `reddit_validate: true` (hard cap: 6 searches)
3. **Claude writes report** — renders structured JSON into an Obsidian note with verdicts, key takeaways, and per-project grouping

See `/tech-radar:scan` command for the full process and report template.

## Grouping Rules

The script handles initial categorization. Items arrive pre-grouped as:
- `stack-match` — matches a registered project's tech stack keywords
- `plugin` — Claude Code plugins
- `under-the-radar` — young repos with high stars-per-day
- `rising-star` — repos with significant growth since last scan
- `interest-match` — matches global interest keywords (wild cards)
- `general` — developer tools that don't match any specific project

Claude renders each category into the appropriate report section.

## JSON Output Fields

Each repo in the script's JSON output includes:
- `query_type` — `"stack"`, `"interest"`, `"phrase"`, or `"code"`. Stack queries use `created:>` (new repos only). Interest and phrase queries use `pushed:>` (established repos with recent activity).
- `relevance_score` — priority ranking (3=stack-match, 2=plugin, 1=interest, 0=general, +1 for viral growth >50 stars/day). Higher-scored repos get detailed verdicts; lower-scored general repos can get shorter verdicts. Category diversity slots ensure all four categories are represented in the final output.
- `matched_projects` — (HN stories) list of registered project names the story is relevant to, used for cross-referencing in report rendering.

Constants: `BROAD_KEYWORD_THRESHOLD = 3` (keywords in 3+ projects are treated as broad and don't drive stack-match assignment), `DIVERSITY_SLOTS` (reserved per-category minimums ensuring category representation in capped output).

## Error Handling

- If the script fails entirely (non-zero exit), fall back to WebSearch-only approach using `resources/search-queries.md` templates
- If individual sources fail (`meta.sources.X.status == "error"`), note it in the report header and continue
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
2. **For {project-name}** — one section per registered project with matching results
3. **Plugins** — Claude Code plugin discoveries
4. **Discovery & Inspiration** — Under the Radar, Rising Stars, Wild Cards, HN Highlights
5. **General Dev Tools** — everything else

Also print a short summary to the conversation after writing the file.
