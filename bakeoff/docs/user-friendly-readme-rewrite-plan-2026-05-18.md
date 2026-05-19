# User-Friendly README Rewrite Plan

Date: 2026-05-18
Status: planning
Scope: root `README.md` information architecture, user-facing copy strategy,
section outline, examples, diagrams, and evidence/citation placement for the
Bakeoff Claude Code plugin, Codex plugin manifest, and shared Go CLI.

## Decision

Rewrite the root README as the single canonical, plugin-first user guide.

The README should teach the Claude Code plugin flow first because `/bakeoff:*`
is the primary launcher a Claude user will encounter. It should also mention
that the checkout ships a Codex plugin manifest. The CLI should be presented as
the engine underneath both plugin surfaces, not as a second competing product.

Do not maintain two full READMEs. Keep one root README and move dense reference
material one click deeper into focused docs such as:

- `docs/cli-reference.md`
- `docs/work-orders.md`
- `docs/research-basis.md`
- `docs/artifacts-and-ledger.md`

The README's narrative should be:

```text
three workflows, one mental model
```

The three workflows are:

- Research
- Review
- Build

The one mental model is:

```text
user request
  -> work order draft
  -> explicit approval when drafted from natural language
  -> two provider runs
  -> judge, verifier, or triage phase
  -> report + replayable ledger artifacts
```

## Audience

Primary reader: an engineer trying Bakeoff for the first time from Claude Code
or Codex. They have used at least one AI coding assistant, but they do not know
Bakeoff's work-order schema, decision kinds, facets, or artifact layout. They
may not have Go installed.

Secondary reader: a power user who prefers the CLI after learning the plugin
flow. The README should help them discover `bakeoff init`, `validate`,
`research`, `build`, `show`, `triage`, `ls`, `runs verify`, `doctor`, and
`rerun`, then send them to `docs/cli-reference.md`.

Non-audience: core contributors looking for implementation internals. They
should get a short Development pointer and then read deeper docs rather than
the root README.

## Voice

Use a direct, technical, restrained-confident voice. Write like a senior
engineer explaining a useful tool to another engineer in Slack. Avoid marketing
phrases such as "empowers developers", "enterprise-grade", "lightning-fast",
"seamless", and "production-grade".

Use this style:

- Bad: "Bakeoff orchestrates parallel provider invocations with
  evidence-mediated selection."
- Good: "Bakeoff runs the same task through Claude and Codex, then picks a
  winner when the evidence is strong enough."
- Bad: "Build mode enables autonomous multi-agent implementation workflows."
- Good: "Build mode creates two isolated patches. It never mutates your
  checkout; you choose whether to apply the selected patch."
- Bad: "Facets unlock persona-driven specialist review."
- Good: "A facet is a task filter. It tells both providers what evidence to
  prioritize."

README pattern findings from `docs/review-findings-readme-patterns.md` should
guide the rewrite:

- header and tagline
- one-paragraph "what is this"
- linkified highlights
- install plus 3-8 line quickstart
- usage sections with links out
- community/license/development footer

The first runnable command should appear within the first screen, roughly the
first 50 lines.

## Length Budget

Target total README length: 250-400 lines of Markdown, with an upper bound of
about 10 KB before links and citations make it feel heavy.

Section budgets:

- Header, pitch, highlights, install, and quickstart: <= 70 lines total.
- Each workflow section: <= 70 lines.
- Flow diagrams: <= 12 lines each.
- Tables in the README: <= 4 columns. Move wider matrices into `docs/`.
- Evidence blocks: one sentence visible inline, then collapsible citations or a
  link to `docs/research-basis.md`.
- CLI/schema/reference details: link out after the first useful mention.

Use plain-text diagrams only in this rewrite. Defer Mermaid until there is a
specific rendering need in the plugin marketplace or docs site.

## Resolved README Decisions

The review turned the earlier open questions into decisions:

- Evidence placement: each workflow gets one visible rationale sentence, a
  short collapsible "Why this design?" block, and a link to
  `docs/research-basis.md`.
- Build examples: show prompts plus a small JSON shape stub. Link to
  `examples/build.work-order.json` for full schema.
- Review context flags: keep `--base` and `--diff` in the Review section, not
  Quick Start.
- CLI binary detail: one short "Underlying CLI" section in the README; full
  flags and machine-readable modes move to `docs/cli-reference.md`.
- `docs/cli-reference.md`: ship it in the same pass as the README rewrite so
  one-click-deep links are not broken.
- Prerequisites: restore a short callout before Quick Start.
- Installation paths: never ship a reviewer-local `/Users/...` path as the
  default. Use marketplace install instructions when available and a clearly
  labeled local-development `<path-to-marketplace>` placeholder otherwise.
- Uninstall: keep a short Uninstall section because the command intentionally
  leaves the final `/plugin uninstall` step manual.
- Development: keep a short footer pointer and move details one click deep.

## Evidence Fact-Check Rule

`docs/review-findings-evidence-and-competitive.md` contains useful competitive
landscape and citation material, but some claims in it do not match this
checkout's current Bakeoff implementation. In particular, do not claim that
this Bakeoff uses beads as its coordination substrate, ships a spec-review ->
code-review -> codex-review chain, or synthesizes/cherry-picks a third patch
unless the implementation changes first.

