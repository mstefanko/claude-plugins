# Competitive Builds Implementation Plan

Date: 2026-05-18
Status: proposed
Scope: an experimental `build` mode for running two isolated implementation
candidates, verifying them with deterministic commands, judging only when the
verifier cannot decide, and writing a replayable ledger.

## Decision

Add a small competitive-build path, but keep the center of gravity the same as
research:

```text
one work order
-> two heterogeneous providers
-> isolated provider workspaces
-> captured artifacts
-> deterministic verification
-> optional position-swapped judge
-> report with the next human/Claude step
```

Do not add DAGs, beads, recursive decomposition, auto-merge, PR shepherding,
debate loops, multi-round repair, or a separate test-authoring agent in v1.

The build path is worth doing only if the selector is evidence-first:

1. If a predeclared verifier can decide, it decides.
2. If the verifier cannot decide and both patches are viable enough to compare,
   run the same A/B and B/A position-swap judging pattern used by compare.
3. If verifier evidence and judge evidence are weak or unstable, write artifacts
   and make the human step obvious instead of manufacturing confidence.

## Research Basis

### Multiple candidates help, but candidate selection is the value center

The Codex paper introduced HumanEval and showed that repeated sampling
substantially improves functional correctness: the reported model solved 28.8%
of problems with one sample and 70.2% with 100 samples. This supports candidate
diversity as a real signal, but not an open-ended orchestration system.
Reference: [Chen et al., 2021, "Evaluating Large Language Models Trained on Code"](https://arxiv.org/abs/2107.03374).

AlphaCode reached competitive-programming performance by combining large-scale
sampling with filtering and clustering based on program behavior, then
submitting a small candidate set. This again supports "generate alternatives,
then select with evidence." It does not support endless agent debate.
References: [Li et al., 2022, "Competition-Level Code Generation with AlphaCode"](https://arxiv.org/abs/2203.07814)
and [DeepMind AlphaCode overview](https://deepmind.google/blog/competitive-programming-with-alphacode).

MBR-EXEC selects programs by comparing execution results across candidates and
finds execution-aware selection better than execution-unaware selection.
Reference: [Shi et al., 2022, "Natural Language to Code Translation with Execution"](https://arxiv.org/abs/2204.11454).

CodeT generates tests, executes generated solutions against them, and uses dual
execution agreement to choose a candidate. The reported HumanEval pass@1 gain
is a strong argument that execution signals are better selectors than textual
preference when available. Reference: [Chen et al., 2022, "CodeT: Code Generation with Generated Tests"](https://arxiv.org/abs/2207.10397).

DOCE surveys and compares execution-based code-generation selection methods and
highlights the gap between execution-based and execution-free methods, plus the
value of trial unit tests. Reference: [Li et al., 2024, "DOCE: Finding the Sweet Spot for Execution-Based Code Generation"](https://arxiv.org/abs/2408.13745).

Conclusion for Bakeoff: N=2 with heterogeneous providers is a useful and cheap
candidate set. More candidates may help, but they immediately widen provider
count, ledger size, and judge complexity. V1 should keep exactly two providers.

### Tests should decide when they can

For code, deterministic verification is stronger evidence than an LLM judge.
The verifier should therefore run before the judge and should short-circuit the
judge when exactly one candidate passes.

This does not mean "any tests found in the candidate patch are decisive." A
provider can add narrow or misleading tests. Provider-authored tests are still
useful as coverage artifacts, but the highest-trust selector is a verifier
contract supplied before providers write code.

V1 policy:

- Work-order verifier commands are the primary test oracle.
- Providers may add or update tests as part of their patch.
- Bakeoff runs the same predeclared verifier commands against both candidates.
- The decision records whether the decisive verifier command was pre-existing,
  work-order supplied, or depended on provider-authored tests discovered after
  the patch.
- If there is no predeclared verifier, the run can still compare patches, but
  the decision is marked `judge_only`.

This keeps CodeT's useful lesson, "execution beats taste", without adding a new
test-generation agent to the build loop.

### LLM judges are useful but biased

The MT-Bench / Chatbot Arena judge paper identifies position, verbosity, and
self-enhancement biases in LLM-as-judge setups. Reference: [Zheng et al., 2023, "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena"](https://arxiv.org/abs/2306.05685).

FairEval similarly identifies order bias and proposes balanced-position
calibration, which maps directly to Bakeoff's existing two-pass A/B and B/A
judge strategy. Reference: [Wang et al., 2023, "Large Language Models are not Fair Evaluators"](https://arxiv.org/abs/2305.17926).

Conclusion for Bakeoff: keep position swap for build judging. Do not reuse the
research judge schema unchanged. Build judging needs a build-specific rubric
that weighs verifier evidence, diff scope, maintainability, risk, and test
quality.

### Simple repository-level repair pipelines are competitive

SWE-agent shows that repository editing, navigation, and test execution
interfaces matter for automated software engineering. Reference:
[Yang et al., 2024, "SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering"](https://arxiv.org/abs/2405.15793).

Agentless shows that a simple repository-level workflow with localization,
repair, and patch validation can compete with more complex autonomous agents on
SWE-bench Lite. Reference: [Xia et al., 2024, "Agentless: Demystifying LLM-based Software Engineering Agents"](https://arxiv.org/abs/2407.01489).

The multi-agent failure taxonomy identifies specification/system design,
inter-agent misalignment, and task verification/termination as recurring
failure categories. Reference: [Cemri et al., 2025, "Why Do Multi-Agent LLM Systems Fail?"](https://arxiv.org/abs/2503.13657).

Conclusion for Bakeoff: avoid phased autonomous project management. Bakeoff
should be the harness and ledger, not the project manager.

## Current Bakeoff Fit

Bakeoff already owns the reliable pieces:

- one work order with two providers and one judge
- bounded subprocess execution, output caps, heartbeats, and format retry
- provider artifacts under `runs/<run-id>/providers/<id>/`
- judge artifacts under `runs/<run-id>/judge/`
- decision/report/meta/manifest output
- position-swapped compare/analyze judging

The current code that most directly applies:

- `internal/commands/researchcmd/run.go` runs two providers in parallel and
  writes provider artifacts.
- `internal/commands/researchcmd/run.go` runs compare/analyze judges twice,
  with A/B and B/A order maps.
- `internal/decision/decision.go` resolves stable swapped judge outcomes for
  compare and analyze.
- `internal/runner/runner.go` already has deadline, output cap, final-json, and
  retry behavior that build workers and verifiers should reuse.

The biggest missing piece is not judging. It is editable workspace isolation.
`scope:web` creates a temporary empty CWD, which is useful evidence for cleanup
and metadata patterns, but it is not a build-ready repository checkout.
Build mode needs linked git worktrees or checkout copies.

## Worktree Research And Pattern

### Git's native contract

Git worktrees allow one repository to have multiple working trees attached to
the same repository. `git worktree add` creates a linked working tree; `git
worktree remove` removes one; `git worktree prune` cleans stale administrative
files. Reference: [official git-worktree documentation](https://git-scm.com/docs/git-worktree).

Useful implications:

- Worktrees are lighter than full clones because they share repository object
  storage.
- Each provider can have a separate working tree with separate modified files.
- Git already has a cleanup model, but Bakeoff must still clean up paths it
  created and record metadata when cleanup fails.

### Superpowers

Superpowers' `using-git-worktrees` skill is the closest practical pattern. It
checks whether the agent is already in an isolated worktree, avoids nested
worktrees, prefers native platform worktree controls when available, falls back
to `git worktree add`, verifies project-local worktree directories are ignored,
runs setup, and verifies a clean baseline before implementation. Reference:
[obra/superpowers using-git-worktrees skill](https://github.com/obra/superpowers/blob/main/skills/using-git-worktrees/SKILL.md).

What Bakeoff should borrow:

- detect and record main repo, git common dir, and whether the current checkout
  is already a linked worktree
- avoid nested worktree surprises unless explicitly allowed
- keep worktrees in an ignored location or outside the repo
- run baseline verification before provider writes
- distinguish cleanup of the filesystem path from cleanup of git worktree
  metadata

What Bakeoff should not borrow:

- asking the provider interactively for consent
- provider-managed worktree creation
- project setup heuristics that silently run package managers
- forcing a commit-oriented workflow

### MCO

MCO fans out prompts to multiple provider CLIs and supports consensus,
artifact writing, provider permissions, path constraints, and optional debate or
divide modes. It defaults Codex to a writable sandbox, but the public README
does not describe git worktree isolation as a core primitive. Reference:
[mco-org/mco](https://github.com/mco-org/mco).

What Bakeoff should borrow:

- adapter-shaped provider permissions
- per-provider artifacts
- parallel fan-out
- explicit result modes and machine output

What Bakeoff should avoid:

- broad provider matrices in v1
- memory, debate, divide, sessions, ACP, and consensus weighting
- treating agreement as equivalent to passing tests

### Metaswarm

Metaswarm uses worktree assignment, mandatory TDD, independent validation,
adversarial review, commits, PR shepherding, BEADS state, and knowledge
capture. Reference: [dsifry/metaswarm](https://github.com/dsifry/metaswarm)
and [metaswarm docs](https://dsifry.github.io/metaswarm/).

What Bakeoff should borrow:

- independent validation; do not trust provider self-reports
- worktree assignment as an isolation primitive
- "writer reviewed by a different model" as a possible future judge-model swap
  idea

What Bakeoff should avoid:

- BEADS/DAG state
- recursive orchestration
- implementation/validate/review/commit loops
- mandatory TDD gates
- PR shepherding and knowledge-base learning

### Recommended Bakeoff worktree design

V1 should create deterministic, run-scoped, linked worktrees:

```text
runs/<run-id>/worktrees/<provider-id>/       # or sibling under .bakeoff-worktrees
runs/<run-id>/providers/<provider-id>/       # artifact ledger
```

Default location should be outside tracked source whenever possible. A
project-local location is acceptable only if Bakeoff verifies it is ignored.
Given Bakeoff already owns a run ledger, the least surprising v1 is:

```text
runs/<run-id>/worktrees/<provider-id>/
```

That path must be rejected if `runs/` is tracked. If a repository intentionally
tracks `runs/`, use an out-of-repo temp directory and record it in metadata.

Create worktrees from an exact base commit:

```text
git worktree add --detach <path> <base_commit>
```

Detached worktrees avoid branch namespace churn. Provider output is captured as
patches, not commits. A future apply command can apply a patch to the user's
chosen branch explicitly.

Cleanup policy:

- Keep worktrees by default for debuggability until the run is verified? No:
  that turns Bakeoff into a workspace manager.
- V1 should remove worktrees after patch capture and verification by default.
- Add `--keep-worktrees` for debugging and record retained paths in
  `workspace.json`.
- On cleanup failure, preserve paths and make the next command obvious.

## Test And Verifier Strategy

### Who writes tests?

V1 answer:

- The work-order author supplies verifier commands.
- Providers may write tests as part of their implementation patches.
- Bakeoff runs the same verifier commands against both candidates.
- The build judge does not write tests.
- No new independent test-writing agent is added in v1.

Rationale:

- CodeT supports the value of generated tests, but adding a test-generation
  phase inside Bakeoff creates a second agentic product surface and more
  orchestration.
- The strongest no-creep path is to let the human or an existing Claude/Codex
  planning step write the verifier contract before `bakeoff build` starts.
- Provider-authored tests are useful but not independent. They should improve
  the patch and be visible to the judge/human, but they should not be treated as
  equivalent to a predeclared acceptance test.

### How to make work testable

Build work orders must include acceptance criteria and at least one verifier for
`build` mode unless `allow_judge_only` is explicitly true.

Verifier commands should be argv arrays, not shell strings:

```json
"build": {
  "base_ref": "HEAD",
  "allow_judge_only": false,
  "verify": [
    {
      "id": "unit",
      "argv": ["go", "test", "./..."],
      "wall_clock_seconds": 300,
      "max_output_bytes": 60000
    }
  ]
}
```

Command policy:

- no shell by default
- no redirection, pipes, or command substitution in v1
- each verifier has its own timeout and output cap
- verifier CWD is the provider worktree root
- verifier env is inherited, with room for future explicit env allowlists
- baseline verifier runs before providers on a clean base worktree

Baseline policy:

- If baseline passes, provider verify results are directly comparable.
- If baseline fails, default behavior is to stop before provider execution and
  write a validation failure explaining the failing verifier.
- Add `--allow-failing-baseline` only if dogfood proves it is needed. In that
  mode, the report must mark verifier evidence as degraded.

Provider-authored tests policy:

- If a provider adds or modifies files matching project test patterns, record
  `provider_authored_tests: true`.
- If the verifier passes only because provider-authored tests are included, this
  is still a valid "the suite passed" signal, but not independent proof.
- The judge prompt should explicitly review the quality and relevance of added
  tests.
- The report should separate "verifier passed" from "added tests appear to cover
  acceptance criteria."

Future option:

- Add a separate `bakeoff init build --from-analysis <run-id>` or
  `bakeoff verify-plan` helper that drafts verifier commands from a research or
  analysis run. This should write a work order for human approval, not execute
  inside the build run.

## User Surface

Add:

```text
bakeoff init build [--force]
bakeoff build <work-order> [--out runs] [--run-id ID] [--force] [--quiet] [--json] [--keep-worktrees]
```

Do not overload `bakeoff research` with writes. A separate command makes the
mutation boundary obvious.

`bakeoff show`, `bakeoff ls`, and `bakeoff runs verify` should work for build
runs after manifest/report extensions.

## Work Order Shape

Extend schema version 1 conservatively by allowing `type: "build"` and a
required top-level `build` object.

Example:

```json
{
  "schema_version": 1,
  "id": "example-build",
  "type": "build",
  "goal": "Implement receipt barcode lookup caching.",
  "background": "Acceptance criteria, target files, constraints, and known risks.",
  "providers": [
    { "id": "claude", "backend": "claude", "model": "claude-sonnet-4-6", "effort": "high", "scope": "codebase" },
    { "id": "codex", "backend": "codex", "model": "gpt-5.5", "effort": "high", "scope": "codebase" }
  ],
  "judge": { "backend": "claude", "model": "claude-opus-4-7", "effort": "xhigh" },
  "scope_policy": { "enforcement": "best_effort" },
  "build": {
    "base_ref": "HEAD",
    "allow_judge_only": false,
    "patch_max_bytes": 500000,
    "verify": [
      {
        "id": "tests",
        "argv": ["go", "test", "./..."],
        "wall_clock_seconds": 300,
        "max_output_bytes": 60000
      }
    ]
  },
  "budgets": {
    "wall_clock_seconds": 1200,
    "max_output_bytes": 80000,
    "heartbeat_seconds": 60,
    "output_cap_grace_seconds": 10,
    "max_output_overrun_bytes": 80000
  }
}
```

Validation rules:

- `build.base_ref` defaults to `HEAD`.
- `build.verify` is required and non-empty unless `allow_judge_only` is true.
- `build.verify[].id` must be a slug unique within the work order.
- `build.verify[].argv` must be a non-empty string array.
- no verifier argv element may be empty.
- verifier timeouts and output caps must be positive.
- `patch_max_bytes` must be positive and capped by a conservative upper bound.

## Provider Contract

Build workers write files in their isolated worktree. They still emit a small
final JSON payload:

```json
{
  "status": "complete",
  "summary": "What changed and why.",
  "files_touched": ["path/to/file.go"],
  "tests_added_or_changed": ["path/to/file_test.go"],
  "risks": [],
  "manual_checks": []
}
```

Allowed statuses:

- `complete`
- `complete_with_concerns`
- `needs_context`
- `blocked`

Provider patch is the artifact of record. The final JSON is an index and
explanation, not the implementation.

Provider prompt rules:

- implement the requested change in the current working tree
- keep changes scoped to the goal/background
- add or update tests when appropriate
- do not commit
- emit final JSON only after editing
- do not modify files outside the worktree

## Pipeline

1. Load and validate work order.
2. Resolve git root and `base_ref` to `base_commit`.
3. Ensure repository state is acceptable:
   - v1 default: require clean working tree unless `build.allow_dirty_base` is
     later added.
   - record branch, head commit, base commit, and git root.
4. Create a baseline worktree.
5. Run verifier commands in the baseline worktree.
6. If baseline fails, stop by default with a validation/runtime failure and
   artifacts.
7. Create one detached worktree per provider from `base_commit`.
8. Run both providers in parallel with writable codebase permissions.
9. Capture provider final JSON, stdout/stderr/status, changed files, diff patch,
   and workspace metadata.
10. Enforce patch size caps.
11. Run verifier commands in each provider worktree.
12. Decide by verifier when possible.
13. Run position-swapped build judge only when verifier policy says judge is
   needed.
14. Write `decision.json`, `report.md`, `meta.json`, and `manifest.json`.
15. Remove worktrees unless `--keep-worktrees` is set.
16. Print next command:
   - show report
   - inspect winner patch
   - apply winner patch, when a future apply command exists

## Decision Policy

Provider completion categories:

- `no_patch`: provider succeeded structurally but produced no diff
- `patch_captured`: provider produced a diff under cap
- `patch_over_cap`: diff exceeded cap
- `provider_failed`: provider runner failed, timed out, or emitted invalid JSON
- `verify_passed`: all required verifier commands passed
- `verify_failed`: one or more verifier commands failed
- `verify_unavailable`: verifier not configured or baseline evidence degraded

Decision rules:

1. If neither provider has a captured patch, decision is `both_failed`, exit 1.
2. If exactly one provider has a captured patch and no verifier is available,
   decision is `single_provider_only`, exit 0 with caveat.
3. If verifier is configured and exactly one captured patch passes all required
   verifier commands, decision is `pick_winner`, `selection_basis:
   "verifier"`, judge skipped, exit 0.
4. If verifier is configured and both captured patches fail, decision is
   `both_failed_verification`, judge skipped by default, exit 1.
5. If verifier is configured and both captured patches pass, run swapped judge.
6. If verifier is unavailable and both captured patches exist, run swapped
   judge and mark `selection_basis: "judge_only"`.
7. If swapped judge agrees, decision is `pick_winner`, exit 0.
8. If swapped judge disagrees or ties, decision is `tie`, exit 3.

Do not let an LLM judge override "one passes, one fails." Do not declare a
failing patch as winner unless a future explicit flag permits advisory ranking
of failed patches.

## Build Judge

Add `judge-build.txt` and a build judge validator.

Inputs:

- work-order goal/background
- provider A/B final JSON
- provider A/B diff summaries and capped patches
- changed files
- verifier status and logs
- baseline verifier status
- test files added/changed

Rubric:

- correctness against acceptance criteria
- verifier evidence
- scope control
- test relevance
- maintainability
- risk and reversibility

Output shape:

```json
{
  "relation": "compare",
  "scores_a": {
    "correctness": 1,
    "verifier_evidence": 1,
    "scope_control": 1,
    "test_quality": 1,
    "maintainability": 1
  },
  "scores_b": {
    "correctness": 1,
    "verifier_evidence": 1,
    "scope_control": 1,
    "test_quality": 1,
    "maintainability": 1
  },
  "winner": "A",
  "rationale": "2-4 sentences.",
  "kept_from_nonwinner": [],
  "risks": []
}
```

The resolver should mirror `ResolveCompare`: accept a winner only if pass1 and
pass2 map to the same canonical provider. Otherwise tie and exit 3.

## Artifacts

Build run ledger:

```text
runs/<run-id>/
  work-order.json
  build-context.json
  baseline/
    verify/<verify-id>/{status.json,stdout.txt,stderr.txt}
  providers/<id>/
    prompt.txt
    stdout.txt
    stderr.txt
    status.json
    final.json
    build/
      workspace.json
      changed-files.txt
      diff.patch
      diffstat.txt
      test-files.json
      verify/<verify-id>/{status.json,stdout.txt,stderr.txt}
  judge/
    prompt-pass1.txt
    prompt-pass2.txt
    result-pass1.json
    result-pass2.json
    status-pass1.json
    status-pass2.json
  decision.json
  report.md
  meta.json
  manifest.json
```

`workspace.json` should include:

- git root
- base ref
- base commit
- worktree path
- worktree retained/removed
- cleanup status
- provider id
- provider backend/model/effort

## Manifest And Verify

Extend manifests to include stable build artifacts:

- `build-context.json`
- baseline verifier statuses/logs
- provider workspace metadata
- provider changed files
- provider diff patch and diffstat, subject to cap
- provider verifier statuses/logs
- judge artifacts when judge ran

`runs verify` should fail if a captured patch, verifier status, or decision file
has drifted from the manifest fingerprints.

## Provider Permissions

Research mode currently prefers read-only or restricted codebase access where
possible. Build mode must be writable inside provider worktrees.

Provider adapter changes:

- Claude: run with CWD set to provider worktree. Do not add read-only
  restrictions. Keep web restrictions according to scope.
- Codex: run with `-C <provider-worktree>` and a writable sandbox mode when the
  CLI supports it.
- Scope policy: `codebase` means "can edit worktree; no web." `mixed` means
  "can edit worktree and may use web." `web` is not meaningful for build mode
  and should be rejected in v1.

## Reports

Build reports should lead with:

- decision kind
- selection basis: verifier, judge, judge_only, single_provider_only, or failed
- canonical winner, if any
- verifier matrix
- patch paths
- changed-file summaries
- judge audit, if judge ran
- risks and manual checks
- next command

Example next commands:

```text
next: bakeoff show <run-id>
patch: runs/<run-id>/providers/<winner>/build/diff.patch
apply: git apply runs/<run-id>/providers/<winner>/build/diff.patch
```

Do not auto-apply in v1.

## Non-Goals

- no more than two providers
- no DAGs, beads, subtasks, or dependency graph
- no independent test-writing agent inside build mode
- no iterative repair loop
- no automatic commits
- no PR creation or shepherding
- no background worker/session manager
- no memory or cross-run provider scoring
- no merge of both patches into a synthesized third patch
- no long-lived worktree manager
- no hidden package-manager setup

## Implementation Plan

### Phase 1: Schema and prompts

- Add `build` to `workorder.modes` and `initKinds`.
- Add `BuildSpec` and `VerifierSpec` validation.
- Add `internal/workorder/templates/build.work-order.json`.
- Add worker build fixtures for Claude and Codex.
- Add judge build fixture.
- Add worker and judge validators.
- Add prompt fixture tests.

### Phase 2: Worktree package

- Add `internal/buildworkspace`.
- Resolve git root and base commit with context-aware git subprocesses.
- Detect dirty worktree and reject by default.
- Create detached provider worktrees under a run-scoped path.
- Verify worktree parent is ignored when project-local.
- Capture changed files, diffstat, and diff patch.
- Remove worktrees or retain with `--keep-worktrees`.
- Unit-test worktree creation, cleanup, dirty rejection, submodule guard, and
  cleanup failure metadata.

### Phase 3: Verifier runner

- Reuse runner lifecycle concepts for verifier commands, but do not require
  final JSON.
- Add verifier result status enum: `passed`, `failed`, `timeout`,
  `output_cap`, `missing_command`, `cancelled`.
- Run baseline verifier before providers.
- Run provider verifier after patch capture.
- Write verifier artifacts.
- Unit-test pass/fail/timeout/output-cap behavior.

### Phase 4: Build command

- Add `internal/commands/buildcmd`.
- Implement pipeline through provider execution and patch capture.
- Add `bakeoff build` to root command.
- Add `--keep-worktrees`, `--json`, `--quiet`, `--force`, `--run-id`, and
  `--out`.
- Add fake-provider integration tests that mutate files in their own worktrees.

### Phase 5: Decision, report, manifest

- Add `decision.ResolveBuild`.
- Add build report rendering.
- Extend meta/manifest for build artifacts.
- Extend `ls`, `show`, and `runs verify` as needed.
- Add parity-style tests for verifier winner, both-pass judge winner, both-fail
  verifier failure, judge disagreement exit 3, and single-provider-only.

### Phase 6: Dogfood and tighten

- Dogfood on a small Bakeoff feature with a known verifier command.
- Inspect whether the judge prompt overweights patch size or verbosity.
- Inspect artifact size and manifest verification performance.
- Decide whether an apply helper is worth a separate future plan.

## Test Plan

Unit tests:

- work-order validation for build specs
- verifier argv validation
- build worker final JSON validation
- build judge final JSON validation
- build decision matrix
- worktree path and cleanup behavior
- patch cap enforcement

Integration tests with fake providers:

- provider A edits `a.txt`, provider B edits `b.txt`; original checkout remains
  unchanged
- exactly one verifier passes; judge skipped
- both verifiers pass; judge runs pass1/pass2
- both verifiers fail; judge skipped and exit 1
- no verifier with `allow_judge_only: true`; judge runs and decision marks
  `judge_only`
- judge swap disagreement returns exit 3
- provider emits valid final JSON but no diff; report says `no_patch`
- dirty base rejects before provider launch
- `--keep-worktrees` retains paths and records them

Manual dogfood:

- one small Go change with `go test ./...`
- one frontend-only change with a formatter/linter verifier
- one deliberately ambiguous change with no verifier, using
  `allow_judge_only: true`

## Risks

- Verifier commands may be flaky or environment-sensitive.
- Provider-authored tests can make a weak patch appear stronger than it is.
- Worktree dependency setup can be slow or missing.
- Large diffs can overwhelm judge prompts and ledger storage.
- Codex/Claude write permission flags may drift across CLI versions.
- Dirty or untracked local state can make "same base" ambiguous.
- LLM judge self-preference and style bias remain after position swap.

Mitigations:

- require baseline verifier pass by default
- cap patches and logs
- record provider-authored tests separately
- keep exactly two providers in v1
- skip judge when verifier has a clear winner
- require human apply step
- pin all decisions in `decision.json`

## Open Questions

- Should worktrees live under `runs/<run-id>/worktrees` or a sibling
  `.bakeoff-worktrees/` by default?
- Should v1 support dirty local changes by copying them into each worktree, or
  reject dirty bases until dogfood proves otherwise?
- Should `bakeoff build --json` include full verifier matrices or only summary
  paths?
- Should failed-but-interesting patches be judge-ranked under an explicit
  advisory flag, or always left unranked?
- Should a future `bakeoff apply <run-id> <provider>` exist, or is printing the
  patch path enough?

## Recommendation

Proceed with a small experimental build mode only if v1 holds this boundary:

```text
two isolated patches
same verifier commands
verifier decides when it can
swapped judge only when needed
no automatic apply
no extra agents
```

That is the part supported by the research and compatible with Bakeoff's
existing design.
