# Bakeoff

Run the same research, review, or build task through Claude and Codex, then get an auditable report and replayable artifacts.

Bakeoff is a small launcher and CLI harness. It runs providers, captures artifacts, verifies or judges outputs, and writes a ledger. It does not auto-apply build patches or publish PRs.

This guide is for engineers trying Bakeoff from Claude Code or Codex. Use it from Claude Code with `/bakeoff:*`; this checkout also ships `.codex-plugin/plugin.json` for Codex.

## What You Use It For

| Workflow | Use it when | Example request | Result |
| --- | --- | --- | --- |
| Research | You need evidence, comparison, or explanation. | `/bakeoff:run compare these two approaches` | `report.md`, `decision.json`, provider artifacts. |
| Review | You want an actionable audit of a branch, PR, diff, or local changes. | `/bakeoff:run review this diff against main` | Review report plus triage artifacts. |
| Build | You want two isolated implementation candidates and a selected patch artifact. | `/bakeoff:run build competing fixes for this failing test` | Build report plus selected `diff.patch` when there is a canonical winner. |

## Prerequisites And Quick Start

Prerequisites: Claude Code with this plugin installed; `git` for review and build flows; authenticated `claude` and `codex` provider CLIs for live runs; Go 1.24+ unless you installed a package with `dist/bakeoff` or set `BAKEOFF_GO_BINARY`.

Provider auth belongs to provider CLIs. Bakeoff does not own or store credentials. Do not place secrets in work orders.

```text
/bakeoff:quickstart
```

Local development install:

```text
/plugin marketplace add mstefanko-plugins <path-to-mstefanko-plugins>
/plugin marketplace update mstefanko-plugins
/plugin install bakeoff@mstefanko-plugins
/reload-plugins
/bakeoff:quickstart
```

Codex note: this checkout includes `.codex-plugin/plugin.json`. Verify the current Codex plugin install flow in Codex before publishing package-specific install commands.

```text
/bakeoff:run research the auth retry behavior
/bakeoff:run review this diff against main
/bakeoff:run build competing fixes for this failing test
/bakeoff:run examples/build.work-order.json
```

`/bakeoff:run` accepts natural language or a work-order path. Natural-language drafts are shown in full JSON and require explicit approval before the plugin writes or runs them. Sample work orders live in `examples/`: `gather`, `compare`, `analyze`, `review`, and `build`.

`scripts/bakeoff-ensure-cli` and `/bakeoff:quickstart` find or build the CLI. The launcher resolution order is `BAKEOFF_GO_BINARY`, then `dist/bakeoff`, then `go run ./cmd/bakeoff`.

```text
You: /bakeoff:run review this diff against main
Bakeoff: I drafted a gather work order with facet.id = "code-review".
        Here is the JSON...
        Write and run this work order? Reply `yes` to continue, or tell me what to change.
You: yes
Bakeoff: validate -> research -> auto-triage
Bakeoff: report: runs/<run-id>/report.md
         triage: runs/<run-id>/triage/triage.md
         next: bakeoff show <run-id> --triage
```

## The Mental Model

```text
Your request
  -> work order
       existing file: validate and run
       natural language: draft JSON, show it, wait for approval
  -> two providers: Claude + Codex
  -> evidence phase
       research: judge merges or compares outputs
       review: judge merges findings, then triage verifies actionability
       build: gates, metrics, then swapped judge only if needed
  -> report + ledger
```

| If the user asks for | Bakeoff shape | What happens |
| --- | --- | --- |
| Fact-finding, source gathering, inventory, coverage | `type: "gather"` | Both providers collect evidence; the judge deduplicates and preserves citations. |
| Comparing options, vendors, APIs, designs, approaches | `type: "compare"` | Both providers argue the decision; swapped judging resolves a winner or tie. |
| Root cause, explanation, design analysis, synthesis | `type: "analyze"` | Both providers build explanation spines; the judge picks or merges the strongest spine. |
| Review, audit, check a PR, branch, diff, or local changes | `type: "gather"` with `facet.id: "code-review"` | Both providers inspect the same review scope; findings are deduped and triaged. |
| Candidate implementations, competing patches, failing-test fixes | `type: "build"` | Providers edit isolated worktrees; Bakeoff captures patches, runs verifiers, and selects only when evidence is conclusive. |

Review is not a separate work-order type. It is a `gather` run with a `code-review` facet.

## Research

Use Research for evidence collection, comparisons, and explanations.