Use the evidence memo this way:

- Use the 12-tool competitive landscape only in `docs/research-basis.md`, after
  fact-checking every "distinction from Bakeoff" sentence against this repo.
- Keep the README-level distinction narrower and true: Bakeoff is a small,
  pairwise, artifact-ledger harness for two-provider research/review/build
  runs.
- Use the citations for general principles: independent candidates, cross-model
  review, judge bias mitigation, and the risks of naive orchestration.
- Keep `docs/competitive-builds-evidence-2026-05-18.md` as the authoritative
  build evidence source for the current implementation.

## Why This Direction

The current README is accurate but reads like an operator reference. It leads
with CLI-first architecture and implementation boundaries before the user has a
felt model for what to do. The rewrite should make the first run feel safe,
boringly understandable, and auditable.

Local Claude plugin README patterns support this:

- Setup-first, approachable plugin READMEs lead with prerequisites, quick setup,
  and concrete usage before tools/reference. Good examples:
  - `claude-plugins-official/external_plugins/discord/README.md`
  - `claude-plugins-official/external_plugins/telegram/README.md`
  - `claude-plugins-official/external_plugins/greptile/README.md`
- Workflow-heavy plugin READMEs are useful for explaining phases, but they get
  long quickly. Good examples to borrow from carefully:
  - `claude-code-plugins/plugins/feature-dev/README.md`
  - `claude-code-plugins/plugins/code-review/README.md`
  - `claude-code-plugins/plugins/plugin-dev/README.md`
- Bakeoff's current root README is already strong as a compact reference, but
  it should be reorganized around user tasks rather than implementation
  surfaces.

The rewrite should also follow progressive disclosure:

- visible: install, quick start, what happens, what files to inspect
- one click deep: full schema, CLI flags, citation bibliography, architecture
  rationale, ledger internals

Documentation structure guidance:

- Diataxis separates tutorials/how-to/reference/explanation, which maps well to
  "quick start and workflow first; schema and architecture later."
  Source: https://diataxis.fr/
- Progressive disclosure keeps advanced or rarely needed details available
  without making the first path harder to scan.
  Source: https://www.nngroup.com/articles/progressive-disclosure/

## README Acceptance Criteria

The rewritten README should:

- Name the primary audience and use the voice specified above.
- Put normal getting-started/setup at the top.
- Include a short prerequisites callout before the quickstart.
- Keep install instructions path-neutral, with local-development paths labeled
  as placeholders.
- Explain Bakeoff in user language before schema language.
- Show copy-paste examples for research, review, and build.
- Include one example transcript showing natural language -> JSON draft ->
  approval prompt.
- Include a request-routing matrix that explains how natural-language requests
  map to work-order types and facets.
- Include sections for Research, Review, and Build.
- In each workflow section, show:
  - when to use it
  - what type or facet is assigned
  - an example prompt
  - what Bakeoff drafts or runs
  - a diagram of the flow
  - what output/artifacts the user should expect
  - why the design is evidence-based, with citations
- Explain review facets clearly, including `include`, `exclude`, and phase
  behavior.
- Make output paths clear enough that users know exactly what to inspect after
  a run.
- Explain why Bakeoff remains a thin launcher and CLI harness rather than a
  full multi-agent orchestrator.
- Include an explicit "Bakeoff is not" list.
- Mention that the checkout ships both Claude Code and Codex plugin manifests,
  while verifying exact Codex install wording before publishing.
- Surface the `examples/` directory as the schema-friendly starting point.
- Include `bakeoff init` and `bakeoff rerun` in the CLI reference.
- Include the key `/bakeoff:run` flags: `--run-id`, `--out`, `--quiet`,
  `--keep-worktrees`, and `--no-triage`.
- Include the exact CLI exit-code table from `internal/cli/exit.go`.
- Include uninstall scope and the manual `/plugin uninstall` follow-up.
- Include a keep/rewrite/move/delete map for existing README sections in this
  plan so the writer does not silently drop content.
- Bury highly technical material one click deep instead of front-loading it.
- Say explicitly that build mode does not apply, merge, commit, push, publish,
  or synthesize provider patches.

## Proposed Root README Outline

### 1. Header

Use:

```markdown
# Bakeoff

Run the same research, review, or build task through Claude and Codex, then get
an auditable report and replayable artifacts.
```

Keep the first paragraph short. Include the critical boundary immediately after:

```markdown
Bakeoff is a small launcher and CLI harness. It runs providers, captures their
artifacts, verifies or judges the outputs, and writes a ledger. It does not
auto-apply build patches or publish PRs.
```

Header micro-spec:

- No badges unless release/CI/license badges are already reliable.
- No logo requirement for this pass.
- The first call to action should be `/bakeoff:quickstart`.
- Mention both surfaces in one sentence: "Use it from Claude Code with
  `/bakeoff:*`; the same checkout also ships a Codex plugin manifest."

### 2. What You Use It For

Show the three workflows in a compact table:

| Workflow | Use it when | Example request | Result |
| --- | --- | --- | --- |
| Research | You need evidence, comparison, or explanation. | `/bakeoff:run compare these two approaches` | `report.md`, `decision.json`, provider artifacts. |
| Review | You want an actionable audit of a branch, PR, diff, or local changes. | `/bakeoff:run review this diff against main` | Review report plus triage artifacts. |
| Build | You want two isolated implementation candidates and a selected patch artifact. | `/bakeoff:run build competing fixes for this failing test` | Build report plus selected `diff.patch` when there is a canonical winner. |

