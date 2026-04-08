# Search Query Templates

Query templates organized by scan tier. Variables are substituted at scan time from `~/.tech-radar.json`.

Variables:
- `{month}` — current month name (e.g., "April")
- `{year}` — current year (e.g., "2026")
- `{quarter_start}` — ISO date of quarter start (e.g., "2026-01-01")
- `{backend}` — joined backend keywords (e.g., "ruby rails")
- `{frontend}` — joined frontend keywords (e.g., "stimulus turbo")
- `{migrating_to}` — joined migration target keywords
- `{migrating_from}` — joined migration source keywords
- `{interests}` — joined interest keywords

## Weekly (4-5 searches)

Core stack monitoring. Run on `--weekly` and all longer scans.

| # | Query Template | Purpose |
|---|---------------|---------|
| 1 | `trending github {backend} {month} {year}` | Backend ecosystem |
| 2 | `trending github javascript {frontend} {month} {year}` | Frontend ecosystem |
| 3 | `ruby toolbox trending gems {month} {year}` | Gem ecosystem |
| 4 | `new {migrating_to} tools {month} {year}` | Migration target tools |

## Monthly (add 4-5 more, 8-10 total)

Broader ecosystem scan. Run on default (no flag) and quarterly.

| # | Query Template | Purpose |
|---|---------------|---------|
| 5 | `claude code plugins new {month} {year}` | Plugin ecosystem |
| 6 | `best new rails developer tools {year}` | General Rails tooling |
| 7 | `site:news.ycombinator.com "rails" OR "ruby" {month} {year}` | Hacker News signal |
| 8 | `npm packages trending {frontend} {month} {year}` | JS package ecosystem |

## Quarterly (add 4-5 more, 12-14 total)

Deep scan including upgrade paths and migration planning.

| # | Query Template | Purpose |
|---|---------------|---------|
| 9 | `rails upgrade path {year}` | Framework upgrade planning |
| 10 | `{migrating_from} to {migrating_to} migration tools {year}` | Migration tooling |
| 11 | `{migrating_from} replacement alternatives {year}` | Replacement discovery |
| 12 | `github ".claude-plugin" in:path created:>{quarter_start}` | New Claude plugins on GitHub |

## Notes

- All queries run in the main thread via WebSearch (subagents cannot use WebSearch)
- Individual query failures are expected — continue with partial results
- Queries are intentionally broad; filtering happens in Phase 3 of the scan
- Stack keywords come from `~/.tech-radar.json` — run `/tech-radar:setup` to configure
