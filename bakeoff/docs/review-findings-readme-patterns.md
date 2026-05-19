# README Pattern Findings — for `bakeoff` Rewrite

Surveyed 15 READMEs from adjacent spaces (AI agent frameworks, AI dev tools,
modern CLI tools, developer tooling, GitHub Actions). Each project is cited
with a URL in section 5.

## 1. Common structural pattern

Nearly every strong README I surveyed follows a 6–9 section sequence. Roughly:

1. **Header block** — logo or wordmark, one-line tagline, badge row
   (license / version / CI / community). Usually centered HTML.
2. **One-paragraph "what is this"** — plain prose, 2–4 sentences. Names the
   category, the audience, and the one big claim. (Bun, Vite, LangGraph, uv,
   Ruff, Tauri, Claude Code all do this.)
3. **Highlights / Why use this** — short bulleted list, bolded lead-ins, links
   on each bullet to deeper docs. 6–10 bullets is typical. (uv "Highlights",
   pnpm bullets, LangGraph "Why use LangGraph?", Ruff emoji bullets.)
4. **Install** — copy/paste-able commands with platform tabs. Always before
   any conceptual content. (Claude Code, Bun, uv, Ollama.)
5. **Quickstart / Get started** — smallest possible "hello world" that
   produces a visible result. Usually 3–8 lines of code. (Aider, AutoGen,
   CrewAI, Ollama, Tauri.)
6. **Usage / Features deep-dive** — short prose blocks linking out to docs,
   not in-line walls of config. (Aider icons grid, uv link-per-feature,
   Cline product matrix.)
7. **Comparison / Benchmark** (optional) — when the project competes with an
   incumbent. Hard numbers, one chart. (uv "10–100x faster", pnpm benchmark,
   Ruff benchmark image.)
8. **Docs / Quick links** — explicit "read the docs" pointer near the top
   AND at the bottom. (Bun, Vite, LangGraph.)
9. **Community / Support / Contributing / License** — boilerplate footer.

The dominant ordering rule: **show me something to copy/paste before you show
me a philosophy section.** Install + Quickstart come before "why".

## 2. Tone recommendation for bakeoff

**Recommended voice — direct, technical, restrained-confident; no
buzzwords, no breathless adjectives, no marketing voice. Write like a senior
engineer explaining the tool to another engineer on a Slack thread.**

Five concrete sentence examples in the recommended voice:

1. "Bakeoff runs competing or cooperating Claude Code agents through a
   phased pipeline backed by a `bd` issue tracker."
2. "Use `/bakeoff:run` with a natural-language description, or point it at a
   work-order file. Either way you see the full JSON and approve it before
   anything writes to disk."
3. "Build mode generates competing implementations against the same work
   order, then a judge ranks them. The runner never mutates your tree —
   you pick the winner and apply it yourself."
4. "Review mode produces a structured findings report. No code changes, no
   PR comments — just evidence-cited markdown."
5. "If you only ever use one command, use `/bakeoff:quickstart`."

This voice is closest to **uv**, **Ruff**, **Bun**, and **Claude Code**.
Avoid the CrewAI / AutoGen marketing register ("empowers developers",
"enterprise-grade", "lightning-fast").

## 3. Length guidance

- **Aim for ~250–400 lines of markdown total.** uv, Ruff, Bun, and Vite all
  land in this range. Claude Code is shorter (~100 lines) because it offloads
  aggressively to external docs — also a valid pattern.
- **Brevity wins** for: the tagline, the "what is this" paragraph,
  install steps, quickstart, and the first feature list.
- **More detail is justified** for: the section that explains the one
  feature that makes the tool different (for bakeoff: the phased pipeline +
  non-mutation boundary). Even there, prefer prose + a single example over
  exhaustive config tables.
- **Push everything else to `docs/`.** CLI reference, schema details,
  phase-by-phase config, advanced flags. Link to them; do not inline them.
- **Hard rule:** a new user should reach a runnable command within the
  first screen (roughly 50 lines).

## 4. What to AVOID

Anti-patterns I observed and that the bakeoff rewrite should not repeat:

- **Leading with architecture.** AutoGen's current README opens with a
  maintenance-mode banner, then installation, then philosophy buried below.
  Bakeoff's current README leads with CLI architecture before the user
  knows what to do. Bad.