This section should be friendly and concrete, not exhaustive.

### 3. Prerequisites And Quick Start

Start with this prerequisites callout:

```markdown
Prerequisites: Claude Code with this plugin installed; `git` for review and
build flows; authenticated `claude` and `codex` provider CLIs for live runs;
Go 1.24+ unless you installed a package with `dist/bakeoff` or set
`BAKEOFF_GO_BINARY`.
```

Clarify dependency scope:

- `git` is required for review context capture and build worktree isolation.
- ordinary research runs that do not request git context can be less git-heavy,
  but users should still expect `git` for the standard workflow.
- Provider auth belongs to the provider CLIs. Bakeoff does not own or store
  credentials. Do not place API keys or secrets in work orders.

Keep install and first-run commands near the top:

```text
# Local development install:
/plugin marketplace add mstefanko-plugins <path-to-mstefanko-plugins>
/plugin marketplace update mstefanko-plugins
/plugin install bakeoff@mstefanko-plugins
/reload-plugins
/bakeoff:quickstart
```

If there is a non-local marketplace install path by the time the README ships,
put it first and label the local path as contributor-only.

Add a Codex note:

```markdown
This checkout also includes `.codex-plugin/plugin.json`. Verify the current
Codex plugin install command before publishing this README, then include a
short Codex install or "open from Codex marketplace" note here.
```

Then show the first useful commands:

```text
/bakeoff:run research the auth retry behavior
/bakeoff:run review this diff against main
/bakeoff:run build competing fixes for this failing test
/bakeoff:run examples/build.work-order.json
```

Mention:

- `/bakeoff:run` accepts either natural language or a work-order path.
- Natural-language drafts are shown in full JSON and require explicit approval
  before writing or running.
- Five sample work orders ship in `examples/`: gather, compare, analyze,
  review, and build.
- `scripts/bakeoff-ensure-cli` and `/bakeoff:quickstart` find or build the CLI.
  The launcher resolution order is `BAKEOFF_GO_BINARY`, then `dist/bakeoff`,
  then `go run ./cmd/bakeoff`.

Add this short example transcript:

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

### 4. The Mental Model

Add a simple diagram:

```text
Your request
  |
  v
Work order
  |  existing file: validate and run
  |  natural language: draft JSON, show it, wait for approval
  v
Two providers
  |  Claude
  |  Codex
  v
Evidence phase
  |  research: judge merges or compares outputs
  |  review: judge merges findings, then triage verifies actionability
  |  build: gates, metrics, then swapped judge only if needed
  v
Report + ledger
```

Also add a request-routing matrix:

| If the user asks for | Bakeoff shape | What happens |
| --- | --- | --- |
| Fact-finding, source gathering, inventory, coverage | `type: "gather"` | Both providers collect evidence; the judge deduplicates and preserves citations. |
| Comparing options, vendors, APIs, designs, approaches | `type: "compare"` | Both providers argue the decision; swapped judging resolves a winner or tie. |
| Root cause, explanation, design analysis, synthesis | `type: "analyze"` | Both providers build explanation spines; the judge picks/merges the strongest spine. |
| Review, audit, check a PR, branch, diff, or local changes | `type: "gather"` with `facet.id: "code-review"` | Both providers inspect the same review scope; findings are deduped and triaged. |
| Candidate implementations, competing patches, failing-test fixes | `type: "build"` | Providers edit isolated worktrees; Bakeoff captures patches, runs verifiers, and selects only when evidence is conclusive. |

Add the important clarification:

```markdown
Review is not a separate work-order type. It is a `gather` run with a
`code-review` facet.
```

### 5. Research

This section covers `gather`, `compare`, and `analyze`.

#### Research Type Matrix

Keep the README table to four columns. Move deeper scoring/rubric detail to
`docs/work-orders.md`.

| Type | Best for | What providers do | What the judge does |
| --- | --- | --- | --- |
| `gather` | Evidence collection, inventories, source-backed findings. | Answer the same coverage question with `codebase`, `web`, or `mixed` scope. | Dedupes overlapping claims and preserves citations. |
| `compare` | Choosing between options. | Evaluate the same options and tradeoffs. | Uses swapped A/B and B/A judging to pick a winner, consensus, or tie. |
| `analyze` | Root cause, explanation, architecture analysis. | Build explanation spines. | Chooses or merges the strongest spine and useful additions. |

#### Research Prompt Examples

```text
/bakeoff:run research how auth retry behavior works and cite the files involved
/bakeoff:run compare SQLite FTS vs Tantivy for local product search
/bakeoff:run analyze why provider output caps sometimes produce incomplete reports
```

#### Research Flow Diagram

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

#### Research Output

Mention these common artifacts:

- `runs/<run-id>/work-order.json`
- `runs/<run-id>/providers/<provider-id>/`
- `runs/<run-id>/judge/`
- `runs/<run-id>/decision.json`
- `runs/<run-id>/report.md`
- `runs/<run-id>/manifest.json`

End this section with:

```text
Next: bakeoff show <run-id>
```

#### Research Evidence Placement

