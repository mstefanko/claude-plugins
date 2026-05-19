# Plugin Convention Review — Validating the Task-Fit/Split Plan Against the Wild

Date: 2026-05-19

Status: research memo (fact-finding only; no recommendations)

## Scope Note

The plan under review
(`bakeoff/docs/plugin-task-fit-and-split-plan-2026-05-19.md`) does **not**
propose marketplace restructuring. It proposes adding two advisory behaviors
inside the existing Bakeoff plugin layer:

1. A task-fit warning in `skills/bakeoff/SKILL.md` and `commands/run.md`.
2. A clean-split suggestion that drafts 2–3 separate normal work-order files.

The research below therefore checks two distinct things in parallel:

- (A) Does the **plan's intra-plugin design** (skill + command + advisory gates,
  no new schema, no orchestration) match how other Claude Code plugins are
  built?
- (B) Does the **existing marketplace** (`mstefanko-plugins/.claude-plugin/
  marketplace.json`) match conventions seen elsewhere? (The user asked for this
  comparison even though the plan does not change it.)

## Primary Sources Consulted

- Anthropic docs — Create plugins
  (`https://docs.claude.com/en/docs/claude-code/plugins`)
- Anthropic docs — Discover plugins
  (`https://docs.claude.com/en/docs/claude-code/discover-plugins`)
- Anthropic docs — Skills
  (`https://docs.claude.com/en/docs/claude-code/skills`)
- Anthropic official marketplace
  (`anthropics/claude-code/.claude-plugin/marketplace.json`,
  `plugins/{code-review,feature-dev,frontend-design,ralph-loop,
  code-simplifier,claude-md-management}` directories)
- wshobson/agents (35.6k stars) marketplace
  (`wshobson/agents/.claude-plugin/marketplace.json`, 80 plugins)
- davila7/claude-code-templates (27.4k stars) — discovery patterns
- Locally installed: `context-mode`, `enovis-trello`, `enovis-playwright`,
  `enovis-circleci`, `enovis-context`, `ralph-loop`, `frontend-design`,
  `claude-md-management`, `code-simplifier`

## A) Plan's Intra-Plugin Design vs. Conventions

### Skill + Command Co-location

Plan: keep one skill at `skills/bakeoff/SKILL.md` and one command at
`commands/run.md`; new behavior goes into both files.

Convention: standard. Anthropic's own `feature-dev` plugin has the same shape
(`commands/` + `agents/` under one plugin root, single README). `code-review`
ships just `commands/` and a README. `claude-opus-4-5-migration` ships only a
`skills/` directory. Both shapes are blessed by the docs:

> Plugin structure: `plugin-name/{commands,agents,skills,hooks,.claude-plugin}`
> (Anthropic docs — Create plugins)

The plan's choice not to add new dirs or sibling skills is consistent with how
single-purpose Anthropic plugins are organized.

### Skill That Defines Policy, Command That Executes

Plan: `SKILL.md` becomes the shared policy ("Task Fit And Clean Splits"
section); `commands/run.md` becomes the executable behavior.

Convention: matches the dominant pattern. `enovis-trello` does exactly this —
`skills/trello/SKILL.md` carries cache/query semantics, `commands/search.md`,
`commands/card.md`, etc. carry the per-invocation argument mapping and call
sites. Same shape in `enovis-context` and `enovis-circleci`. Anthropic's own
docs frame skills as "model-invoked" policy and commands as the user-facing
entry point.

### Advisory Confirmation Gates In Natural-Language Drafting

Plan: the command asks "Continue anyway?" / "Reply `yes` to continue, or tell
me what to change." before writing JSON, then again before running.

Convention: this exact pattern is already in Bakeoff's `commands/run.md`
("Natural Language Drafting" → "Write and run this work order? Reply `yes`")
and is used identically in wshobson's plugins (the README calls it "Protocol
Orchestrator — slash commands pause at checkpoints for user approval"). It is
not novel.

### No New Schema, No DAG, No Cross-Run Synthesis

Plan: rejects work-order-list schemas, decomposition agents, DAGs, and merge
agents.

Convention: most popular plugins keep the orchestration surface small.
Anthropic's `code-review` is the heaviest orchestration in the official
marketplace; it launches 4-5 parallel subagents under one command but writes
no cross-run state. `feature-dev` uses a 7-phase sequential flow but again
keeps state per command and asks for user confirmation between phases. No
official plugin ships a multi-work-order schema or DAG runner. The plan's
rejection list is consistent with what doesn't exist in the wild.