- **Corporate-speak.** "empowers developers", "enterprise-grade",
  "lightning-fast", "production-ready" — CrewAI and parts of AutoGen lean
  on this. It reads like a vendor brochure and erodes trust.
- **Wall-of-config dumps.** GitHub Actions `checkout` inlines its entire
  YAML interface in the README. Bakeoff has the same temptation with work-
  order schemas — resist it. Link instead.
- **Sponsor block before the product.** pnpm pushes Platinum / Gold sponsor
  tables above any usage content. For a personal plugin, this is wrong
  shape.
- **Walls of HTML tables.** Cline's nested centered tables work because they
  have five products to index; for a single-binary plugin, plain markdown
  beats `<table>`.
- **Missing or buried quickstart.** Tauri ships you to an external site for
  any usage at all. Acceptable if your docs are world-class; risky otherwise.
- **Feature lists that don't link out.** A bulleted highlight list with no
  per-bullet link forces the reader to scroll for detail. uv and aider get
  this right — every bullet is a doc link.
- **Mixing audience signals.** AutoGen's "we're in maintenance mode, also
  here's how to install us, also use this other framework" buries the lede.
  Pick one primary CTA per README.
- **No "what does this output?" answer.** For an agent/orchestration tool,
  users need to know what artifacts come out the other side. Bakeoff should
  state this per workflow (research → memo, review → findings markdown,
  build → competing diffs).
- **Hiding the safety boundary.** Bakeoff's "build mode does not mutate
  your tree" is a trust feature. State it explicitly and early; do not
  bury it in section 9.

## 5. Citations — which project exemplifies which pattern

| Pattern | Best example(s) | URL |
|---|---|---|
| Short, punchy tagline + 1-paragraph "what is this" | Bun, Vite | https://github.com/oven-sh/bun · https://github.com/vitejs/vite |
| Linkified highlights bullet list | uv, Ruff | https://github.com/astral-sh/uv · https://github.com/astral-sh/ruff |
| Install-first, then quickstart | Claude Code, Ollama, Bun | https://github.com/anthropics/claude-code · https://github.com/ollama/ollama |
| Minimal "hello world" code block | AutoGen, Aider, CrewAI | https://github.com/microsoft/autogen · https://github.com/Aider-AI/aider |
| Comparison / "replaces X, Y, Z" framing | uv, Ruff, pnpm | https://github.com/astral-sh/uv · https://github.com/pnpm/pnpm |
| "Why use this?" section with linked sub-bullets | LangGraph | https://github.com/langchain-ai/langgraph |
| Product matrix table (for multi-surface tools) | Cline | https://github.com/cline/cline |
| Offload aggressively to docs site | Tauri, Vite, Bun, Claude Code | https://github.com/tauri-apps/tauri · https://github.com/vitejs/vite |
| Iconographic feature grid | Aider | https://github.com/Aider-AI/aider |
| Restrained, engineer-to-engineer tone | uv, Ruff, Claude Code, Bun | (above) |
| Buzzword-heavy tone to AVOID | CrewAI, parts of AutoGen | https://github.com/joaomdmoura/crewAI · https://github.com/microsoft/autogen |
| Wall-of-config to AVOID | actions/checkout | https://github.com/actions/checkout |

## 6. Direct application to bakeoff

The rewrite should:

- Open with a one-paragraph "what is bakeoff" — name the category
  ("multi-agent orchestration plugin for Claude Code"), the mechanism
  ("phased pipelines backed by a `bd` issue tracker"), and the safety
  property ("run never mutates your tree; you approve before anything
  writes").
- Follow uv's "Highlights" pattern: 6–8 bullets, each one a doc link.
- Put `/plugin install` and `/bakeoff:quickstart` in a code block within
  the first screen.
- Give Research / Review / Build each its own short section with
  (a) one-line purpose, (b) one example invocation, (c) named output
  artifact, (d) link to deeper docs.
- Defer the schema, CLI reference, evidence/citation format, and phase
  internals to `docs/`.
- Use the engineer-to-engineer voice from section 2. No "empower",
  "seamless", "lightning-fast", "production-grade". State capabilities
  flatly and let them stand.