Place research citations at the end of the section in a collapsible block:

```markdown
<details>
<summary>Why this design?</summary>

...

</details>
```

Citations and rationale to include:

- Independent samples can improve reasoning robustness, but the value comes
  from comparing and aggregating outputs rather than unbounded agent sprawl.
  Source: Wang et al., "Self-Consistency Improves Chain of Thought Reasoning in
  Language Models" (2022), https://arxiv.org/abs/2203.11171
- Anthropic's multi-agent research system supports parallel breadth-first
  research for broad search tasks, while noting high token costs and that many
  coding tasks have fewer parallelizable subtasks.
  Source: Anthropic Engineering, "How we built our multi-agent research
  system", https://www.anthropic.com/engineering/multi-agent-research-system
- Multi-agent debate can improve factuality and reasoning on some tasks, but
  the README must phrase this as supporting evidence for independent candidate
  generation, not as a claim that Bakeoff runs debate swarms.
  Source: Du et al., "Improving Factuality and Reasoning in Language Models
  through Multiagent Debate", https://arxiv.org/abs/2305.14325
- Bakeoff uses two heterogeneous providers because it wants independent
  evidence and auditable artifacts without creating a general-purpose swarm.

### 6. Review

Make Review its own user-facing section even though it uses `gather` under the
hood. Users think in terms of "review my branch", not "create a gather work
order with a facet".

#### Review Summary

```markdown
Review runs ask both providers to inspect the same branch, PR, diff, or local
change through a shared `code-review` facet. The judge deduplicates actionable
findings, then Bakeoff triage verifies which findings are real, stale,
false-positive, or need more evidence.
```

#### Review Prompt Examples

```text
/bakeoff:run review this diff against main
/bakeoff:run review my local changes for correctness and missing tests
/bakeoff:run review branch feature/auth-cache against main --run-id review-auth-cache
```

Document review-context flags here, not in Quick Start:

```text
/bakeoff:run review this diff --base main --diff
/bakeoff:run review this diff --no-triage
```

`--base` and `--diff` ask the CLI to capture read-only git context. `--no-triage`
skips the default auto-triage for code-review runs.

#### Review Facet Explanation

Add a compact facet table:

| Field | Meaning | Example |
| --- | --- | --- |
| `id` | Stable slug identifying the task focus. | `code-review` |
| `kind` | Reserved compatibility field. V1 uses `generic`. | `generic` |
| `focus` | One-sentence review focus applied to both workers and judge. | `Find actionable defects introduced or exposed by the change.` |
| `include` | What to look for. | correctness bugs, security issues, regressions, missing tests |
| `exclude` | What to avoid. | style-only preferences, unrelated rewrites, speculation |
| `notes` | Optional concrete project constraints. | `Treat generated files as out of scope.` |

Include this exact conceptual rule:

```markdown
A facet is a task filter, not a persona. It tells both providers what evidence
to prioritize; it does not ask either model to role-play.
```

#### Review Facet Example

Show an abbreviated work-order fragment:

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

#### Review Phase Breakdown

```text
Review request
  -> classify as gather + code-review facet
  -> collect optional git context when requested
       base branch
       diff
       changed files
  -> run Claude and Codex over the same review scope
  -> gather judge deduplicates findings
  -> auto-triage verifies actionability
  -> report + triage artifacts
```

Describe how facets affect phases:

- Draft phase: `/bakeoff:run` creates a normal `gather` work order with
  `facet.id: "code-review"`.
- Provider phase: both providers receive the same facet block after scope rules.
- Judge phase: the judge keeps claims that satisfy the facet and may preserve
  severe out-of-facet next checks separately.
- Triage phase: code-review reports auto-triage by default unless
  `--no-triage` is used.
- Report phase: the report displays the facet id/focus and triage state.

#### Review Output

List review-specific artifacts:

- `runs/<run-id>/review-context.md`
- `runs/<run-id>/review-context.json`
- `runs/<run-id>/report.md`
- `runs/<run-id>/triage/status.json`
- `runs/<run-id>/triage/triage.md`
- `runs/<run-id>/triage/citation_checks.json`
- `runs/<run-id>/triage/source_finding_filter.json`

Add a visible tip:

```markdown
After a review run, open `runs/<run-id>/report.md` first. If triage ran, open
`runs/<run-id>/triage/triage.md` before deciding what to fix.
```

#### Review Evidence Placement

Put citations at the end of the section in a collapsible block.

Citations and rationale to include:

- LLM code review is useful when bounded, contextual, and checked, but naive
  prompts create false positives and irrelevant comments.
  Source: "Automated Code Review Using Large Language Models at Ericsson: An
  Experience Report", https://arxiv.org/abs/2507.19115
- Context-enriched retrieval and examples improve review generation quality.
  Source: "LAURA: Enhancing Code Review Generation with Context-Enriched
  Retrieval-Augmented LLM", https://arxiv.org/abs/2512.01356
- Field work on LLM-assisted code review highlights PR summarization and review
  help, but also trust and false-positive concerns.
  Source: "Rethinking Code Review Workflows with LLM Assistance",
  https://arxiv.org/abs/2505.16339
- Persona prompting has weak or mixed evidence for factual accuracy, so Bakeoff
  uses facets as task filters rather than personas.
  Source: Zheng et al., "When 'A Helpful Assistant' Is Not Really Helpful",
  https://arxiv.org/abs/2311.10054
