---
description: "Scan trending tools and repos against your tech stack"
argument-hint: "[--weekly | --quarterly]"
---

# Tech Radar Scan

Run a web scan for trending tools, repos, and plugins filtered against your tech stack.

## Arguments

- No argument: monthly scan (default, last 30 days, 8-10 searches)
- `--weekly`: quick scan (last 7 days, 4-5 searches)
- `--quarterly`: broad scan (last 90 days, 12-14 searches, includes upgrade paths)

## Process

### Phase 1: Load Context

1. Read `~/.tech-radar.json` — if missing, tell user to run `/tech-radar:setup` and stop
2. Read `~/.obsidian-notes.json` — need `vault_path` and `notes_dir` for output
3. Calculate date range from the timeframe argument
4. Build search queries from `resources/search-queries.md` templates, substituting stack keywords and dates

### Phase 2: Web Searches

Run all WebSearch queries. These run in the main thread (WebSearch doesn't work in subagents).

- Track which queries succeed and which fail
- Continue on individual failures — partial results are fine
- If ALL searches fail, report the error and stop

### Phase 3: Filter & Group

1. **Discard junk** — skip results without a GitHub or registry URL, skip below `min_stars`
2. **Dedup** — merge same project found across multiple searches
3. **Group by relevance tier:**
   - **Direct fit** — matches `stack.backend`, `stack.frontend`, or `stack.migrating_to` keywords
   - **Adjacent** — matches `interests` or `stack.infra`, or is a Claude Code plugin
   - **General** — developer tool, no specific stack match
4. **Sort by popularity within each group** (star tiers: 1k-5k / 5k-20k / 20k+)
5. **Flag installed plugins** from `installed_plugins` config
6. **Cap at 30 results total**

### Phase 4: Write Output

Write to `{vault_path}/{notes_dir}/{YYYY-MM-DD}-tech-radar.md`:

```
---
type: note
project: tech-radar
date: {today}
tags: [tech-radar, {timeframe}]
---

# Tech Radar — {Month Year}

Stack: {one-line summary from config}
Scanned: {N}/{total} searches succeeded

## Key Takeaways

- {3-5 bullets: what's new, what's worth trying, what's missing}

## Direct Stack Match

| Project | What | Stars | URL | Verdict |
|---------|------|-------|-----|---------|
| ... | one-line description | tier | url | natural language verdict |

## Adjacent / Plugins

| Project | What | Stars | URL | Installed? | Verdict |
|---------|------|-------|-----|------------|---------|

## General Dev Tools

| Project | What | Stars | URL | Verdict |
|---------|------|-------|-----|---------|
```

Also print a short summary (3-5 lines) to the conversation.

### Phase 5: Update Config

Update `last_scan` in `~/.tech-radar.json` to today's date.

## Error Handling

- Individual WebSearch failures: continue, report at top of output
- Config missing: stop with clear instruction to run setup
- Obsidian config missing: stop with instruction to run `/obsidian-notes:setup`
- Zero results after filtering: write a note saying "no notable results this period"

## Quality Rules

- Verdicts are natural language, not standardized vocabulary ("Try on one CoffeeScript migration" not "Try now")
- Star counts are approximate from web results — use tiers not exact numbers
- Executive summary is the most important section — make it actionable
- Don't include tools the user obviously already knows about
