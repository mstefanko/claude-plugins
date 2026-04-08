---
description: "Manage your tech radar project registry"
argument-hint: "[--list | --remove <project> | no args to add projects]"
---

# Tech Radar Setup

Discover git repos, register their tech stacks, and manage the project registry in `~/.tech-radar.json`. **Setup is optional** — scan works without it, just without project-specific grouping.

## Arguments

- No arguments: discover and add projects (interactive)
- `--list`: show registered projects and their stacks
- `--remove <project>`: remove a project from the registry

## Add Projects (default)

### Phase 1: Discover Git Repos

Scan common locations for git repositories:

1. `~/` — top-level home directory repos
2. `~/code/`, `~/projects/`, `~/dev/`, `~/src/`, `~/work/` — common dev directories
3. `~/.claude/plugins/marketplaces/*/` — plugin marketplaces

For each location, find directories containing `.git/` (one level deep — don't recurse into nested repos). Collect the list of discovered repos.

### Phase 2: Present Choices

Show the user a numbered list of discovered repos:

```
Found git repositories:
  1. myorthomd-web          ~/myorthomd-web
  2. enovis-plugins         ~/.claude/plugins/marketplaces/enovis-plugins
  3. mstefanko-plugins      ~/.claude/plugins/marketplaces/mstefanko-plugins
  4. dotfiles               ~/dotfiles

Already registered: (none)

Which projects to add? (comma-separated numbers, or "all"):
```

- Mark projects already in the registry so the user knows
- Already-registered projects can be re-selected to update their stack
- User picks by number, comma-separated, or "all"

### Phase 3: Analyze Selected Projects

For each selected project, read its files to extract tech keywords:

- `Gemfile` — Ruby/Rails gems, database adapters, test frameworks
- `package.json` — npm packages, JS frameworks, bundlers
- `CLAUDE.md` — mentioned technologies, migration plans
- `docker-compose.yml` / `Dockerfile` — infra tools
- Skip any that don't exist

Extract into categories:
- `backend` — language, framework, database, test framework, ORM
- `frontend` — JS framework, CSS framework, bundler, asset pipeline
- `infra` — containerization, web server, CI, deployment
- `migrating_from` — deprecated tech, upgrade comments, old versions
- `migrating_to` — target tech, migration plans, new versions

### Phase 4: Confirm & Save

Show the extracted stacks for all selected projects at once:

```
Proposed additions:

myorthomd-web (~/myorthomd-web)
  backend:        ruby, rails, mysql, rspec
  frontend:       stimulus, turbo, bootstrap, esbuild
  infra:          docker, caddy
  migrating_from: coffeescript, backbone, jquery, bootstrap 4
  migrating_to:   stimulus, turbo, bootstrap 5, es6

enovis-plugins (~/.claude/plugins/marketplaces/enovis-plugins)
  backend:        bash, node, typescript, sqlite
  frontend:       (none)
  infra:          (none)

Suggested interests: healthcare, hipaa, hotwire, claude-code

Confirm? (y/edit/cancel):
```

- User can confirm all, edit individual projects, or cancel
- Detect installed plugins from `~/.claude/plugins/cache/*/`
- Write to `~/.tech-radar.json`
- Verify `~/.obsidian-notes.json` exists (warning if missing, not a blocker)

## List Projects (`--list`)

Read `~/.tech-radar.json` and display:

```
Tech Radar Registry (3 projects)

myorthomd-web (~/myorthomd-web)
  backend:        ruby, rails, mysql, rspec
  frontend:       stimulus, turbo, bootstrap, esbuild
  migrating_from: coffeescript, backbone
  migrating_to:   stimulus, turbo, bootstrap 5

enovis-plugins (~/.claude/plugins/marketplaces/enovis-plugins)
  backend:        bash, node, typescript, sqlite

mstefanko-plugins (~/.claude/plugins/marketplaces/mstefanko-plugins)
  backend:        (none)

Global interests: healthcare, hipaa, hotwire, claude-code
Min stars: 1000
Last scan: 2026-04-08
```

If no config exists, say so and suggest running `/tech-radar:setup`.

## Remove Project (`--remove <name>`)

Remove a project from the registry by name:

1. Read `~/.tech-radar.json`
2. Find the project by name (case-insensitive match)
3. Show what will be removed and ask for confirmation
4. Remove the project entry and write the file
5. If that was the last project, keep the config file with empty `projects: {}`

## Rules

- **Never writes to project repos** — only `~/.tech-radar.json`
- **Additive by default** — add flow never removes existing projects
- Never overwrite without showing the user what will change
- `interests` are global (shared across projects) — suggest additions based on project domains
- `min_stars` defaults to 1000 if not set
- `last_scan` preserved across updates
- Repo discovery is best-effort — if a common directory doesn't exist, skip it silently
