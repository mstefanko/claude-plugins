---
description: "Scan trending tools and repos against your tech stack"
argument-hint: "[--weekly | --quarterly]"
---

# Tech Radar Scan

Run a web scan for trending tools, repos, and plugins. Results are grouped by which of your registered projects they're relevant to.

**Works without setup.** If `~/.tech-radar.json` doesn't exist, runs generic developer tool searches and suggests running `/tech-radar:setup` afterward.

## Arguments

- No argument: monthly scan (default, last 30 days, 8-10 searches)
- `--weekly`: quick scan (last 7 days, 4-5 searches)
- `--quarterly`: broad scan (last 90 days, 12-14 searches, includes upgrade paths)

## Process

### Phase 1: Load Context

1. Read `~/.tech-radar.json` — if missing, enter **no-config mode** (see below)
2. Read `~/.obsidian-notes.json` — need `vault_path` and `notes_dir` for output. If missing, print results to conversation only.
3. Calculate date range from the timeframe argument
4. Build search queries from `resources/search-queries.md` templates:
   - **With config:** substitute each project's stack keywords into templates. Generate queries per project.
   - **No-config mode:** use generic queries only (trending dev tools, Claude plugins, HN signal)

### Phase 2: Web Searches

Run all WebSearch queries. These run in the main thread (WebSearch doesn't work in subagents).

- Track which queries succeed and which fail
- Continue on individual failures — partial results are fine
- If ALL searches fail, report the error and stop

### Phase 3: Filter & Group

1. **Discard junk** — skip results without a GitHub or registry URL, skip below `min_stars` (default 1000)
2. **Dedup** — merge same project found across multiple searches
3. **Match to projects:**
   - For each result, check against each registered project's stack keywords
   - A result matching `backend`, `frontend`, `migrating_to`, or `infra` keywords goes under that project
   - A result can appear under multiple projects if relevant to both
   - Claude Code plugins always go in the **Plugins** section
   - Everything else goes in **General Dev Tools**
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

Projects: myorthomd-web, enovis-plugins
Scanned: {N}/{total} searches succeeded

## Key Takeaways

- {3-5 bullets: what's relevant to which project, what's worth trying}

## For myorthomd-web

| Project | What | Stars | URL | Verdict |
|---------|------|-------|-----|---------|
| Herb 0.9 | HTML-aware ERB linter/formatter | 5k+ | github.com/marcoroth/herb | Try on ERB templates |

## For enovis-plugins

| Project | What | Stars | URL | Verdict |
|---------|------|-------|-----|---------|
| sqlite-fts5-tool | FTS5 query builder | 2k+ | github.com/... | Could improve Trello search |

## Plugins

| Project | What | Stars | URL | Installed? | Verdict |
|---------|------|-------|-----|------------|---------|
| Superpowers | TDD/planning enforcement | 29k | github.com/obra/superpowers | No | Try on one task |

## General Dev Tools

| Project | What | Stars | URL | Verdict |
|---------|------|-------|-----|---------|
```

Also print a short summary (3-5 lines) to the conversation.

### Phase 5: Update Config

Update `last_scan` in `~/.tech-radar.json` to today's date. (Skip if no-config mode.)

## No-Config Mode

When `~/.tech-radar.json` doesn't exist:
- Run generic queries only: trending dev tools, Claude Code plugins, HN signal
- Group as "Plugins" and "General Dev Tools" only (no per-project sections)
- At the end, suggest: "Run `/tech-radar:setup` from your project directories to get project-specific results next time."

## Error Handling

- Individual WebSearch failures: continue, report at top of output
- Obsidian config missing: print results to conversation instead of writing file
- Zero results after filtering: write a note saying "no notable results this period"

## Quality Rules

- Verdicts are natural language, not standardized vocabulary ("Try on one CoffeeScript migration" not "Try now")
- Star counts are approximate from web results — use tiers not exact numbers
- Executive summary is the most important section — make it actionable
- Don't include tools the user obviously already knows about
- Tag verdicts to specific projects when possible ("useful for myorthomd-web's Bootstrap migration")
