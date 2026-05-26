# tech-radar

Persistent technology radar for tracking trending GitHub repos, Claude Code
plugins, Hacker News signals, and curated verticals against your own project
stack. It stores scan history in SQLite, lets Claude add durable verdicts, and
can export the latest state to Obsidian or browse it in an interactive
dashboard.

## What It Does

- Discovers repos from GitHub Search, GitHub Code Search, HN Algolia, and optional curated vertical sources.
- Matches discoveries to registered projects from `~/.tech-radar.json`.
- Persists scans, repo snapshots, verdicts, annotations, and full-text indexes in `~/.tech-radar/radar.db`.
- Tracks new vs. returning repos, star deltas, rising stars, under-the-radar repos, and skipped rejected repos.
- Supports a Claude-assisted workflow for verdict writing and optional Reddit validation.
- Exports saved scan results to an Obsidian-flavored Markdown note.
- Provides a Textual dashboard for browsing, searching, and triaging repos.

## Prerequisites

- Python 3.8+.
- Python dependencies from this plugin:

  ```bash
  pip3 install -r ~/.claude/plugins/marketplaces/mstefanko-plugins/tech-radar/scripts/requirements.txt
  ```

- GitHub authentication for practical API limits. Token resolution order:
  1. `GITHUB_TOKEN`
  2. `gh auth token`
  3. Unauthenticated fallback, limited to 4 GitHub queries with delays

  ```bash
  gh auth login
  # or
  export GITHUB_TOKEN=ghp_your_token_here
  ```

- Optional Obsidian output config from the `obsidian-notes` plugin. If `~/.obsidian-notes.json` is missing, export prints Markdown to stdout.

## Quick Start

For the Claude slash-command workflow:

```text
/tech-radar:setup
/tech-radar:scan
/tech-radar:dashboard
```

For direct CLI usage:

```bash
cd ~/.claude/plugins/marketplaces/mstefanko-plugins/tech-radar

scripts/tech-radar gather --timeframe monthly --source all
scripts/tech-radar status
scripts/tech-radar evaluate pending
scripts/tech-radar export
scripts/tech-radar dashboard
```

The first successful `gather` creates `~/.tech-radar/radar.db` automatically.

## Setup

`/tech-radar:setup` is a Claude slash-command workflow, not a local CLI
subcommand. It discovers local git repositories, reads project files such as
`Gemfile`, `package.json`, `CLAUDE.md`, `Dockerfile`, and `docker-compose.yml`,
then writes the selected project stack data to `~/.tech-radar.json`.

```text
/tech-radar:setup              # discover and add projects
/tech-radar:setup --list       # show registered projects and stacks
/tech-radar:setup --remove app # remove one registered project
```

Setup is optional for the CLI to run, but strongly recommended. Without
`~/.tech-radar.json`, the current gather code has no project stack, interests,
phrases, or verticals to search. It can still run, but discovery is mostly
limited to plugin code search and any defaults the slash-command workflow adds
outside the CLI.

## Slash Commands

Slash commands are Claude-facing workflow wrappers. They call the local CLI where
appropriate, then use Claude for the judgment-heavy pieces.

```text
/tech-radar:setup              # discover projects and update ~/.tech-radar.json
/tech-radar:scan               # monthly scan workflow
/tech-radar:scan --weekly      # last 7 days
/tech-radar:scan --quarterly   # last 90 days
/tech-radar:dashboard          # open the interactive browser/TUI dashboard
/tech-radar:status             # show database statistics
/tech-radar:search <query>     # search stored repos or verdicts
/tech-radar:annotate ...       # set watching/tested/adopted/rejected/archived
/tech-radar:evaluate ...       # prepare or save Claude verdicts
/tech-radar:export             # re-export an existing scan
/tech-radar:migrate            # import legacy history.json data
```

Important distinction: there is no `scripts/tech-radar scan` CLI subcommand.
`/tech-radar:scan` is the orchestrated Claude workflow. The local CLI subcommand
that gathers API data is `scripts/tech-radar gather`.

## Current Workflow

1. `gather` loads config, builds GitHub and HN queries, fetches data, tags repos, computes scan deltas, and writes the scan to SQLite.
2. `evaluate pending` returns the latest repos that need Claude verdicts, including project and vertical context.
3. Claude writes verdict JSON and `evaluate save` persists it to the database. Saved verdicts clear `needs_verdict`.
4. `export` renders the saved database state as Markdown.
5. `dashboard`, `search`, and `annotate` support ongoing triage between scans.

The CLI does not call Claude or WebSearch by itself. Reddit validation, nuanced
verdicts, and key takeaways happen in the slash-command workflow, then are saved
back to SQLite.

## CLI Reference

All CLI examples assume this working directory:

```bash
~/.claude/plugins/marketplaces/mstefanko-plugins/tech-radar
```

