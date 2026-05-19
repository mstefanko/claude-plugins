# Review Findings: Existing Content Inventory vs. README Plan

Date: 2026-05-18
Scope: cross-check `docs/user-friendly-readme-rewrite-plan-2026-05-18.md` against the actual
surfaces shipped by the `bakeoff` plugin at this checkout, and flag concrete material that
should appear in the new README but is not enumerated in the plan.

---

## 1. Project Surface Inventory (ground truth from the checkout)

### 1.1 Plugin manifests

- `.claude-plugin/plugin.json` — Claude marketplace manifest. Fields present:
  `name=bakeoff`, `version=0.0.0`, `description`, `author.name=mstefanko`, `license=MIT`,
  `keywords=[bakeoff, research, build, competitive, judge, claude, codex, multi-agent]`.
- `.codex-plugin/plugin.json` — Codex marketplace manifest (parallel). Adds an `interface`
  block: `displayName="Bakeoff"`, `category="Productivity"`, `capabilities=["CLI"]`, plus a
  `defaultPrompt` list with three canned prompts (create work order, run doctor, inspect
  latest report). This means **bakeoff ships as both a Claude Code plugin and a Codex
  plugin from the same checkout**.

### 1.2 Slash commands (commands/*.md)

Five slash commands, each with frontmatter `description`, `argument-hint`, `allowed-tools`:

| File             | Slash                | Argument hint                                                                  |
|------------------|----------------------|--------------------------------------------------------------------------------|
| `quickstart.md`  | `/bakeoff:quickstart`| (none)                                                                          |
| `run.md`         | `/bakeoff:run`       | `<work-order-path \| request> [--run-id ID] [--out runs] [--quiet] [--keep-worktrees] [--no-triage]` |
| `doctor.md`      | `/bakeoff:doctor`    | `[--skip-auth-probe] [--build] [--quiet]`                                       |
| `inspect.md`     | `/bakeoff:inspect`   | `[latest \| run-id]` (inferred)                                                  |
| `uninstall.md`   | `/bakeoff:uninstall` | (none)                                                                          |

Each command's `allowed-tools` is narrowly scoped (e.g., `run.md` only allows
`bakeoff validate|research|build`, `git status|diff|rev-parse`, plus standard FS tools).

### 1.3 Skills (skills/*)

- `skills/bakeoff/SKILL.md` — single skill, `name=bakeoff`, `version=0.0.0`,
  `allowed-tools=Read,Write,Edit,Glob,Grep,Bash`, with trigger phrases for "bakeoff,
  /bakeoff, run a bakeoff, compare providers, inspect a bakeoff run, code-review bakeoff,
  or competitive build bakeoff." Contains operating contract (do/don't around git apply,
  budgets, heartbeat, output caps, summarization expectations).

### 1.4 Agents / Hooks

- **None.** There is no `agents/` and no `hooks/` directory. The plugin is purely
  command+skill+CLI.

### 1.5 CLI binary surface (`bin/bakeoff` launcher → Go binary)

Top-level subcommands defined in `internal/commands/`:

| Subcommand            | Source                                | Use string                          |
|-----------------------|----------------------------------------|--------------------------------------|
| `bakeoff validate`    | `validatecmd/validate.go`              | `validate WORK_ORDER`                |
| `bakeoff research`    | `researchcmd/research.go`              | `research WORK_ORDER`                |
| `bakeoff build`       | `buildcmd/build.go`                    | `build WORK_ORDER`                   |
| `bakeoff show`        | `showcmd/show.go`                      | `show RUN_ID`                        |
| `bakeoff triage`      | `triagecmd/triage.go`                  | `triage RUN_ID`                      |
| `bakeoff ls`          | `lscmd/ls.go`                          | `ls`                                 |
| `bakeoff runs verify` | `runscmd/runs.go`                      | `runs verify RUN_ID`                 |
| `bakeoff doctor`      | `doctorcmd/doctor.go`                  | `doctor`                             |
| `bakeoff init`        | `initcmd/init.go`                      | `init {gather\|compare\|analyze\|review\|build}` |
| `bakeoff rerun`       | `reruncmd/rerun.go`                    | `rerun SOURCE_RUN_ID`                |

