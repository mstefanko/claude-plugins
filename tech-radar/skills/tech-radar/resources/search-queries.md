# Search Query Templates

Query templates organized by scan tier. Variables are substituted at scan time from `~/.tech-radar.json`.

## Variables

Global:
- `{month}` — current month name (e.g., "April")
- `{year}` — current year (e.g., "2026")
- `{quarter_start}` — ISO date of quarter start (e.g., "2026-01-01")
- `{interests}` — joined global interest keywords

Per-project (generate one query per project that has matching keywords):
- `{backend}` — joined backend keywords for a specific project
- `{frontend}` — joined frontend keywords for a specific project
- `{migrating_to}` — joined migration target keywords for a specific project
- `{migrating_from}` — joined migration source keywords for a specific project

## Weekly (4-5 searches)

Core stack monitoring. Run on `--weekly` and all longer scans.

| # | Query Template | Scope | Purpose |
|---|---------------|-------|---------|
| 1 | `trending github {backend} {month} {year}` | per-project | Backend ecosystem |
| 2 | `trending github javascript {frontend} {month} {year}` | per-project (skip if no frontend) | Frontend ecosystem |
| 3 | `claude code plugins new {month} {year}` | global | Plugin ecosystem |
| 4 | `new {migrating_to} tools {month} {year}` | per-project (skip if no migrations) | Migration target tools |

**Query generation:** For N registered projects, weekly generates up to 2N+1 queries (backend + frontend per project, plus 1 global plugin query). Projects with empty `frontend` or `migrating_to` arrays skip those queries.

## Monthly (add 4-5 more, 8-10 total)

Broader ecosystem scan. Run on default (no flag) and quarterly.

| # | Query Template | Scope | Purpose |
|---|---------------|-------|---------|
| 5 | `best new {backend} developer tools {year}` | per-project | Stack-specific tooling |
| 6 | `site:news.ycombinator.com "{backend}" {month} {year}` | per-project (use primary keyword only) | Hacker News signal |
| 7 | `npm packages trending {frontend} {month} {year}` | per-project (skip if no frontend) | JS package ecosystem |
| 8 | `{interests} open source tools {month} {year}` | global | Interest-based discovery |

## Quarterly (add 4-5 more, 12-14 total)

Deep scan including upgrade paths and migration planning.

| # | Query Template | Scope | Purpose |
|---|---------------|-------|---------|
| 9 | `{backend} upgrade path {year}` | per-project (use framework keyword) | Framework upgrade planning |
| 10 | `{migrating_from} to {migrating_to} migration tools {year}` | per-project (skip if no migrations) | Migration tooling |
| 11 | `{migrating_from} replacement alternatives {year}` | per-project (skip if no migrations) | Replacement discovery |
| 12 | `github ".claude-plugin" in:path created:>{quarter_start}` | global | New Claude plugins on GitHub |

## No-Config Fallback Queries

When `~/.tech-radar.json` doesn't exist, use these generic queries:

| # | Query Template | Purpose |
|---|---------------|---------|
| 1 | `trending github developer tools {month} {year}` | General dev tools |
| 2 | `claude code plugins new {month} {year}` | Plugin ecosystem |
| 3 | `site:news.ycombinator.com "developer tools" {month} {year}` | HN signal |
| 4 | `best new open source tools for developers {year}` | Broad discovery |

## Notes

- All queries run in the main thread via WebSearch (subagents cannot use WebSearch)
- Individual query failures are expected — continue with partial results
- Queries are intentionally broad; filtering happens in Phase 3 of the scan
- Per-project queries use that project's stack keywords — tag results back to the originating project
- Dedup across projects: if the same tool appears in queries for two projects, list it under both
