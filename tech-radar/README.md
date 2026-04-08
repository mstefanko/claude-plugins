# tech-radar

Scan trending repos, Claude Code plugins, and ecosystem tools against your tech stack. Produces a ranked Obsidian note grouped by project relevance.

## Setup

```
/tech-radar:setup
```

Run from any project directory to register its tech stack. Reads `Gemfile`, `package.json`, and `CLAUDE.md` to extract keywords. Additive — run from multiple projects to build a registry.

**Setup is optional.** Scan works without it using generic queries.

Requires `obsidian-notes` plugin for file output (`/obsidian-notes:setup` if not configured).

## Usage

```
/tech-radar:scan              # monthly (default, 8-10 searches)
/tech-radar:scan --weekly     # quick scan (4-5 searches)
/tech-radar:scan --quarterly  # broad scan with upgrade paths (12-14 searches)
```

Results are grouped by project ("For myorthomd-web", "For enovis-plugins") and written to your Obsidian vault.

## Config

`~/.tech-radar.json` — multi-project registry with per-project tech stacks, global interests, and installed plugin tracking. Created by `/tech-radar:setup`, never written to project repos.