### `gather`

Scan GitHub and/or HN, then persist results to SQLite.

```bash
scripts/tech-radar gather \
  --timeframe monthly \
  --source all \
  --max-repos 90
```

Useful flags:

- `--timeframe weekly|monthly|quarterly` - lookback window, default `monthly`.
- `--source github|hn|all` - source selection, default `all`.
- `--max-repos N` - cap selected main repos, default `90`.
- `--dry-run` - use fixture data instead of network APIs, but still writes to the selected database.
- `--show-queries` - print generated GitHub and HN queries without scanning.
- `--no-fuzzy` - disable `rapidfuzz` matching and use exact/synonym matching only.
- `--config PATH` - config path, default `~/.tech-radar.json`.
- `--db PATH` - database path, default `~/.tech-radar/radar.db`.

### `status`

Show database stats:

```bash
scripts/tech-radar status
```

Outputs schema version, repo count, scan count, snapshot count, verdict count,
annotation count, pending verdict count, and latest scan date.

### `evaluate`

Prepare pending repos for Claude and save verdicts.

```bash
scripts/tech-radar evaluate pending

cat verdicts.json | scripts/tech-radar evaluate save \
  --tokens-in 12000 \
  --tokens-out 2400 \
  --web-searches 4
```

Verdicts should include `full_name`, `verdict_text`, and `project_relevance`.
They may also include `reddit_validation` and `recommendation`. A
`recommendation` of `investigate` auto-annotates an unannotated repo as
`watching`; `reject` auto-annotates it as `rejected`.

### `export`

Render a saved scan to Markdown:

```bash
scripts/tech-radar export
scripts/tech-radar export --date 2026-04-10
scripts/tech-radar export --output /tmp/tech-radar.md
scripts/tech-radar export --output -
```

If no output path is provided, export uses `~/.obsidian-notes.json` when present:

```text
{vault_path}/{notes_dir}/{scan_date}-tech-radar.md
```

Without Obsidian config, it prints the report to stdout.

### `dashboard`

Launch the Textual dashboard:

```bash
scripts/tech-radar dashboard
scripts/tech-radar dashboard --web
scripts/tech-radar dashboard --kill
```

Behavior:

- In cmux, opens a right split pane.
- In an interactive terminal, runs the TUI directly.
- In a non-interactive shell, starts `textual-serve` and prints a localhost URL.
- Uses singleton state in `~/.tech-radar/dashboard.pid` and `~/.tech-radar/dashboard-pane.json`.

Dashboard features:

- Tabs: All, Latest, Watching, Tested, Adopted, Rejected.
- Full-text search over stored repos.
- Project filter and vertical filter.
- Sort by stars, growth delta, category, or name.
- Detail preview with verdicts, project relevance, annotation notes, HN context, and growth sparkline.
- Keyboard triage: `w` watch, `t` tested, `a` adopted, `r` reject, `o` open URL, `c` copy URL, `?` help.

### `annotate`

Mark a repo with a durable status:

```bash
scripts/tech-radar annotate rails/rails watching --notes "Track framework direction"
scripts/tech-radar annotate hotwired/turbo adopted --notes "Used in production"
scripts/tech-radar annotate owner/repo rejected --reason "Not relevant"
```

Statuses:

- `watching` - always gets refreshed verdicts.
- `tested` or `adopted` - gets refreshed only after larger star movement.
- `rejected` - skipped by future gathers and hidden from default dashboard browsing.
- `archived` - retained for history but separated from active triage.

### `search`

Search SQLite FTS indexes:

```bash
scripts/tech-radar search "rails deployment"
scripts/tech-radar search "migration pain" --table verdicts
```

### `migrate`

Import legacy pre-SQLite history:

```bash
scripts/tech-radar migrate
scripts/tech-radar migrate --history ~/.tech-radar/history.json
```

This imports old `history.json` data into `~/.tech-radar/radar.db` and renames
the original file to `history.json.bak`. New installs do not need this.

## Config

Main config lives at `~/.tech-radar.json`. Setup is optional for command
execution, but the current code depends on config for stack, interest, phrase,
and vertical discovery.

Current fields used by the code:

```json
{
  "projects": {
    "my-app": {
      "path": "/Users/me/my-app",
      "backend": ["ruby", "rails", "postgres"],
      "frontend": ["stimulus", "turbo", "bootstrap"],
      "infra": ["docker"],
      "migrating_from": ["jquery"],
      "migrating_to": ["hotwire"]
    }
  },
  "interests": ["healthcare", "hipaa", "claude-code"],
  "phrase_queries": ["design system", "generative UI"],
  "min_stars": 1000,
  "verticals": {
    "selfhosted": {
      "min_stars": 100,
      "seed_repos": ["awesome-selfhosted/awesome-selfhosted"],
      "github_topics": ["self-hosted"],
      "awesome_lists": ["awesome-selfhosted/awesome-selfhosted"],
      "code_searches": []
    },
    "mcp": {
      "min_stars": 50,
      "seed_repos": [],
      "github_topics": ["mcp"],
      "awesome_lists": [],
      "code_searches": ["filename:mcp.json"]
    }
  }
}
```