Launcher script `bin/bakeoff` resolves the binary in this order:
`$BAKEOFF_GO_BINARY` → `$ROOT/dist/bakeoff` → `go run ./cmd/bakeoff`. Errors out if Go is
absent and no built binary exists.

Helper script `scripts/bakeoff-ensure-cli` performs the same probe with `--check` mode
(returns dist binary path or version probe) and otherwise builds `dist/bakeoff` if Go is
available.

### 1.6 Example work orders (examples/*.work-order.json)

Five concrete sample work orders shipped in-repo, one per type/facet:
`analyze.work-order.json`, `build.work-order.json`, `compare.work-order.json`,
`gather.work-order.json`, `review.work-order.json`. These are immediately copy-pasteable
and currently invisible to anyone reading the README.

### 1.7 Configuration surface

- Env vars in launcher and CLI:
  `CLAUDE_PLUGIN_ROOT`, `BAKEOFF_GO_BINARY`, `BAKEOFF_PLUGIN_ROOT`, `CODEX_PLUGIN_ROOT`,
  `NO_COLOR`, `GOCACHE` (auto-set to `/tmp/bakeoff-go-cache` for `go run`).
- Plugin-internal settings (`.claude/settings.local.json`): allowlists context-mode MCP
  tools — not user-facing, but documents that **bakeoff's dev workflow expects
  context-mode**.
- Work-order schema knobs surfaced in `SKILL.md`/CLAUDE.md: `wall_clock_seconds`,
  `heartbeat_seconds`, `max_output_bytes`, `max_output_overrun_bytes`,
  `output_cap_grace_seconds`, `scope_policy.enforcement="best_effort"`,
  `build.base_ref`, `build.patch_max_bytes` (default `100000`), `build.verify[].kind`
  in `{gate, metric}`.

### 1.8 External dependencies / runtimes

- **Go ≥ 1.24.0** (`go.mod`), or a prebuilt `dist/bakeoff` binary.
- **`claude` and `codex` provider CLIs** — must be installed and authenticated separately;
  bakeoff never stores credentials.
- **`git`** — required for review-context capture and competitive-build worktrees.
- Go deps: `spf13/cobra v1.10.2`, `golang.org/x/sync v0.18.0`.
- Optional dev: `python3` for `scripts/parity-go.py` parity harness; `pytest` for the
  parity fixtures under `tests/parity/`.

### 1.9 Existing docs and rationale

`docs/` already contains rich rationale documents the plan only loosely references:

- `competitive-builds-evidence-2026-05-18.md` — full citations behind build mode.
- `competitive-builds-plan-audit-2026-05-18.md`, `…-implementation-plan-…`,
  `…-phase-6-dogfood-…` — design history for build mode.
- `faceted-research-implementation-plan-2026-05-15.md` — faceted research rationale.
- `post-judge-triage-implementation-plan-2026-05-14.md` — triage design.
- `heartbeat-observability-implementation-plan-2026-05-15.md` — heartbeat/budget rationale.
- `review-context-and-run-manifest-implementation-plan-2026-05-16.md` — review-context
  capture rationale.
- `research-go-cli-patterns-…`, `research-go-idioms-and-antipatterns-…`,
  `research-cli-languages-…`, `research-llm-languages-…` — language/CLI selection notes.
- `review-findings-readme-patterns.md`, `review-findings-plan-critique.md` — meta-docs the
  plan author used.

### 1.10 Repository artifacts / runtime state directories