- Same-model self-correction can degrade without external feedback; this
  supports using independent provider outputs and triage instead of asking one
  model to simply review itself.
  Source: Huang et al., "Large Language Models Cannot Self-Correct Reasoning
  Yet", https://arxiv.org/abs/2310.01798
- Diverse model panels can reduce intra-model bias and cost versus a single
  large judge. Use this as evidence for heterogeneous provider review, not as a
  claim that this README ships a panel-of-judges architecture.
  Source: Verga et al., "Replacing Judges with Juries",
  https://arxiv.org/abs/2404.18796
- The existing Bakeoff facet plan already records the implementation rationale
  and should be linked for deeper detail:
  `docs/faceted-research-implementation-plan-2026-05-15.md`

### 7. Build

Build mode should be explained as a competitive implementation harness, not a
general autonomous project manager.

#### Build Summary

```markdown
Build mode runs two providers in isolated worktrees, captures each candidate
patch, runs predeclared verifier commands, and selects a winner only when gates,
metrics, or swapped judging agree.
```

Immediately add:

```markdown
Bakeoff stops at the handoff. It does not apply, merge, rewrite, combine,
commit, push, open a PR, or synthesize a third patch from provider outputs.
```

#### When To Use Build

Use build mode for:

- performance, memory, query-count, bundle-size, or latency-sensitive changes
- bug fixes where existing tests may be under-specified
- refactors where both patches may pass but one better preserves local patterns
- dependency or API migrations where compatibility risk matters
- concurrency, race, or robustness work where stress/fuzz/property checks can
  expose differences
- UX or developer-experience changes where executable checks are partial and a
  structured review is still useful

Usually skip build mode for:

- mechanical edits
- tiny fixes with a strong existing regression test
- formatter/linter-only work
- tasks with only one obvious implementation path
- judge-only patch comparison without executable verification

#### Build Prompt Examples

```text
/bakeoff:run build competing fixes for the failing cache invalidation test
/bakeoff:run build two approaches for reducing ledger scan time, verify with go test ./...
/bakeoff:run build a safer parser for work-order JSONC with tests as the gate
```

#### Build Work-Order Requirements

Make these visible but concise:

- `type: "build"`
- `build.base_ref`, defaulting to `HEAD`
- two providers with `scope: "codebase"`
- `build.verify` with at least one `kind: "gate"` verifier
- optional `kind: "metric"` verifiers for numeric comparison
- `build.patch_max_bytes`, currently defaulted by plugin drafts to `100000`

Show only a small shape stub in the README:

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

Then link to `examples/build.work-order.json` for the full work order.

#### Build Decision Matrix

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

#### Build Flow Diagram

```text
Build request
  -> classify as build
  -> require acceptance criteria and at least one gate verifier
  -> create isolated worktrees from base ref
  -> run Claude and Codex as code-editing providers
  -> capture provider patches
  -> run gates
  -> run metrics if declared
  -> run swapped judge only if gates/metrics cannot decide
  -> report + selected patch artifact when there is a canonical winner
```

#### Build Output

List build-specific artifacts:

- `runs/<run-id>/report.md`
- `runs/<run-id>/decision.json`
- `runs/<run-id>/diagnostics.json`
- `runs/<run-id>/providers/<provider-id>/build/diff.patch`
- `runs/<run-id>/providers/<provider-id>/build/diffstat.txt`
- `runs/<run-id>/providers/<provider-id>/build/changed-files.txt`
- `runs/<run-id>/providers/<provider-id>/build/verify/result.json`
- selected patch only when there is a canonical winner:
  `runs/<run-id>/providers/<winner>/build/diff.patch`

Make this path impossible to miss:

```markdown
If there is a canonical winner, the handoff patch is:
`runs/<run-id>/providers/<winner>/build/diff.patch`.
Bakeoff does not apply it for you.
```

#### Build Evidence Placement

Put citations at the end of the section in a collapsible block.

Citations and rationale to include:

- Multiple generated candidates can improve correctness, but only when there is
  a strong selector. HumanEval showed large pass@N gains under oracle
  selection, which supports candidate diversity but not unbounded orchestration.
  Source: Chen et al., "Evaluating Large Language Models Trained on Code",
  https://arxiv.org/abs/2107.03374
- AlphaCode's success depended on large candidate generation plus filtering and
  clustering by execution behavior, reinforcing "generate alternatives, then
  select with evidence."
  Source: Li et al., "Competition-Level Code Generation with AlphaCode",
  https://arxiv.org/abs/2203.07814
- Repeated sampling can scale issue-solving rates, but the README should frame
  Bakeoff as the small-N, auditable version of that idea rather than a claim
  that N=2 matches large best-of-N systems.
  Source: Brown et al., "Large Language Monkeys: Scaling Inference Compute with
  Repeated Sampling", https://arxiv.org/abs/2407.21787
- Execution-based selection beats text-only preference when executable evidence
  exists.
  Sources:
  - CodeT, https://arxiv.org/abs/2207.10397
  - MBR-EXEC, https://arxiv.org/abs/2204.11454
  - DOCE, https://arxiv.org/abs/2408.13745