Notes:

- `projects` drives stack matching and per-project report sections.
- `interests` drives wildcard discovery using recently pushed repos.
- `phrase_queries` are searched as exact multi-word phrases.
- `min_stars` defaults to `1000`.
- `verticals` are optional external source pipelines. Each vertical can pull from seed repos, GitHub topics, code search, and awesome-list READMEs.
- Older configs may still contain fields such as `installed_plugins` or `last_scan`; the current gather/export code does not use them.

## Data Model

Primary state lives in `~/.tech-radar/radar.db`.

Tables:

- `scans` - one row per gather run, with timeframe, query counts, source metadata, and aggregate counts.
- `repos` - canonical repo metadata keyed by `full_name`.
- `scan_snapshots` - per-scan repo facts such as stars, deltas, category, project matches, HN context, and `needs_verdict`.
- `verdicts` - Claude-generated verdicts and project relevance.
- `annotations` - human or auto annotations such as watching, tested, adopted, rejected, or archived.
- `meta` - schema version.
- FTS tables for repo and verdict search.

`~/.tech-radar/history.json` is legacy-only now. Use `migrate` if you have old
history data.

## Discovery And Ranking

The gather pipeline:

- Builds stack queries from registered project keywords.
- Batches GitHub `OR` terms to avoid GitHub's operand limits.
- Uses `created:>` for stack discovery and `pushed:>` for interests and phrase queries.
- Runs plugin discovery through GitHub Code Search for `.claude-plugin/plugin.json`.
- Queries HN Algolia from backend keywords, interests, and phrase queries.
- Optionally enriches verticals from seed repos, topics, code searches, and awesome lists.
- Fuzzy-matches repo text with exact, synonym, and `rapidfuzz` matching.
- Treats keywords shared by 3 or more projects as broad, so they do not force a project match.
- Scores stack matches highest, then plugins, verticals, interests, and general tools.
- Preserves category diversity when selecting the final repo set.
- Ensures registered projects with available matches get coverage when possible.

Categories currently used by the code include:

- `stack-match`
- `plugin`
- `interest-match`
- `general`
- vertical categories such as `frontend`, `selfhosted`, and `mcp`

Under-the-radar and rising-star flags are stored separately from category.

## Report Output

`export` generates Markdown from database state. The report includes:

- Frontmatter with `type`, `project`, `date`, and `tags`.
- Sources and scan counts.
- Key Takeaways from saved scan metadata when present; otherwise the current exporter prints a placeholder prompt.
- Per-project sections for matched repos.
- Plugins.
- Under the Radar.
- Rising Stars.
- Wild Cards.
- HN Highlights for repos with saved HN context.
- General Dev Tools.

The exported report reflects persisted verdicts and annotations. Re-run `export`
after changing annotations or saving new verdicts; no API calls are needed.

## Development And Testing

Inspect generated queries without network calls:

```bash
scripts/tech-radar gather --show-queries
```

Run a fixture-backed scan into a disposable database:

```bash
scripts/tech-radar gather --dry-run --db /tmp/tech-radar-dry-run.db
scripts/tech-radar status --db /tmp/tech-radar-dry-run.db
scripts/tech-radar export --db /tmp/tech-radar-dry-run.db --output -
```

Run dashboard query tests:

```bash
PYTHONPATH=scripts python3 -m unittest scripts.tests.test_dashboard_queries
```

If any command fails with `No module named 'sqlite_utils'`, `textual`, or
`rapidfuzz`, install `scripts/requirements.txt` with the same Python interpreter
used to run `scripts/tech-radar`.

## Files

- `scripts/tech-radar` - executable CLI entry point.
- `scripts/tech_radar/cli.py` - argparse subcommands and dashboard launch behavior.
- `scripts/tech_radar/gather.py` - GitHub/HN gathering, matching, scoring, diffing, and DB writes.
- `scripts/tech_radar/db.py` - SQLite schema, persistence helpers, FTS, annotations, and migration.
- `scripts/tech_radar/evaluate.py` - pending verdict selection and verdict persistence.
- `scripts/tech_radar/export.py` - Markdown export.
- `scripts/tech_radar/dashboard.py` - Textual dashboard.
- `scripts/tech_radar/sources.py` - optional vertical discovery sources.
- `commands/*.md` - Claude slash-command workflows.
- `skills/tech-radar/SKILL.md` - Claude skill instructions for running the radar workflow.