- `runs/<run-id>/` — primary output directory; full per-run ledger.
- `*.work-order.json` in cwd — drafted work orders.
- `dist/bakeoff` — locally built CLI.
- `tests/parity/` — fixtures + fakes; not user-facing.
- `internal/` — 27 Go subpackages (apperror, artifact, buildinfo, buildverify,
  buildworkspace, cli, commands, decision, fsutil, jsonutil, ledger, manifest, output,
  prompt, provider, report, reviewcontext, runner, runnerenv, runresult, runstatus, scope,
  summary, triage, verify, workorder). Not user-facing but indicates the surface depth.

### 1.11 Marketplace + install paths the existing README documents

- `/plugin marketplace add mstefanko-plugins <abs path>` — marketplace registration.
- `/plugin marketplace update mstefanko-plugins`, `/plugin install bakeoff@mstefanko-plugins`,
  `/reload-plugins`.
- Plugin cache path: `~/.claude/plugins/cache/mstefanko-plugins/bakeoff`.

---

## 2. What the Plan Covers

The plan (`user-friendly-readme-rewrite-plan-2026-05-18.md`) proposes an outline that
covers:

- High-level "what is Bakeoff" + workflow-first narrative.
- Quickstart: marketplace add, install, reload, `/bakeoff:quickstart`.
- Slash-command table (the same five `/bakeoff:*` commands).
- Request-routing matrix (NL → work-order type/facet).
- Three workflow sections: Research (gather/compare/analyze), Review (code-review facet),
  Build (competitive build).
- Per-workflow: when to use, example prompts, what bakeoff drafts, flow diagrams,
  expected artifacts, evidence-based rationale with collapsible citations.
- Ledger/artifact table (run-id paths).
- Build-mode "what it does NOT do" boundary section.
- Troubleshooting (doctor variants, exit code `3` meaning).
- Progressive-disclosure principle, deferring schema/CLI-flag/parity details to
  `docs/cli-reference.md`, `docs/work-order-schema.md`, `docs/research-basis.md`,
  `docs/architecture.md`.
- Acceptance criteria + non-goals.

---

## 3. What the Plan MISSES (high-value gaps the README should still address)

For each gap: where it lives in the code, why a user needs it, and where it belongs in the
new README.

### 3.1 The plugin is dual-target (Claude Code AND Codex)

- Where: `.codex-plugin/plugin.json` with its own `displayName`, `category`,
  `capabilities`, `defaultPrompt`. Launcher honors `CODEX_PLUGIN_ROOT`.
- Why users need it: Codex users currently get **no signal** that this plugin is
  installable on their side. The Claude-only framing in the README orphans half the
  audience.
- New README location: a one-paragraph "Works with Claude Code and Codex" note in the
  intro, plus a Codex install snippet near the Claude install snippet.

### 3.2 The `examples/` directory of ready-to-run work orders

- Where: `examples/{analyze,build,compare,gather,review}.work-order.json` (5 files).
- Why users need it: copy-paste running. The plan keeps full schema details out of the
  README, which is fine, but examples are the bridge between "draft from NL" and "edit
  the JSON yourself." Currently nobody knows these files exist.
- New README location: a one-line callout under Quick Start: "Five sample work orders
  ship in `examples/` — `bakeoff validate examples/build.work-order.json` is a safe
  smoke test."

### 3.3 Full slash-command argument hints

- Where: command frontmatter `argument-hint:` fields, especially `run.md`'s
  `[--run-id ID] [--out runs] [--quiet] [--keep-worktrees] [--no-triage]`.
- Why users need it: the plan's command table omits flags. `--keep-worktrees` and
  `--no-triage` change run behavior materially.
- New README location: expand the command table; also called out under Build (for
  `--keep-worktrees`) and Review (for `--no-triage`).

### 3.4 Full CLI subcommand list (10 subcommands, not the 8 the plan listed)

- Where: `internal/commands/` enumerates `validate, research, build, show, triage, ls,
  runs verify, doctor, init, rerun`. The plan's `docs/cli-reference.md` list is missing
  `init` and `rerun`.
- Why users need it: `bakeoff init <type>` and `bakeoff rerun <run-id>` are the two
  ways power users skip the slash-command layer entirely (scaffold a work order without
  Claude; replay a prior run with a new run-id). Both are user-facing.