- Passing benchmark tests can overstate patch correctness, so Bakeoff treats
  tests as gates and records caveats rather than assuming green means correct.
  Source: Wang et al., "Are Solved Issues in SWE-bench Really Solved
  Correctly?", https://arxiv.org/abs/2503.15223
- LLM judges have position and verbosity bias, so Bakeoff uses gates/metrics
  before judging and uses swapped A/B + B/A judging when a judge is needed.
  Sources:
  - MT-Bench / Chatbot Arena judge bias, https://arxiv.org/abs/2306.05685
  - FairEval, https://arxiv.org/abs/2305.17926
- Simple repository-level repair pipelines can compete with heavier agent
  systems, which supports Bakeoff's narrow harness approach.
  Source: Agentless, https://arxiv.org/abs/2407.01489
- The existing Bakeoff competitive-build evidence memo should be linked for
  deeper detail:
  `docs/competitive-builds-evidence-2026-05-18.md`

### 8. Outputs And Artifacts

Add one consolidated artifact table so users know where to look. Keep the root
README table short; move the full artifact inventory to
`docs/artifacts-and-ledger.md`.

| Artifact | Meaning |
| --- | --- |
| `runs/<run-id>/work-order.json` | The exact work order used for the run. |
| `runs/<run-id>/decision.json` | Machine-readable decision record. |
| `runs/<run-id>/report.md` | Human-readable report. |
| `runs/<run-id>/triage/triage.md` | Review triage report, when triage ran. |
| `runs/<run-id>/providers/<winner>/build/diff.patch` | Selected build patch artifact, only when there is a canonical winner. |

Also include the exact exit-code table from `internal/cli/exit.go`:

| Exit | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | Runtime, provider, verifier, or build failure. |
| `2` | Usage, config, validation, or missing-input error. |
| `3` | Completed run with unresolved judge disagreement. |
| `130` | Interrupted. |

Explain exit code `3` in prose:

```markdown
Exit code `3` means the run completed but the decision was unresolved. It is a
completed Bakeoff handoff, not a launcher failure.
```

Mention that deeper artifacts include provider stdout/stderr, judge prompts,
manifests, review context, diagnostics, verifier logs, and retained build
worktrees when `--keep-worktrees` is used.

### 9. Configuration And Launcher

Keep this short but do not remove it entirely. Users need to know how the
plugin finds the CLI and where common knobs live.

Launcher resolution order:

```text
BAKEOFF_GO_BINARY
  -> dist/bakeoff
  -> go run ./cmd/bakeoff
```

Environment mini-table:

| Variable | Role |
| --- | --- |
| `CLAUDE_PLUGIN_ROOT` | Set by Claude Code; read by plugin commands and scripts. |
| `CODEX_PLUGIN_ROOT` | Codex-side plugin root when installed there. Verify exact Codex docs before publishing wording. |
| `BAKEOFF_GO_BINARY` | Optional path to a prebuilt compatible `bakeoff` binary. |
| `BAKEOFF_PLUGIN_ROOT` | Developer/test override for the shared launcher. |
| `NO_COLOR` | Standard CLI color suppression. |

Add a one-paragraph "Budgets and timeouts" note:

```markdown
Work orders carry budgets for wall-clock time, heartbeat cadence, and output
caps. Most users do not need to edit these, but long review/build runs can
tune them in the work order. See `docs/work-orders.md`.
```

### 10. Why Bakeoff Is A Thin Launcher

This section should answer the user's concern directly.

Visible summary:

```markdown
Bakeoff intentionally stays small. The plugin drafts work orders, invokes the
CLI, and summarizes artifacts. The Go CLI owns validation, provider execution,
scope handling, judging, verifier execution, patch capture, reports, triage,
exit codes, and ledger integrity.
```

Explain why it is not a full multi-agent orchestrator:

- Full orchestration adds scheduling, role coordination, state sharing,
  termination, retries, and synthesis semantics.
- Multi-agent systems have documented failure modes around specification,
  coordination, role clarity, and verification.
- Coding tasks often have fewer truly independent subtasks than open-ended
  research tasks.
- Bakeoff's strongest property is that every run is small, pairwise,
  replayable, and auditable.
- If a user wants to apply, combine, or reimplement from a winning patch, that
  is a separate explicit request with fresh verification.

Add a "Bakeoff is not" list:

- not a general multi-agent framework
- not a CI runner
- not a hosted code-review service
- not a benchmark suite
- not a patch applier
- not a PR publisher
- not a hidden branch/worktree manager outside the run ledger
- not a synthesizer that combines provider patches into a third patch

Citations:

- Anthropic multi-agent research system:
  https://www.anthropic.com/engineering/multi-agent-research-system
- MAST multi-agent failure taxonomy:
  https://arxiv.org/abs/2503.13657
- Agentless:
  https://arxiv.org/abs/2407.01489

### 11. Commands

Keep this short in the root README.

| Command | Purpose |
| --- | --- |
| `/bakeoff:quickstart` | Build or locate the CLI, then run a readiness check without provider auth probes. |
| `/bakeoff:run <path \| request> [--run-id ID] [--out runs] [--quiet] [--keep-worktrees] [--no-triage]` | Validate and run an existing work order, or draft one from natural language. |
| `/bakeoff:inspect [latest \| run-id]` | Inspect existing ledgers, reports, decisions, triage, and build handoff artifacts. |
| `/bakeoff:doctor [--skip-auth-probe] [--build] [--quiet]` | Check provider and host readiness. `--build` runs live edit probes. |
| `/bakeoff:uninstall` | Remove Bakeoff-owned plugin state, then guide manual plugin uninstall. |

