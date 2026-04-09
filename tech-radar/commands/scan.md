---
description: "Scan trending tools and repos against your tech stack"
argument-hint: "[--weekly | --quarterly]"
---

# Tech Radar Scan

Run a hybrid scan for trending tools, repos, and plugins. A Python script gathers structured data from GitHub and Hacker News APIs, then Claude writes verdicts and validates findings via targeted Reddit searches.

**Works without setup.** If `~/.tech-radar.json` doesn't exist, runs generic queries and suggests running `/tech-radar:setup` afterward.

## Arguments

- No argument: monthly scan (default, last 30 days, 8-10 searches)
- `--weekly`: quick scan (last 7 days, 4-5 searches)
- `--quarterly`: broad scan (last 90 days, 12-14 searches, includes upgrade paths)

## Process

### Phase 1: Load Context

1. Read `~/.tech-radar.json` — if missing, enter **no-config mode** (see below)
2. Read `~/.obsidian-notes.json` — need `vault_path` and `notes_dir` for output. If missing, print results to conversation only.
3. Determine timeframe from arguments (monthly/weekly/quarterly)

### Phase 2: Gather Data via Script

1. Run the gathering script via Bash:
   ```
   $CLAUDE_PLUGIN_ROOT/scripts/tech-radar-gather --timeframe {tf} --source all --config ~/.tech-radar.json --history-dir ~/.tech-radar/
   ```
   - In no-config mode, omit the `--config` flag (script falls back to generic queries)
2. Capture the JSON output from stdout
3. Check `meta.sources` — if a source has `status: "error"`, note it in the report header and optionally fall back to 2-3 WebSearches for that source's coverage area

### Phase 3: Reddit Validation (Targeted)

For items in the JSON with `reddit_validate: true`, run targeted WebSearch queries:

- **Hard cap: 6 WebSearches maximum**
- **Priority order:**
  1. Divisive HN stories first
  2. Anomalous growth (>100% `stars_delta_pct`)
  3. Under-the-radar items
  4. Wild cards
- **Query pattern:** `site:reddit.com "{topic or repo name}" 2026`
- For divisive HN items: synthesize both sides of the debate (HN position vs Reddit position)
- For under-the-radar/wild cards: validate genuine community interest
- Skip Reddit validation entirely if there are no flagged items

### Phase 4: Write Report

Write to `{vault_path}/{notes_dir}/{YYYY-MM-DD}-tech-radar.md`:

```
---
type: note
project: tech-radar
date: {today}
tags: [tech-radar, {timeframe}]
---

# Tech Radar — {Month Year}

Sources: GitHub API ({N}/{total}), HN Algolia ({N}/{total}), Reddit validation ({N} searches)
New this scan: {meta.history.new_this_scan} | Seen before: {meta.history.returning} | Rising: {meta.history.rising}

## Key Takeaways
- {3-5 actionable bullets — synthesize the most important findings across all sections}

## For {project-name}
| Project | What | ★ | Δ | New? | URL | Verdict |
|---------|------|---|---|------|-----|---------|
{For each repo with category=stack-match matching this project. Include stars, stars_delta if not null, is_new badge, and write a verdict that's specific to the project.}

{Repeat for each registered project that has matching repos. Skip projects with no matches.}

## Plugins
| Plugin | What | ★ | URL | Installed? | Verdict |
|--------|------|---|-----|------------|---------|
{category=plugin repos}

## Discovery & Inspiration

### Under the Radar 🔬
{category=under-the-radar items, max 5}
- **owner/repo** (★ {stars}, {stars_per_day} ★/day, {age} days old) — {description}
  {If hn_crossref: "HN: {title} ({points} pts)."}
  {If Reddit validated: "Reddit: {synthesis}."}
  {Verdict}

### Rising Stars ↑
{category=rising-star items, max 5. Empty on first scan — say "No history yet — rising stars appear after your second scan."}
- **owner/repo** (★ {stars}, +{stars_delta_pct}% since last scan, seen {scans_seen} scans) — {description}. {Verdict}

### Wild Cards 🃏
{category=interest-match items, max 5}
- **owner/repo** (★ {stars}) — {description}
  {If Reddit validated: "Reddit: {synthesis}."}
  {Verdict — focus on "could this inspire a new project/plugin/app?"}

### HN Highlights 🔥
{hn_stories sorted by points, max 5}
- **{title}** ({points} pts, {comments} comments{if divisive: " — divisive"}) — {1-line summary}
  {If divisive AND Reddit validated: "Community split: {HN take} vs {Reddit take}."}
  → {Verdict, tag to relevant project if applicable}

## General Dev Tools
| Project | What | ★ | New? | URL | Verdict |
|---------|------|---|------|-----|---------|
{category=general items}
```

Also print a short summary (3-5 lines) to the conversation after writing the file.

### Phase 5: Update Config

Update `last_scan` in `~/.tech-radar.json` to today's date. (Skip if no-config mode.)

## No-Config Mode

When `~/.tech-radar.json` doesn't exist:
- Run `tech-radar-gather` without the `--config` flag (script falls back to generic queries)
- Only show **Plugins**, **HN Highlights**, and **General Dev Tools** sections (no per-project sections, no Discovery & Inspiration)
- At the end, suggest: "Run `/tech-radar:setup` from your project directories to get project-specific results next time."

## Error Handling

- **Script fails entirely** (non-zero exit): fall back to the WebSearch-only approach from `resources/search-queries.md`
- **Individual sources fail** (`meta.sources.X.status == "error"`): note it in the report header, continue with available data
- **Obsidian config missing:** print results to conversation instead of writing file
- **Zero results after filtering:** write a note saying "no notable results this period"

## Quality Rules

- Verdicts are natural language, specific to projects when possible ("useful for myorthomd-web's Bootstrap migration" not "Try now")
- Star counts come from the script data — use real numbers, not tiers
- Executive summary (Key Takeaways) is the most important section — make it actionable
- Don't include tools the user obviously already knows about
- Tag verdicts to specific projects when possible
- If vault config missing, print report to conversation instead of file
