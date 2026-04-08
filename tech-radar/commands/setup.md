---
description: "Register a project's tech stack for radar scans"
argument-hint: "[no arguments — run from any project directory]"
---

# Tech Radar Setup

Add or update the current project in `~/.tech-radar.json`. Run from different project directories to build up a multi-project registry. **Setup is optional** — scan works without it, just without project-specific grouping.

## Process

1. **Detect project identity** from the current working directory:
   - Project name: basename of the git root (e.g., `myorthomd-web`, `enovis-plugins`)
   - Project path: absolute path to the git root
   - If not in a git repo, use the current directory name and path

2. **Read project files** to extract tech keywords:
   - `Gemfile` — Ruby/Rails gems, database adapters, test frameworks
   - `package.json` — npm packages, JS frameworks, bundlers
   - `CLAUDE.md` — mentioned technologies, migration plans
   - `docker-compose.yml` / `Dockerfile` — infra tools
   - Skip any that don't exist

3. **Extract tech keywords** into categories:
   - `backend` — language, framework, database, test framework, ORM
   - `frontend` — JS framework, CSS framework, bundler, asset pipeline
   - `infra` — containerization, web server, CI, deployment
   - `migrating_from` — deprecated tech, upgrade comments, old versions
   - `migrating_to` — target tech, migration plans, new versions

4. **Check for existing config** at `~/.tech-radar.json`:
   - If exists, load it and check if this project is already registered
   - If project exists: show current stack vs proposed changes, ask to confirm
   - If project is new: show proposed stack, ask to confirm before adding
   - If no config file: create fresh with this project as the first entry

5. **Ask user to confirm or edit** before saving. Show:
   - Project name and path
   - Extracted stack keywords by category
   - Global interests (suggest additions based on project domain)

6. **Detect installed plugins** by listing directories in `~/.claude/plugins/marketplaces/*/` and extracting plugin names. Update `installed_plugins` in config.

7. **Write `~/.tech-radar.json`** — merge this project into the existing registry:
   ```json
   {
     "projects": {
       "myorthomd-web": {
         "path": "/Users/mstefanko/myorthomd-web",
         "stack": {
           "backend": ["ruby", "rails", "mysql", "rspec"],
           "frontend": ["stimulus", "turbo", "bootstrap", "esbuild"],
           "infra": ["docker", "caddy"],
           "migrating_from": ["coffeescript", "backbone", "jquery", "bootstrap 4"],
           "migrating_to": ["stimulus", "turbo", "bootstrap 5", "es6"]
         }
       }
     },
     "interests": ["healthcare", "hipaa", "hotwire", "claude-code"],
     "min_stars": 1000,
     "installed_plugins": ["claude-mem", "context-mode", "obsidian-notes"],
     "last_scan": null
   }
   ```

8. **Verify obsidian-notes config** exists at `~/.obsidian-notes.json` (needed for scan output). If missing, suggest running `/obsidian-notes:setup` first — but this is a warning, not a blocker.

## Rules

- **Never writes to the project repo** — only `~/.tech-radar.json`
- **Additive** — running from a new project adds it; never removes existing projects
- Never overwrite without showing the user what will change
- `interests` are global (shared across projects) — suggest new ones based on project domain
- `min_stars` defaults to 1000 if not set
- `last_scan` preserved across updates
- To remove a project from the registry, user must explicitly ask