Then link:

```markdown
For full CLI flags and machine-readable JSON modes, see `docs/cli-reference.md`.
```

Add a short skill invocation note:

```markdown
You do not have to remember every slash command. The Bakeoff skill also loads
for phrases like "run a bakeoff", "compare providers", "code-review bakeoff",
or "competitive build bakeoff".
```

Add an "Underlying CLI" table with all subcommands:

| Subcommand | Purpose |
| --- | --- |
| `bakeoff init {gather\|compare\|analyze\|review\|build}` | Scaffold a starter work order JSON. |
| `bakeoff validate <work-order>` | Schema-validate a work order without running it. |
| `bakeoff research <work-order>` | Run a research-shaped bakeoff: gather, compare, analyze, or review. |
| `bakeoff build <work-order>` | Run a competitive build bakeoff in isolated worktrees. |
| `bakeoff rerun <source-run-id>` | Replay a prior work order with a fresh run id. |
| `bakeoff show <run-id>` | Print a run report and decision summary. |
| `bakeoff triage <run-id>` | Run or rerun triage on a completed review. |
| `bakeoff ls` | List runs in `runs/`. |
| `bakeoff runs verify <run-id>` | Verify ledger manifest integrity for a run. |
| `bakeoff doctor [--skip-auth-probe] [--build]` | Readiness check. |

Because this table is already close to the README complexity limit, move
per-subcommand flags and examples into `docs/cli-reference.md`.

### 12. Troubleshooting

Keep the troubleshooting section practical:

- quickstart cannot find CLI
- Go missing for source install
- provider CLIs unauthenticated
- `git` missing
- cwd not writable
- build readiness issues
- exit code `3`
- no selected build patch because no canonical winner
- stale or missing triage

Use this shape:

```markdown
Problem: Provider auth failed
What it means: Bakeoff found the provider CLI, but the provider session is not ready.
Try: log in with the provider CLI directly, then rerun `/bakeoff:doctor --build`.
```

### 13. Uninstall

Keep a short section because the uninstall flow intentionally stops before the
manual plugin uninstall command:

```text
/bakeoff:uninstall
/plugin uninstall bakeoff@mstefanko-plugins
```

Say what is not removed:

- provider CLIs
- provider auth/session files
- git branches
- user commits
- non-Bakeoff `runs/` content
- development binaries such as `./bakeoff` and `./bakeoff-go`

### 14. Development

Keep three lines in the README footer:

```bash
go test ./...
go test -race ./...
python3 scripts/parity-go.py
```

Then link to a deeper development or architecture doc. Do not keep the full
parity harness discussion in the root README.

## Research Placement Rule

Research citations should not appear at the top of the README. Put the workflow
first, then the evidence at the end of each relevant workflow section in a
collapsible "Why this design?" block.

Reason:

- The first-time user needs setup and examples before literature.
- The citations matter, but they should explain the design after the user has a
  mental model.
- Review and Build have different evidence bases; localizing citations keeps
  each section readable.
- A deeper `docs/research-basis.md` can collect the full bibliography.

## Technical Details To Move One Click Deep

Move or shorten these in the root README:

- Full work-order schema details.
- Full CLI flag list.
- Environment variable matrix beyond the common knobs.
- Detailed ledger internals.
- Full validation rules.
- Prompt contract details.
- Development commands and parity harness details.
- Long-form evidence memos.

Keep only enough in the root README for a user to:

1. install the plugin
2. run quickstart
3. choose research/review/build
4. understand what will and will not mutate their checkout
5. find the report and artifacts

## Suggested Follow-Up Docs

Create these only as needed during the rewrite:

### `docs/cli-reference.md`

Full CLI and plugin command reference:

- `bakeoff init`
- `bakeoff validate`
- `bakeoff research`
- `bakeoff build`
- `bakeoff rerun`
- `bakeoff show`
- `bakeoff triage`
- `bakeoff ls`
- `bakeoff runs verify`
- `bakeoff doctor`
- JSON output modes
- exit codes

### `docs/work-orders.md`

Full schema reference:

- common fields
- provider fields
- judge fields
- budgets
- `scope_policy`
- facets
- build verifier spec
- examples for gather, compare, analyze, review, build

### `docs/research-basis.md`

Collected bibliography and design rationale:

- research/gather/compare/analyze
- review/facets
- competitive build
- judge bias
- thin launcher/non-orchestrator rationale

### `docs/artifacts-and-ledger.md`

Artifact inventory and replay/inspection guide:

- run directory structure
- manifest verification
- provider artifacts
- judge artifacts
- triage artifacts
- build patch artifacts
- retained worktrees when `--keep-worktrees` is used

## Existing README Disposition Map

Use this map when rewriting so existing content is intentionally kept, moved, or
deleted.