### `${CLAUDE_PLUGIN_ROOT}` For Binaries

Bakeoff already uses `${CLAUDE_PLUGIN_ROOT}/bin/bakeoff` in `commands/run.md`.

Convention: matches `ralph-loop` (`Bash(${CLAUDE_PLUGIN_ROOT}/scripts/
setup-ralph-loop.sh:*)`) and is the documented variable for binary lookup.

### Verdict on (A)

The plan's design aligns with established community + Anthropic conventions on
every axis: one skill + one command per single-purpose plugin, advisory yes/no
gates, no new schema, no DAG, named binary via `CLAUDE_PLUGIN_ROOT`. No
divergence from convention identified.

## B) Existing Marketplace vs. Conventions

### `marketplace.json` Shape

Local file: `{name, description, owner.name, plugins:[{name, source,
description, category}]}` for 4 plugins.

Convention:

- **Anthropic official** (`anthropics/claude-code/.claude-plugin/
  marketplace.json`) includes a top-level `$schema`, `version`, and richer
  per-plugin metadata: `version`, `author.{name,email}`, `category`. Example:
  `{"name":"code-review","version":"1.0.0","author":{"name":"Boris Cherny",
  "email":"boris@anthropic.com"},"source":"./plugins/code-review","category":
  "productivity"}`.
- **wshobson** (1.6.0, 80 plugins) uses `{name, source, description, version,
  author.{name,email,url}, homepage, license, category}` per plugin and groups
  under `metadata.{description,version}`.
- **context-mode** uses the same — `metadata.{description,version}`,
  per-plugin `version`, `author`, `category`, `keywords`.

Local divergences from these:

- No top-level `$schema` reference (Anthropic uses
  `https://json.schemastore.org/claude-code-marketplace.json`).
- No top-level `metadata.version` or per-plugin `version`.
- No per-plugin `author`, `homepage`, `license`, or `keywords`.
- Owner block has only `name`, no `email`/`url`.

These are all optional fields — the docs allow the minimal shape — but the
richer form is what every popular published marketplace uses. Note the plan
does not propose changing any of this.

### Plugin Name vs. Directory Name

Local: `swarmdaddy` ships from `./swarm-do`. All other plugins match: name ==
directory.

Convention: directory and plugin `name` matching is the strong convention in
both Anthropic's repo (`code-review/` → `name:"code-review"`) and wshobson's
repo (every one of 80 plugins matches). The local
`swarmdaddy`/`swarm-do` split is a divergence; the project CLAUDE.md
explicitly calls it out as a gotcha. The Anthropic docs do not forbid the
mismatch (the slash command namespace comes from `name`, not the directory),
but no major published marketplace has been observed doing it.

### Plugin Granularity

Local: 4 plugins, ranging from a single-skill plugin (obsidian-notes,
tech-radar) to a multi-agent orchestration plugin (swarmdaddy with 14 commands,
23 agents, 1 skill).

Convention: both directions exist.

- Coarse: Anthropic's `feature-dev` (1 command, ~6 agents, README) is
  comparable in size to swarmdaddy.
- Fine: wshobson explicitly markets "80 focused plugins" with "granular
  installation and minimal token usage" as the design goal — each plugin is
  scoped to one domain (e.g., `debugging-toolkit`, `git-pr-workflows`,
  `backend-development`).

The plan does not propose splitting Bakeoff further, and convention supports
either direction; what matters is internal cohesion.

### Plugin-to-Plugin Dependencies

Local: none declared. Skills reference siblings only at the workflow level
(e.g., `claude-md-management` notes that it can be used by `swarmdaddy`).

Convention: the docs document **no** mechanism for declaring plugin-to-plugin
dependencies in `plugin.json` or `marketplace.json`. wshobson with 80 plugins
has none. Anthropic's 10+ plugins have none. The pattern is: plugins are
independent; coordination happens via skill discovery and the SkillTool runtime.

## Documented Best Practices (from Anthropic docs)

Direct quotes paraphrased from the indexed docs:

- "Use plugins when you want to share … namespaced skills like
  `/my-plugin:hello`."
- "Skills are model-invoked: Claude automatically uses them based on the task
  context."
- Plugin structure is `{commands,agents,skills,hooks,.claude-plugin}` —
  presence of each subdir is optional.
