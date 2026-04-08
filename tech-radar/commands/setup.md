---
description: "Configure your tech stack for radar scans"
argument-hint: "[no arguments]"
---

# Tech Radar Setup

Create or update `~/.tech-radar.json` by analyzing the current project.

## Process

1. **Read project files** from the current working directory:
   - `Gemfile` — extract Ruby/Rails gems
   - `package.json` — extract npm packages
   - `CLAUDE.md` — extract mentioned technologies
   - Skip any that don't exist

2. **Extract tech keywords** from what you found:
   - Backend: language, framework, database, test framework
   - Frontend: JS framework, CSS framework, bundler
   - Infra: containerization, web server, CI
   - Migrating from/to: look for comments about upgrades, deprecated tech, or migration plans

3. **Check for existing config** at `~/.tech-radar.json`:
   - If exists, show current config and proposed changes
   - If new, show proposed config

4. **Ask user to confirm or edit** the extracted stack before saving

5. **Detect installed plugins** by listing directories in `~/.claude/plugins/marketplaces/*/` and extracting plugin names

6. **Write `~/.tech-radar.json`** with this schema:
   ```json
   {
     "stack": {
       "backend": ["ruby", "rails", "mysql", "rspec"],
       "frontend": ["stimulus", "turbo", "bootstrap", "esbuild"],
       "infra": ["docker", "caddy"],
       "migrating_from": ["coffeescript", "backbone", "jquery", "bootstrap 4"],
       "migrating_to": ["stimulus", "turbo", "bootstrap 5", "es6"]
     },
     "interests": ["healthcare", "hipaa", "hotwire"],
     "min_stars": 1000,
     "installed_plugins": ["claude-mem", "context-mode", "obsidian-notes"],
     "last_scan": null
   }
   ```

7. **Verify obsidian-notes config** exists at `~/.obsidian-notes.json` (needed for scan output). If missing, suggest running `/obsidian-notes:setup` first.

## Rules

- Never overwrite without showing the user what will change
- Merge new project tech with existing config if re-run from a different project
- `min_stars` defaults to 1000 if not set
- `last_scan` starts as null
