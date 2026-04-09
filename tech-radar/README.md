# tech-radar

Scan trending repos, Claude Code plugins, and ecosystem tools against your tech stack. Produces a ranked Obsidian note grouped by project relevance.

## Prerequisites

- **Python 3.8+** — the gathering script uses only stdlib modules (no pip install needed)
- **GitHub authentication** — needed for GitHub Search API. The script auto-detects auth in this order:
  1. `GITHUB_TOKEN` env var (if set)
  2. `gh auth token` (if GitHub CLI is installed and authenticated)
  3. Falls back to unauthenticated mode (severely rate-limited, max 4 queries)

  If you have `gh` CLI installed (`brew install gh && gh auth login`), no extra setup is needed. Otherwise:

  ```bash
  # Add to your shell profile (~/.zshrc or ~/.bashrc)
  export GITHUB_TOKEN=ghp_your_token_here
  ```

  Create a token at https://github.com/settings/tokens with no special scopes (public repo access is sufficient).

- **`obsidian-notes` plugin** — for file output (`/obsidian-notes:setup` if not configured). Without it, results print to the conversation instead.

## Setup

```
/tech-radar:setup              # discover git repos and register projects
/tech-radar:setup --list       # show registered projects and stacks
/tech-radar:setup --remove X   # remove a project from the registry
```

Auto-discovers git repos from common locations (`~/`, `~/code/`, `~/projects/`, plugin marketplaces) and presents a list to choose from. Analyzes `Gemfile`, `package.json`, and `CLAUDE.md` to extract tech stacks. Run from anywhere — no need to be in the project directory.

**Setup is optional.** Scan works without it using generic queries.

## Usage

```
/tech-radar:scan              # monthly (default)
/tech-radar:scan --weekly     # quick scan (last 7 days)
/tech-radar:scan --quarterly  # broad scan with upgrade paths (last 90 days)
```

## How It Works

The scan uses a hybrid architecture:

1. **Python script gathers data** — queries GitHub Search API and HN Algolia API concurrently, deduplicates results, categorizes repos by your tech stack, and diffs against scan history
2. **Claude validates via Reddit** — runs up to 6 targeted WebSearches for divisive HN stories, anomalous growth repos, and wild cards
3. **Claude writes the report** — renders an Obsidian note with verdicts, key takeaways, and per-project grouping

## Report Sections

Results are grouped by project ("For myorthomd-web", "For enovis-plugins") plus these discovery sections:

- **Key Takeaways** — 3-5 actionable bullets synthesizing the most important findings
- **For {project}** — repos matching each registered project's tech stack
- **Plugins** — Claude Code plugin discoveries with installed/not-installed flags
- **Discovery & Inspiration:**
  - **Under the Radar** — young repos with unusually high growth (stars/day), cross-referenced with HN
  - **Rising Stars** — repos with significant star growth since your last scan (appears after second scan)
  - **Wild Cards** — repos matching your global interests that could inspire new projects
  - **HN Highlights** — top Hacker News stories with community sentiment synthesis
- **General Dev Tools** — everything else worth noting

## State & Config

- **`~/.tech-radar.json`** — multi-project registry with per-project tech stacks, global interests, and installed plugin tracking. Created by `/tech-radar:setup`, never written to project repos.
- **`~/.tech-radar/`** — state directory containing `history.json` for cross-scan persistence. Tracks which repos are new vs. returning, star count deltas, and scan counts. This is what powers the "Rising Stars" section.

## Testing

```bash
# Dry run — tests config parsing and query generation without making API calls
scripts/tech-radar-gather --dry-run

# Single source — test one API at a time
scripts/tech-radar-gather --timeframe monthly --source github --config ~/.tech-radar.json
scripts/tech-radar-gather --timeframe monthly --source hn --config ~/.tech-radar.json
```