| Type | Best for | What providers do | What the judge does |
| --- | --- | --- | --- |
| `gather` | Inventories and source-backed findings. | Answer the same coverage question with `codebase`, `web`, or `mixed` scope. | Dedupes overlapping claims and preserves citations. |
| `compare` | Choosing between options. | Evaluate the same options and tradeoffs. | Uses swapped A/B and B/A judging to pick a winner, consensus, or tie. |
| `analyze` | Root cause or architecture analysis. | Build explanation spines. | Chooses or merges the strongest spine and useful additions. |

```text
/bakeoff:run research how auth retry behavior works and cite the files involved
/bakeoff:run compare SQLite FTS vs Tantivy for local product search
/bakeoff:run analyze why provider output caps sometimes produce incomplete reports
```

```text
Research request
  -> classify as gather / compare / analyze
  -> draft or validate work order
  -> run Claude and Codex with the same task shape
  -> judge
       gather: merge claims
       compare: swapped A/B judging
       analyze: swapped spine judging
  -> report.md + decision.json + provider outputs
```

Inspect `runs/<run-id>/report.md`, `runs/<run-id>/decision.json`, `runs/<run-id>/providers/<provider-id>/`, `runs/<run-id>/judge/`, and `runs/<run-id>/manifest.json`. Next: `bakeoff show <run-id>`.

<details open>
<summary>Research and evidence behind this design</summary>

Bakeoff's research modes are built around independent candidate generation followed by comparison. Self-consistency work shows that sampling multiple reasoning paths and aggregating them can improve robustness; Bakeoff applies the same idea at the provider level by asking Claude and Codex for independent artifacts, then using a judge to merge or compare them. Anthropic's multi-agent research writeup supports parallel breadth for broad research tasks, while also warning that cost and coordination grow quickly. That is why Bakeoff stays pairwise instead of running an unbounded swarm.

Position swapping is used where the output is comparative. For `compare` and `analyze`, Bakeoff judges A/B and B/A so the selected winner or explanation spine is less dependent on which provider appeared first. This follows the broader judge-bias literature, especially work showing that balanced position calibration helps reduce order bias.