- New README location: extend the existing "underlying CLI" sub-section. Mention
  `bakeoff init` and `bakeoff rerun` by name with one-line descriptions.

### 3.5 Launcher resolution order and `scripts/bakeoff-ensure-cli`

- Where: `bin/bakeoff` (3-step probe: `BAKEOFF_GO_BINARY` → `dist/bakeoff` → `go run`)
  and `scripts/bakeoff-ensure-cli [--check]`.
- Why users need it: tells them exactly what to expect on first run, why `quickstart`
  works or fails, and how packagers should ship a binary. The plan does not mention the
  helper script by name.
- New README location: "How the CLI is found" callout inside Install or Prerequisites.

### 3.6 The `BAKEOFF_GO_BINARY` / `BAKEOFF_PLUGIN_ROOT` / `CODEX_PLUGIN_ROOT` env vars

- Where: `bin/bakeoff`, scattered references in README and SKILL.
- Why users need it: vendoring, CI, side-by-side testing of binary builds.
- New README location: Config & Environment section with a one-line role per variable.
  Plan mentions environment matrix only as "deferred to docs"; keeping the five common
  knobs in the README is appropriate for power users.

### 3.7 Uninstall scope and what is NOT removed

- Where: existing README "Uninstall" section + `commands/uninstall.md` content.
- Why users need it: avoid surprise — uninstall does not touch provider CLIs, provider
  auth, git branches, user commits, non-bakeoff `runs/`, or dev binaries `./bakeoff` and
  `./bakeoff-go`.
- New README location: keep a short Uninstall section. The plan currently does not list
  Uninstall in the proposed outline. Add it after Troubleshooting.

### 3.8 Provider-auth boundary and secrets policy

- Where: existing README lines 32–34 and SKILL.md security rules.
- Why users need it: explicit statement that Bakeoff never owns credentials, never
  accepts API keys in work orders, and never writes secrets into prompts/summaries.
  This is a trust-relevant claim that should not be buried in a deeper doc.
- New README location: a short callout inside Prerequisites or just below it.

### 3.9 `scope_policy.enforcement: "best_effort"` rationale

- Where: SKILL.md and existing README. Plan lists `scope_policy` only in the
  schema-doc deferral list.
- Why users need it: explains why the CLI sometimes produces warnings instead of hard
  failures when providers stray out of scope, and how to tighten or loosen it.