- Skills are recommended to "include a `description` so Claude knows when to
  use the skill" — the convention is descriptive sentence starting with the
  trigger noun ("Reviews code for…", "Greet the user…") and listing trigger
  phrases (context-mode's SKILL.md is an extreme but accepted form).
- `version`, `author`, `category` are recommended for marketplace plugins;
  none is strictly required by the loader, but every published marketplace
  examined includes them.

## Anti-Patterns Observed Elsewhere

These showed up in surveyed plugins; useful to flag for any future Bakeoff
work, but the current plan triggers none of them.

1. **Drift between plugin `name` and folder name** — wshobson, Anthropic, and
   context-mode all keep them identical. Local `swarmdaddy` / `swarm-do`
   already diverges; this is the only observed local instance and it requires
   a CLAUDE.md gotcha note to compensate.
2. **Mega-skill SKILL.md as a kitchen sink** — context-mode crams 30+ trigger
   phrases into the description block. Useful for hook routing, but blurs
   what the skill actually does. Bakeoff's existing SKILL.md is already
   focused; the plan's "Task Fit And Clean Splits" addition is bounded.
3. **Plugins that overlap functionally** — wshobson has `backend-development`,
   `api-scaffolding`, `backend-api-security` with overlapping agent rosters;
   users can't easily tell which to install. No equivalent overlap in the
   local marketplace.
4. **Hidden orchestration with implicit cross-run state** — observed in
   smaller community plugins that chain `bash` calls without showing each
   invocation. Anthropic's `code-review` avoids this by listing the agents and
   their scoring explicitly. The plan's "show all JSON before writing" rule
   is the same disciplined pattern.
5. **Skipping confirmation gates for write/run actions** — community plugins
   sometimes auto-execute. Anthropic, wshobson, and existing Bakeoff all
   require explicit user approval. The plan preserves this.

## Plan-Specific Alignment Table

| Plan element | Anthropic-official equivalent | wshobson equivalent | Convention status |
|---|---|---|---|
| Task-fit advisory warning | `feature-dev` Phase 1 "clarifying questions" gate | "Protocol Orchestrator … pause at checkpoints" | Established |
| Clean-split suggestion (2-3 work orders) | None — but `code-review`'s parallel-agent split has the same scope-fit reasoning at the agent level | wshobson's agent-orchestration plugin proposes parallel scopes manually | Established (no published schema) |
| No new work-order-list schema | Matches: no Anthropic plugin ships multi-task batch schemas | Matches: wshobson uses separate slash commands per task | Established |
| Sequential execution of split parts | Matches: `feature-dev` is sequential | Matches: wshobson "Protocol Orchestrator" is sequential | Established |
| Plugin layer holds policy; Go CLI unchanged | Matches: Anthropic plugins are markdown-heavy, binary-light | Matches: wshobson plugins are pure markdown | Established |

## Sources (mapped to claims)

- `RAW: anthropics official marketplace.json` — confirms top-level `$schema`,
  per-plugin `version`/`author`/`category`.
- `RAW: anthropics code-review plugin.json`, `RAW: anthropics feature-dev
  plugin.json` — confirm minimal `plugin.json` shape `{name, version,
  description, author}`.
- `RAW: wshobson marketplace.json` — confirms 80-plugin granular catalog,
  `{name, source, description, version, author, homepage, license, category}`
  per plugin.
- `GitHub: anthropics official plugins dir` — confirms standard layout
  `{.claude-plugin, commands, agents, skills, hooks, .mcp.json, README.md}`.
- `GitHub: anthropics code-review plugin`, `feature-dev plugin` — confirm
  one-command-with-N-agents pattern, sequential phased gates.
- `GitHub: wshobson/agents` — confirms "Protocol Orchestrator … pause at
  checkpoints for user approval, same disciplined flow as Claude Code"
  language and 153-skill granular approach.
- `Anthropic docs: plugins overview` — confirms `--plugin-dir` testing,
  namespacing rules, optional `version`/`author`/`category` fields.
- `Anthropic docs: skills` — confirms skill frontmatter `description` is the
  primary trigger surface; trigger-phrase lists are accepted form.
- `marketplace_json` (local) — confirms current 4-plugin shape with
  `swarmdaddy` → `./swarm-do` divergence.
- `bakeoff/commands/run.md` head + `bakeoff/skills/bakeoff/SKILL.md` head —
  confirm existing "Write and run this work order? Reply `yes`" pattern that
  the plan extends.
- `ralph_loop_command_head` — confirms `argument-hint`, `allowed-tools`,
  `${CLAUDE_PLUGIN_ROOT}` patterns the plan implicitly relies on.

## Status: COMPLETE