Sources: [Self-Consistency](https://arxiv.org/abs/2203.11171), [Anthropic multi-agent research](https://www.anthropic.com/engineering/multi-agent-research-system), [Multiagent Debate](https://arxiv.org/abs/2305.14325), [FairEval / balanced position calibration](https://arxiv.org/abs/2305.17926). More: [docs/research-basis.md](docs/research-basis.md).

</details>

## Review

Review asks both providers to inspect the same branch, PR, diff, or local change through a shared `code-review` facet. The judge deduplicates actionable findings, then triage verifies which findings are real, stale, false-positive, or need more evidence.

```text
/bakeoff:run review this diff against main
/bakeoff:run review my local changes for correctness and missing tests
/bakeoff:run review branch feature/auth-cache against main --run-id review-auth-cache
/bakeoff:run review this diff --base main --diff
/bakeoff:run review this diff --no-triage
```

`--base` and `--diff` ask the CLI to capture read-only git context. `--no-triage` skips the default auto-triage for code-review runs.

| Field | Meaning | Example |
| --- | --- | --- |
| `id` | Stable slug identifying the task focus. | `code-review` |
| `kind` | Reserved compatibility field. V1 uses `generic`. | `generic` |
| `focus` | One-sentence review focus applied to both workers and judge. | `Find actionable defects introduced or exposed by the change.` |
| `include` | What to look for. | correctness bugs, security issues, regressions, missing tests |
| `exclude` | What to avoid. | style-only preferences, unrelated rewrites, speculation |
| `notes` | Optional concrete project constraints. | `Treat generated files as out of scope.` |

A facet is a task filter, not a persona. It tells both providers what evidence to prioritize; it does not ask either model to role-play.

```json
{
  "type": "gather",
  "goal": "Review the branch diff for actionable defects.",
  "facet": {
    "id": "code-review",
    "kind": "generic",
    "focus": "Find actionable defects introduced or exposed by the change.",
    "include": [
      "correctness bugs and edge cases",
      "security issues with concrete data-flow or control-flow evidence",
      "user-visible regressions",
      "missing or misleading tests for changed behavior",
      "maintainability risks likely to cause future defects"
    ],
    "exclude": [
      "style-only preferences without project convention evidence",
      "large rewrites unrelated to the changed behavior",
      "speculation without file:line evidence"
    ]
  }
}
```

```text
Review request
  -> classify as gather + code-review facet
  -> collect optional git context: base, diff, changed files
  -> run Claude and Codex over the same review scope
  -> gather judge deduplicates findings
  -> auto-triage verifies actionability
  -> report + triage artifacts
```

Facet behavior: drafts create `gather` + `code-review`; providers receive the same facet; the judge keeps in-facet claims and may preserve severe out-of-facet next checks; triage runs by default unless `--no-triage`; reports show facet id/focus and triage state.

After a review run, open `runs/<run-id>/report.md` first. If triage ran, open `runs/<run-id>/triage/triage.md` before deciding what to fix. Other review artifacts include `review-context.md`, `review-context.json`, `triage/status.json`, `triage/citation_checks.json`, and `triage/source_finding_filter.json`.

<details open>
<summary>Research and evidence behind this design</summary>

Review mode is a `gather` run with a `code-review` facet because the evidence points toward bounded, contextual review instead of open-ended role-play. The facet gives both providers the same focus, include list, and exclude list, so the models inspect the same review scope and the judge can deduplicate findings against the same task filter.

The extra triage step exists because LLM review can produce useful findings but also false positives and vague comments. Context-enriched review research supports giving the model concrete diff and project context; self-correction research warns against asking one model to simply fix its own reasoning without outside feedback. Bakeoff therefore uses two independent provider reviews, a merge judge, and a triage pass that checks actionability, citations, stale findings, and out-of-facet material before the user starts fixing things.

Sources: [Ericsson experience report](https://arxiv.org/abs/2507.19115), [LAURA](https://arxiv.org/abs/2512.01356), [Rethinking Code Review Workflows](https://arxiv.org/abs/2505.16339), [persona prompting limits](https://arxiv.org/abs/2311.10054), [self-correction limits](https://arxiv.org/abs/2310.01798), [Replacing Judges with Juries](https://arxiv.org/abs/2404.18796). More: [docs/research-basis.md](docs/research-basis.md).

</details>

## Build

Build mode runs two providers in isolated worktrees, captures each candidate patch, runs predeclared verifier commands, and selects a winner only when gates, metrics, or swapped judging agree.

Bakeoff stops at the handoff. It does not apply, merge, rewrite, combine, commit, push, open a PR, or synthesize a third patch from provider outputs.

Use build mode when independent patches plus verification are useful: performance, robustness, dependency migrations, refactors, tricky bugs, or UX changes where tests are partial. Skip it for mechanical edits, formatter-only work, tiny fixes with one clear path, or text-only patch comparison.

```text
/bakeoff:run build competing fixes for the failing cache invalidation test
/bakeoff:run build two approaches for reducing ledger scan time, verify with go test ./...
/bakeoff:run build a safer parser for work-order JSONC with tests as the gate
```

Build work orders need `type: "build"`, `build.base_ref` defaulting to `HEAD`, two `codebase` providers, a non-empty `build.verify` list with at least one `kind: "gate"` verifier, optional `kind: "metric"` verifiers, and `build.patch_max_bytes` defaulting to `100000`.

```json
{
  "type": "build",
  "build": {
    "base_ref": "HEAD",
    "verify": [
      { "id": "tests", "kind": "gate", "argv": ["go", "test", "./..."] }
    ]
  }
}
```

See [examples/build.work-order.json](examples/build.work-order.json) for the full shape.

| Evidence | Decision behavior |
| --- | --- |
| Baseline verifier fails before providers run | Stop; baseline failed. |
| No provider captures an eligible patch | Both failed. |
| One provider captures a patch and passes gates | That provider wins by `gate`. |
| Both providers capture patches, only one passes gates | Gate winner. |
| Both pass gates, one metric winner is conclusive | Metric winner. |
| Both pass gates, metrics inconclusive or split | Run swapped build judge. |
| Swapped judge agrees | Judge winner. |
| Swapped judge disagrees | Tie / unresolved; exit code `3`. |

```text
Build request
  -> classify as build
  -> require acceptance criteria and at least one gate verifier
  -> create isolated worktrees from base ref
  -> run Claude and Codex as code-editing providers
  -> capture provider patches
  -> run gates and metrics
  -> run swapped judge only if gates/metrics cannot decide
  -> report + selected patch artifact when there is a canonical winner
```

Build artifacts include `report.md`, `decision.json`, `diagnostics.json`, and `providers/<provider-id>/build/{diff.patch,diffstat.txt,changed-files.txt,verify/result.json}`. If there is a canonical winner, the handoff patch is `runs/<run-id>/providers/<winner>/build/diff.patch`. Bakeoff does not apply it for you.

<details open>
<summary>Research and evidence behind this design</summary>

Competitive build mode is built from the "generate alternatives, then select with evidence" pattern. HumanEval/pass@N and AlphaCode both show that multiple generated candidates can help, but only when there is a strong selector. Bakeoff keeps that selector explicit: first verify the baseline, then capture each provider's patch, then run gate verifiers, then compare metric verifiers when declared.

Execution evidence comes before model preference because code-generation research repeatedly finds that tests, generated checks, and execution-based selection are stronger selectors than text-only judgment when they are available. Bakeoff still records caveats because passing tests can overstate correctness; a green gate is evidence, not proof.

The swapped build judge runs only when gates and metrics cannot decide. This is deliberate: LLM judges can have position and verbosity bias, so Bakeoff asks for A/B and B/A judgments and treats disagreement as unresolved exit code `3` instead of pretending there is a winner. It also stops at the selected provider patch because the current evidence supports auditable selection, not hidden synthesis of a third patch.

Sources: [HumanEval](https://arxiv.org/abs/2107.03374), [AlphaCode](https://arxiv.org/abs/2203.07814), [Large Language Monkeys](https://arxiv.org/abs/2407.21787), [CodeT](https://arxiv.org/abs/2207.10397), [MBR-EXEC](https://arxiv.org/abs/2204.11454), [DOCE](https://arxiv.org/abs/2408.13745), [SWE-bench correctness audit](https://arxiv.org/abs/2503.15223), [MT-Bench / Chatbot Arena](https://arxiv.org/abs/2306.05685), [FairEval](https://arxiv.org/abs/2305.17926), [Agentless](https://arxiv.org/abs/2407.01489). More: [docs/competitive-builds-evidence-2026-05-18.md](docs/competitive-builds-evidence-2026-05-18.md).

</details>

## Outputs And Artifacts

| Artifact | Meaning |
| --- | --- |
| `runs/<run-id>/work-order.json` | The exact work order used for the run. |
| `runs/<run-id>/decision.json` | Machine-readable decision record. |
| `runs/<run-id>/report.md` | Human-readable report. |
| `runs/<run-id>/triage/triage.md` | Review triage report, when triage ran. |
| `runs/<run-id>/providers/<winner>/build/diff.patch` | Selected build patch artifact, only when there is a canonical winner. |

| Exit | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | Runtime, provider, verifier, or build failure. |
| `2` | Usage, config, validation, or missing-input error. |
| `3` | Completed run with unresolved judge disagreement. |
| `130` | Interrupted. |

Exit code `3` means the run completed but the decision was unresolved. It is a completed Bakeoff handoff, not a launcher failure. Deeper artifacts include provider stdout/stderr, judge prompts, manifests, review context, diagnostics, verifier logs, and retained build worktrees when `--keep-worktrees` is used. See [docs/artifacts-and-ledger.md](docs/artifacts-and-ledger.md).

## Configuration And Launcher

```text
BAKEOFF_GO_BINARY
  -> dist/bakeoff
  -> go run ./cmd/bakeoff
```

| Variable | Role |
| --- | --- |
| `CLAUDE_PLUGIN_ROOT` | Set by Claude Code; read by plugin commands and scripts. |
| `CODEX_PLUGIN_ROOT` | Codex-side plugin root when installed there. Verify exact Codex docs before publishing wording. |
| `BAKEOFF_GO_BINARY` | Optional path to a prebuilt compatible `bakeoff` binary. |
| `BAKEOFF_PLUGIN_ROOT` | Developer/test override for the shared launcher. |
| `NO_COLOR` | Standard CLI color suppression. |

Work orders carry budgets for wall-clock time, heartbeat cadence, and output caps. Most users do not need to edit them. See [docs/work-orders.md](docs/work-orders.md).

## Why Bakeoff Is A Thin Launcher

Bakeoff intentionally stays small. The plugin drafts work orders, invokes the CLI, and summarizes artifacts. The Go CLI owns validation, provider execution, scope handling, judging, verifier execution, patch capture, reports, triage, exit codes, and ledger integrity.

Full orchestration adds scheduling, role coordination, state sharing, termination, retries, and synthesis semantics. Bakeoff's strongest property is that every run is small, pairwise, replayable, and auditable.

Bakeoff is not:

- a general multi-agent framework
- a CI runner
- a hosted code-review service
- a benchmark suite
- a patch applier
- a PR publisher
- a hidden branch/worktree manager outside the run ledger
- a synthesizer that combines provider patches into a third patch

Sources: [Anthropic multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system), [MAST multi-agent failure taxonomy](https://arxiv.org/abs/2503.13657), [Agentless](https://arxiv.org/abs/2407.01489).

## Commands

Slash commands:

- `/bakeoff:quickstart`: build or locate the CLI, then run a readiness check without provider auth probes.
- `/bakeoff:run <path or request> [--run-id ID] [--out runs] [--quiet] [--keep-worktrees] [--no-triage]`: validate and run an existing work order, or draft one from natural language.
- `/bakeoff:inspect [latest or run-id]`: inspect existing ledgers, reports, decisions, triage, and build handoff artifacts.
- `/bakeoff:doctor [--skip-auth-probe] [--build] [--quiet]`: check provider and host readiness. `--build` runs live edit probes.
- `/bakeoff:uninstall`: remove Bakeoff-owned plugin state, then guide manual plugin uninstall.

You do not have to remember every slash command. The Bakeoff skill also loads for phrases like "run a bakeoff", "compare providers", "code-review bakeoff", or "competitive build bakeoff".

Underlying CLI:

- `bakeoff init {gather, compare, analyze, review, build}`: scaffold a starter work order JSON.
- `bakeoff validate <work-order>`: schema-validate a work order without running it.
- `bakeoff research <work-order>`: run a research-shaped bakeoff: gather, compare, analyze, or review.
- `bakeoff build <work-order>`: run a competitive build bakeoff in isolated worktrees.
- `bakeoff rerun <source-run-id>`: replay a prior work order with a fresh run id.
- `bakeoff show <run-id>`: print a run report and decision summary.
- `bakeoff triage <run-id>`: run or rerun triage on a completed review.
- `bakeoff ls`: list runs in `runs/`.
- `bakeoff runs verify <run-id>`: verify ledger manifest integrity for a run.
- `bakeoff doctor [--skip-auth-probe] [--build]`: readiness check.

For full CLI flags and machine-readable JSON modes, see [docs/cli-reference.md](docs/cli-reference.md).

## Troubleshooting

Problem: Quickstart cannot find a CLI.
What it means: no `dist/bakeoff`, no `BAKEOFF_GO_BINARY`, and no usable Go toolchain.
Try: install Go 1.24+, install a package with `dist/bakeoff`, or set `BAKEOFF_GO_BINARY`.

Problem: Provider auth failed.
What it means: Bakeoff found the provider CLI, but the provider session is not ready.
Try: log in with the provider CLI directly, then rerun `/bakeoff:doctor --build`.

Problem: Build readiness failed.
What it means: live provider edit probes could not complete in temporary workspaces.
Try: inspect doctor output for sandbox, network, filesystem, or auth failures.

Problem: No selected build patch.
What it means: no canonical winner, or evidence was not strong enough.
Try: inspect `decision.json`, `diagnostics.json`, and provider build artifacts. Exit code `3` means unresolved, not corrupt.

Problem: Triage is stale or missing.
What it means: triage has not run, or its inputs changed.
Try: `bakeoff triage <run-id> --force`.

## Uninstall

```text
/bakeoff:uninstall
/plugin uninstall bakeoff@mstefanko-plugins
```

`/bakeoff:uninstall` removes Bakeoff-owned plugin state and cache, then leaves the final `/plugin uninstall` step manual. It does not remove provider CLIs, provider auth/session files, git branches, user commits, non-Bakeoff `runs/` content, or development binaries such as `./bakeoff` and `./bakeoff-go`.

## Development

```bash
go test ./...
go test -race ./...
python3 scripts/parity-go.py
```

Contributor details live in [docs/cli-reference.md](docs/cli-reference.md), [docs/work-orders.md](docs/work-orders.md), and [docs/artifacts-and-ledger.md](docs/artifacts-and-ledger.md).

<details>
<summary>README disposition map</summary>

| Existing content | Disposition |
| --- | --- |
| Header/opening | Rewritten as plugin-first pitch and boundary. |
| What This Does | Replaced by workflow sections. |
| Prerequisites/install/quick start | Kept near the top with path-neutral install. |
| Commands/CLI/schema/artifacts | Shortened here; moved to focused docs. |
| Build handoff | Elevated into Build and artifact sections. |
| Troubleshooting/uninstall/development | Kept as short footer material. |

</details>