| Existing section/content | Disposition | Destination or replacement |
| --- | --- | --- |
| Header and opening description | Rewrite | New header, tagline, one-paragraph pitch, and safety boundary. |
| What This Does | Rewrite | "What You Use It For" plus Research/Review/Build sections. |
| Prerequisites | Keep and shorten | "Prerequisites And Quick Start" callout. |
| Install | Rewrite | Path-neutral install commands; local-dev placeholder; Codex manifest note. |
| Quick Start | Rewrite | First-screen commands plus example transcript. |
| Commands | Keep and expand | Include full slash-command argument hints; link to `docs/cli-reference.md`. |
| Work-Order UX | Rewrite | "The Mental Model" and request-routing matrix. |
| Competitive Build Handoff | Rewrite and elevate | Build section, with selected patch path and non-mutation boundary repeated. |
| Config And Environment | Keep and shorten | Configuration section with five common variables and launcher resolution order. |
| State And Artifacts | Rewrite | Short root artifact table; full inventory in `docs/artifacts-and-ledger.md`. |
| Troubleshooting | Keep and rewrite | Problem/meaning/try format, exact exit-code table. |
| Uninstall | Keep | Short Uninstall section with manual `/plugin uninstall` step and non-removal list. |
| Development | Move mostly | Three-line footer in README; details to development/architecture doc. |
| Full schema detail | Move | `docs/work-orders.md`. |
| Full CLI flags and JSON modes | Move | `docs/cli-reference.md`. |
| Long evidence memos | Move/link | `docs/research-basis.md` and existing evidence docs. |

Delete or avoid:

- user-specific absolute install paths
- broad claims that Bakeoff uses beads, spec-review chains, or patch synthesis
  unless the implementation changes
- long inline work-order templates when `examples/` can be linked
- marketing adjectives and competitive claims that are not sourced

## Implementation Plan

1. Create `docs/cli-reference.md` as a concise extraction of the current
   command/reference material from `README.md`. This ships in the same pass as
   the README rewrite.
2. Create `docs/work-orders.md` only if the README rewrite needs to remove
   schema details that are not already well covered by `examples/*.work-order.json`.
3. Create or update `docs/research-basis.md` with a fact-checked bibliography.
   If using material from `docs/review-findings-evidence-and-competitive.md`,
   remove or correct any beads/spec-review/codex-review/synthesis claims that
   do not match this checkout.
4. Rewrite root `README.md` around:
   - header
   - what you use it for
   - prerequisites and quick start
   - mental model
   - research
   - review
   - build
   - outputs/artifacts
   - configuration and launcher
   - thin launcher rationale
   - commands
   - troubleshooting
   - uninstall
   - development pointer
5. Add diagrams as plain text first. Mermaid can be considered later, but plain
   text is easier to read in terminals and plugin marketplaces.
6. Keep all examples aligned with current command behavior in:
   - `commands/run.md`
   - `commands/quickstart.md`
   - `skills/bakeoff/SKILL.md`
   - `examples/*.work-order.json`
7. Verify the rewritten README against current implementation:
   - `/bakeoff:run` approval behavior
   - review equals gather + `code-review` facet
   - build requires gate verifier
   - build does not apply patches
   - exit code `3` meaning
   - exit code table: `0`, `1`, `2`, `3`, `130`
   - launcher resolution order
   - `bakeoff init` and `bakeoff rerun`
   - slash-command argument hints
   - artifact paths
8. Run a docs-only review pass to remove overlong technical detail from the root
   README and ensure every dense section links one click deeper.
9. Dogfood the rewrite by running a Bakeoff review on the README diff:

   ```text
   /bakeoff:run review the README/docs diff against main --no-triage
   ```

   Use the findings as review input, not as an automatic patch source.
10. Perform a cold-read validation with one teammate or future self:
    - can they reach `/bakeoff:quickstart` within the first screen?
    - can they explain Research vs Review vs Build after one scan?
    - can they find the selected build patch path?
    - can they explain what Bakeoff will not mutate?
    - can they find CLI reference without searching the repo?

## Definition Of Done

- A new user can install and run `/bakeoff:quickstart` without reading schema
  details.
- The README identifies its audience implicitly through wording and examples:
  engineer user first, contributor second.
- The README uses the specified senior-engineer-on-Slack voice and avoids
  marketing adjectives.
- The first runnable command appears within the first screen.
- Prerequisites are visible before the quickstart.
- Install instructions do not contain a reviewer-local absolute path as the
  default.
- The README mentions both Claude Code and the Codex plugin manifest without
  inventing unverified Codex install syntax.
- The README includes a natural-language draft approval transcript.
- A user can choose Research, Review, or Build from the README alone.
- The type/facet assignment matrix is visible near the top.
- Review facets are explained with one concrete example and phase breakdown.
- Build mode's non-mutation boundary is impossible to miss.
- The selected build patch path is visible in the Build section and artifact
  table.
- Every workflow section states expected output artifacts.
- Evidence citations are present but do not interrupt the setup path.
- CLI reference material is available one click deeper.
- `docs/cli-reference.md` exists and includes `init` and `rerun`.
- The exact CLI exit-code table appears in the README.
- Uninstall scope and manual `/plugin uninstall` follow-up are documented.
- The README contains an explicit "Bakeoff is not" list.
- The README does not imply Bakeoff is a full multi-agent orchestrator.
- The README does not claim beads coordination, spec-review chains,
  codex-review chains, or patch synthesis unless the implementation actually
  ships those features.
