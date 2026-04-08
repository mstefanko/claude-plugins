# tech-radar

Scan trending repos, Claude Code plugins, and ecosystem tools against your tech stack. Produces a ranked Obsidian note grouped by project relevance.

## Setup

```
/tech-radar:setup              # discover git repos and register projects
/tech-radar:setup --list       # show registered projects and stacks
/tech-radar:setup --remove X   # remove a project from the registry
```

Auto-discovers git repos from common locations (`~/`, `~/code/`, `~/projects/`, plugin marketplaces) and presents a list to choose from. Analyzes `Gemfile`, `package.json`, and `CLAUDE.md` to extract tech stacks. Run from anywhere — no need to be in the project directory.

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