- New README location: a sentence in the Research workflow section ("How Bakeoff drafts
  work orders") — the plan already promises this section, it just doesn't enumerate
  the field.

### 3.10 Exit-code semantics beyond code `3`

- Where: `internal/cli/exit.go`, `internal/apperror/`. The plan mentions exit code `3`
  but ignores the rest (validation error, scope error, provider error, schema error,
  timeout, cancelled, missing-provider — all enumerated in `tests/parity/fixtures/`).
- Why users need it: scripting and CI integration. The plan defers all of these to
  `docs/cli-reference.md`, but a 4-row exit-code table in the README is cheap and
  high-value.
- New README location: Troubleshooting subsection, after the `--build` doctor note.

### 3.11 Heartbeat / output-cap / wall-clock budget knobs

- Where: SKILL.md operating contract; schema fields `heartbeat_seconds`,
  `wall_clock_seconds`, `max_output_bytes`, `max_output_overrun_bytes`,
  `output_cap_grace_seconds`.
- Why users need it: long-running build runs hit these. The plan defers all schema to
  `docs/work-order-schema.md`. At minimum, the README should name the four knobs and
  point at the schema doc.
- New README location: a one-paragraph "Budgets and timeouts" note in the
  Configuration section.

### 3.12 Plugin works as a **Skill**, not just commands

- Where: `skills/bakeoff/SKILL.md` with explicit trigger phrases ("compare providers",
  "code-review bakeoff", etc.).
- Why users need it: many users invoke skills indirectly by phrasing rather than
  remembering slash commands. The plan does not mention the skill at all.
- New README location: "How to invoke" subsection right after Commands. Two lines: "You
  can either type `/bakeoff:run …` or describe what you want — the bakeoff skill is
  triggered by phrases like 'compare providers', 'run a bakeoff', 'code-review
  bakeoff'."

### 3.13 Codex `defaultPrompt` examples

- Where: `.codex-plugin/plugin.json` ships three default prompts.
- Why users need it: gives Codex users an instant starting point. The plan only
  considers Claude.
- New README location: include in the dual-target Install section (3.1).

### 3.14 Dependencies on `git` for review and build modes specifically

- Where: review-context capture, build-mode worktree creation. README mentions `git`
  but does not say *which* operations require it.
- Why users need it: users running on detached checkouts, shallow clones, or non-git
  trees need to know what will fail.
- New README location: Prerequisites bullet expansion: "git is required for review
  (diff/base capture) and build (worktree isolation). Research runs that do not
  request review-context do not need git."

### 3.15 Where artifacts go for **review** runs specifically

- Where: `runs/<run-id>/review-context.{md,json}` and `runs/<run-id>/triage/`.
- Why users need it: review users specifically want the triaged output. The plan's
  ledger table includes the rows, but the Review workflow section should reiterate the
  two paths they will read most often.
- New README location: explicit "what to open after a review run" tip inside the
  Review workflow section.

### 3.16 Where artifacts go for **build** runs and the single canonical winner path

- Where: `runs/<run-id>/providers/<winner>/build/diff.patch`.
- Why users need it: this is the single most important output path for build mode.
- New README location: bold callout in the Build section, repeated under
  "Artifacts" — the plan currently shows it in the table but does not pull it up.

### 3.17 Development/parity harness

- Where: `scripts/parity-go.py`, `tests/parity/fixtures/`, `go test ./...`,
  `go test -race ./...`.
- Why users need it: contributors only. The plan correctly punts this to
  `docs/architecture.md`. But the **existing** README has a Development section; keep
  a 3-line version of it in the README with a pointer to the deeper doc, otherwise
  contributors will not know to look.
- New README location: short Development section at the end, deferring details to
  `docs/architecture.md`.

### 3.18 The "thin launcher" rationale

- Where: existing README opening + CLAUDE.md + SKILL.md ("Bakeoff is CLI-first. The
  Claude Code plugin is intentionally thin…").
- Why users need it: explains *why* the plugin will not apply patches, commit, or
  publish — a question that recurs.
- New README location: the plan does flag this; verify the new README opens with one
  sentence stating CLI-first design before any schema or flow detail.

---

## 4. Draft-Ready Snippets the Writer Can Lift

### 4.1 Slash-command table (corrected with full arg hints)

```markdown
| Command                                                              | Purpose                                                                              |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `/bakeoff:quickstart`                                                 | Build or locate the CLI, then run a readiness check without provider auth probes.    |
| `/bakeoff:run <path \| request> [--run-id ID] [--out runs] [--quiet] [--keep-worktrees] [--no-triage]` | Validate and run an existing work order, or draft one from natural language. |
| `/bakeoff:inspect [latest \| run-id]`                                  | Inspect existing ledgers, reports, decisions, triage, and build handoff artifacts.   |
| `/bakeoff:doctor [--skip-auth-probe] [--build] [--quiet]`             | Check provider and host readiness. `--build` runs live edit probes.                  |
| `/bakeoff:uninstall`                                                  | Remove Bakeoff-owned plugin state, then guide manual plugin uninstall.               |
```

### 4.2 CLI subcommand table (complete)

```markdown
| Subcommand                                       | Purpose                                              |
| ------------------------------------------------ | ---------------------------------------------------- |
| `bakeoff validate <work-order>`                  | Schema-validate a work order without running it.     |
| `bakeoff research <work-order>`                  | Run a research bakeoff (gather/compare/analyze/review). |
| `bakeoff build <work-order>`                     | Run a competitive build bakeoff in isolated worktrees. |
| `bakeoff show <run-id>`                          | Print a run's report and decision summary.           |
| `bakeoff triage <run-id>`                        | Run or re-run triage on a completed review.          |
| `bakeoff ls`                                     | List runs in `runs/`.                                |
| `bakeoff runs verify <run-id>`                   | Verify ledger manifest integrity for a run.          |
| `bakeoff doctor [--skip-auth-probe] [--build]`   | Readiness check.                                     |
| `bakeoff init {gather\|compare\|analyze\|review\|build}` | Scaffold a starter work order JSON.            |
| `bakeoff rerun <source-run-id>`                  | Replay a prior run with a new run-id.                |
```

### 4.3 Environment variable mini-table

```markdown
| Variable              | Role                                                                       |
| --------------------- | -------------------------------------------------------------------------- |
| `CLAUDE_PLUGIN_ROOT`  | Set by Claude Code. Read by plugin commands and scripts.                   |
| `CODEX_PLUGIN_ROOT`   | Set by Codex when installed there.                                         |
| `BAKEOFF_GO_BINARY`   | Optional: absolute path to a prebuilt `bakeoff` binary to use instead of building from source. |
| `BAKEOFF_PLUGIN_ROOT` | Developer/test override for the shared launcher.                           |
| `NO_COLOR`            | Standard CLI color suppression.                                            |
```

### 4.4 Example invocations (lifted from skill triggers + existing README)

```text
/bakeoff:quickstart
/bakeoff:run review this diff against main
/bakeoff:run compare these two approaches
/bakeoff:run build competing fixes for this failing test
/bakeoff:run examples/build.work-order.json
/bakeoff:inspect latest
/bakeoff:doctor --build
```

### 4.5 Exit-code mini-table (from fixtures under `tests/parity/fixtures/`)

```markdown
| Exit | Meaning                                                        |
| ---- | -------------------------------------------------------------- |
| 0    | Run completed and decision is conclusive.                      |
| 2    | Validation, schema, or scope error (work order rejected).      |
| 3    | Run completed but judge decision was unresolved (handoff, not failure). |
| 4    | Provider exit error (one or both providers failed to produce a usable artifact). |
| 5    | Cancelled or timed out before completion.                      |
```
(Confirm exact codes against `internal/apperror/` and `internal/cli/exit.go` before
publishing — the fixture names suggest these but I did not read the exit-code constants
directly.)

### 4.6 Codex install snippet

```text
# In Codex:
codex plugin marketplace add mstefanko-plugins <abs path>
codex plugin install bakeoff@mstefanko-plugins
```
(Confirm exact Codex command syntax — bakeoff ships a `.codex-plugin/plugin.json`, so
Codex install is supported, but verify the slash/CLI surface against current Codex docs.)

---

## 5. Quick Reference: top 10 gaps (priority order)

1. Dual Claude Code + Codex framing — currently invisible. (§3.1, §3.13)
2. `examples/*.work-order.json` exists and is copy-pasteable. (§3.2)
3. Two CLI subcommands missing from plan: `bakeoff init` and `bakeoff rerun`. (§3.4)
4. `/bakeoff:run` flags `--keep-worktrees`, `--no-triage`, `--run-id`, `--out`, `--quiet`
   are not in the plan's command table. (§3.3)
5. Skill (`skills/bakeoff/SKILL.md`) is invokable via NL phrases — plan doesn't mention
   it. (§3.12)
6. Launcher resolution order + `scripts/bakeoff-ensure-cli` helper. (§3.5)
7. Exit codes beyond `3`. (§3.10)
8. Uninstall scope + what is NOT removed. (§3.7)
9. `BAKEOFF_GO_BINARY` env var role (vendoring/CI). (§3.6)
10. Where review/build artifacts land specifically (`review-context.{md,json}`,
    `runs/<id>/providers/<winner>/build/diff.patch`). (§3.15, §3.16)

File: `/Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins/bakeoff/docs/review-findings-existing-content-inventory.md`
