# Competitive Builds Implementation Plan

Date: 2026-05-18
Status: v1 execution plan
Scope: an experimental `build` mode for running two isolated implementation
candidates, verifying them with deterministic commands, judging only when the
gate and metric verifiers cannot decide, and writing a replayable ledger.

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

1. Required correctness gates run first. Broken-but-fast code cannot win.
2. If exactly one candidate passes the required gates, the gates decide.
3. If both candidates pass, predeclared comparative verifiers decide when they
   have a clear thresholded winner.
4. If executable evidence cannot separate the candidates and both patches are
   viable enough to compare, run the same A/B and B/A position-swap judging
   pattern used by compare.
5. If verifier evidence and judge evidence are weak or unstable, write artifacts
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

### Green tests are a gate, not always a selector

For many small implementation tasks, both providers will get the ordinary test
suite green. In those cases, competitive build mode is not buying "did the code
work?" It is buying a structured way to compare two plausible patches against a
declared decision lens.

The evidence is mixed in exactly the way a senior engineer would expect:

- Execution-based selection is strong when the executable signal actually
  distinguishes candidate behavior. MBR-EXEC, CodeT, and DOCE all support this.
- Passing a weak suite is not proof of semantic correctness. SWE-bench patch
  validation studies find plausible patches that pass benchmark tests but fail
  developer-written tests or diverge behaviorally from the ground-truth patch.
  Reference: [Wang et al., 2025, "Are Solved Issues in SWE-bench Really Solved Correctly?"](https://arxiv.org/abs/2503.15223).
- Test adequacy matters as much as patch generation. STING strengthens
  SWE-bench-style suites with targeted generated tests and lowers top-agent
  resolved rates after re-assessment, which means some previously green patches
  were exploiting weak tests. Reference: [Li et al., 2026, "Are Benchmark Tests Strong Enough?"](https://arxiv.org/abs/2604.01518).
- Performance can be a real comparison axis, but only when the task is actually
  performance-sensitive and the benchmark is stable enough to trust. Mercury
  and COFFE both argue that ordinary correctness benchmarks miss code
  efficiency differences. References: [Du et al., 2024, "Mercury"](https://arxiv.org/abs/2402.07844)
  and [Peng et al., 2025, "COFFE"](https://arxiv.org/abs/2502.02827).

Conclusion for Bakeoff: do not treat "tests passed" as the whole selector when
both patches pass. Treat required tests as a correctness gate, then run
predeclared comparative verifiers when the user cares about "which is better."

Competitive builds are most useful for:

- performance, memory, query-count, bundle-size, or latency-sensitive changes
- bug fixes where the existing tests are likely under-specified
- refactors where both patches may pass but one preserves local patterns better
- dependency or API migrations where compatibility risk matters
- concurrency, race, or robustness work where stress/fuzz/property checks can
  expose different behavior
- UX or developer-experience changes where executable checks are partial and a
  structured review is still useful

Competitive builds are usually not worth the overhead for:

- mechanical edits
- tiny fixes with a strong existing regression test
- formatter/linter-only work
- tasks where there is only one obvious implementation path

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
- Build work orders must include at least one predeclared `gate` verifier. A
  judge-only build run is not a v1 mode. If a user wants two text patches judged
  without executable verification, they should use `compare` or `analyze`
  against manually prepared artifacts.

This keeps CodeT's useful lesson, "execution beats taste", without adding a new
test-generation agent to the build loop.

### Comparative verifiers should be declared, not improvised

The build work order should distinguish two verifier roles:

- `gate`: required pass/fail commands such as unit tests, type checks, lint, or
  build checks.
- `metric`: numeric comparisons such as latency, memory, allocations, bundle
  size, query count, benchmark throughput, or coverage of a generated stress
  corpus.

Metrics should be baseline-relative and thresholded. For example, "candidate A
is 3% faster than candidate B" should not decide a run unless the work order
declares that 3% is above the expected noise floor. If multiple metrics point in
different directions, the run should fall through to the build judge instead of
inventing a weighted scoring system in v1.

Non-decisive evidence should be captured as ordinary logs, provider notes,
changed files, or report context. Do not add an `advisory` verifier kind in v1;
it creates another validation and artifact surface without improving the
selector hierarchy.

Provider-authored benchmarks are useful as proposed evidence, but not as the
selector by default. A provider can include a benchmark or probe in its patch
and explain it in its summary or manual checks. Bakeoff should record changed
benchmark/probe files and show them to the judge or human. Bakeoff should not
automatically run arbitrary provider-suggested commands as decisive evidence
inside the same run.

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
runs/<run-id>/worktrees/<provider-id>/
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
Existing run directories are rejected unless the user passes the existing
`--force` semantics. For build mode, `--force` removes the entire
`runs/<run-id>/` subtree, including any retained worktrees under that run, after
verifying the path is inside `--out`.

Concurrency policy:

- Same-repository `bakeoff build` invocations must serialize git worktree admin
  mutations with an advisory per-repo lock at
  `<git-common-dir>/bakeoff-build.lock`.
- Hold the lock while checking source cleanliness, resolving `--force` cleanup,
  creating worktrees, and removing worktrees. Provider execution and verifier
  commands run outside the lock after their detached worktrees exist.
- If the lock cannot be acquired promptly, fail before provider launch with a
  message that another build run is active for the same repository.

Create worktrees from an exact base commit:

```text
git worktree add --detach <path> <base_commit>
```

Detached worktrees avoid branch namespace churn. Provider output is captured as
patches, not commits. V1 prints a plain `git apply --3way --binary` command for
the chosen patch; any first-class apply helper is deferred. The printed command
is a human checkpoint, not an automatic apply step. Bakeoff selects and explains
one provider patch. If a human or follow-on agent edits, combines, or
reimplements after the run, that result is a derived patch outside the bakeoff
decision and must be verified separately before being cited as ready.

Base ref resolution:

- `build.base_ref` is a single git commit-ish string resolved with
  `git rev-parse --verify <base_ref>^{commit}`.
- Accept `HEAD`, branch names, tag names, and full or abbreviated commit SHAs
  when they resolve to exactly one commit.
- Reject empty values, revision ranges, pathspec-style expressions, non-commit
  objects, and ambiguous refs.
- Record both the original `base_ref` and resolved `base_commit` in
  `build-context.json`.

Clean source checkout rule:

- V1 requires `git status --porcelain=v1 --untracked-files=all` to be empty in
  the source checkout before provider worktrees are created.
- Staged changes, unstaged changes, deletes, renames, and untracked files all
  make the source checkout dirty.
- Ignored files do not count as dirty.
- There is no `allow_dirty_base` flag in v1. Dirty-base support can be planned
  later if dogfood proves it is needed.

Submodule rule:

- V1 rejects repositories with `.gitmodules` or index entries with gitlink mode
  `160000` before provider worktrees are created.
- Build mode does not recurse into submodules, capture submodule working tree
  diffs, or let providers edit nested git repositories in v1.

Diff capture:

- Providers are instructed not to commit, but Bakeoff must still capture a
  provider that commits anyway.
- After a provider exits, record `provider_head`, `provider_head_is_base`, and
  whether the provider made commits ahead of `base_commit`.
- Run `git add -A` inside the provider worktree, then capture:
  - patch: `git diff --cached --binary <base_commit> -- .`
  - diffstat: `git diff --cached --stat <base_commit> -- .`
  - changed files: `git diff --cached --name-status <base_commit> -- .`
- This staged-index comparison captures committed changes, staged changes,
  unstaged tracked changes, untracked files, and deletions relative to the base
  commit.
- If the provider committed, keep the patch but mark
  `provider_committed_changes: true` in `workspace.json` and the report.
- Symlinks, executable-bit-only changes, file-mode changes, and ordinary binary
  file changes are captured by the binary patch and diffstat.
- Gitlink/submodule changes are rejected and make the provider patch
  ineligible, even if the source repository passed the initial submodule guard.
- A captured patch larger than `patch_max_bytes` is still written for
  diagnostics when possible, but its provider is ineligible for verification,
  judging, and selection.

Cleanup policy:

- V1 removes worktrees after patch capture and verification by default.
- Add `--keep-worktrees` for debugging and record retained paths in
  `workspace.json`.
- On cleanup failure, preserve paths and make the next command obvious.

## Test, Benchmark, And Verifier Strategy

### Who writes tests and benchmarks?

V1 answer:

- The work-order author supplies verifier commands.
- Providers may write tests or benchmarks as part of their implementation
  patches.
- Bakeoff runs the same verifier commands against both candidates.
- The build judge does not write tests or benchmarks.
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
- Provider-authored benchmarks have the same status: valuable proposed
  evidence, but not decisive unless the work order declared that benchmark or
  metric before provider execution.

### How to make work testable

Build work orders must include acceptance criteria and at least one `gate`
verifier for `build` mode.

They should also include a short `comparison_goal` when "both pass" is expected:
what would make one green patch better than another? Examples: lower p95
latency, fewer allocations, less public API churn, stronger edge-case handling,
cleaner migration path, or smaller blast radius.

Verifier commands should be argv arrays, not shell strings:

```json
"build": {
  "base_ref": "HEAD",
  "comparison_goal": "Prefer the patch that preserves behavior and reduces lookup latency without adding global state.",
  "verify": [
    {
      "id": "unit",
      "kind": "gate",
      "argv": ["go", "test", "./..."],
      "wall_clock_seconds": 300,
      "max_output_bytes": 60000
    },
    {
      "id": "lookup-benchmark",
      "kind": "metric",
      "argv": ["./scripts/bench-lookup-json"],
      "metric": {
        "name": "p95_ms",
        "direction": "lower",
        "min_delta_percent": 10,
        "noise_floor_percent": 5
      },
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
- metric verifier commands should emit a small JSON object in v1 rather than
  requiring Bakeoff to parse every ecosystem's native benchmark output
- verifier subprocesses use the same timeout, output cap, heartbeat,
  `output_cap_grace_seconds`, and `max_output_overrun_bytes` concepts as
  provider subprocesses
- verifier subprocesses do not use provider final-JSON parsing or format retry
- `gate` verifiers decide pass/fail by exit code
- `metric` verifiers must exit zero and emit a JSON object as the last
  non-empty stdout line
- the metric parser reads only that last non-empty stdout line; extra stdout
  before it is allowed, multiple earlier JSON objects are ignored, and a final
  non-JSON line makes the metric inconclusive
- the parsed object must contain a finite numeric top-level property matching
  `metric.name`; non-zero exit, invalid JSON, missing metric, `NaN`, infinity,
  or non-numeric metric values make that metric inconclusive rather than
  failing the correctness gate

Dogfood probe hygiene:

- One-off metric probes used to answer a single bakeoff question should live in
  a scratch directory such as `/tmp/<run-purpose>/`, not in the repository.
- The run ledger records the command output and metric result; it does not make
  scratch instrumentation durable or supported.
- If a probe is likely to be reused, first keep it with the dogfood run notes or
  scratch workspace. Promote it into `scripts/` only after it becomes a durable
  maintainer check with stable inputs, no source-tree injection, and clear docs.
- Commit durable checks, not one-off experimental instruments.

Baseline policy:

- If baseline passes, provider verify results are directly comparable.
- If baseline fails, default behavior is to stop before provider execution and
  write a validation failure explaining the failing verifier.
- Add `--allow-failing-baseline` only if dogfood proves it is needed. In that
  mode, the report must mark verifier evidence as degraded.

Provider-authored tests policy:

- If a provider adds or modifies files matching project test patterns, record
  `provider_authored_tests: true`. V1 path patterns are:
  `*_test.go`, `test_*.py`, `*_test.py`, `*.test.*`, `*.spec.*`,
  `__tests__/`, `/tests/`, `/test/`, `/spec/`, and `/fixtures/` when adjacent
  to tests.
- If the verifier passes only because provider-authored tests are included, this
  is still a valid "the suite passed" signal, but not independent proof.
- The judge prompt should explicitly review the quality and relevance of added
  tests.
- The report should separate "verifier passed" from "added tests appear to cover
  acceptance criteria."

Provider-authored benchmark policy:

- If a provider adds benchmark/probe files, record
  `provider_authored_benchmarks: true`. V1 path patterns are:
  `*_bench_test.go`, `bench*.py`, `benchmark*.py`, paths containing
  `/bench/`, `/benchmarks/`, `/perf/`, `/performance/`, `/load/`, `/stress/`,
  or `/probes/`, and executable files under `scripts/` whose names contain
  `bench`, `perf`, `load`, `stress`, or `probe`.
- Provider final JSON may mention how to run a benchmark in `summary`,
  `manual_checks`, or `risks`; do not add a structured
  `benchmarks_or_probes_added` field in v1.
- Bakeoff should not run provider-suggested commands automatically as decisive
  evidence in v1.
- The judge prompt should treat provider-authored benchmarks as claims to
  inspect, not as neutral ground truth.

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

`bakeoff build --json` prints a compact machine-readable run summary:
`run_id`, `mode`, `decision_kind`, `exit_code`, `selection_basis`, `winner`,
provider outcome summaries, gate verifier summaries, metric summaries, and
artifact paths. `selection_basis` is one of `gate`, `metric`, `judge`, or
`none`; `decision_kind` carries `single_provider_only`, `both_failed`,
`both_failed_verification`, and `tie`. The summary does not embed full
stdout/stderr, patches, judge prompts, or judge responses; those stay in the
ledger and manifest.

Do not add `bakeoff apply` in v1. The report may print a plain
`git apply --3way --binary` command for the winning patch, but applying remains a
human-controlled step. The command applies the exact selected provider patch.
Any edited, combined, or reimplemented result is a derived patch outside the
run and should rerun verification in a fresh follow-up step.

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
    "comparison_goal": "Prefer the patch that keeps behavior unchanged while reducing repeated lookup latency.",
    "patch_max_bytes": 100000,
    "verify": [
      {
        "id": "tests",
        "kind": "gate",
        "argv": ["go", "test", "./..."],
        "wall_clock_seconds": 300,
        "max_output_bytes": 60000
      },
      {
        "id": "lookup-benchmark",
        "kind": "metric",
        "argv": ["./scripts/bench-lookup-json"],
        "metric": {
          "name": "p95_ms",
          "direction": "lower",
          "min_delta_percent": 10,
          "noise_floor_percent": 5
        },
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
- `build.verify` is required and non-empty.
- `build.verify` must include at least one `gate` verifier.
- `build.verify[].id` must be a slug unique within the work order.
- `build.verify[].kind` defaults to `gate`; valid v1 values are `gate` and
  `metric`.
- `build.verify[].argv` must be a non-empty string array.
- no verifier argv element may be empty.
- metric verifiers must declare a metric name, direction, and decisive delta.
- verifier timeouts and output caps must be positive.
- `patch_max_bytes` defaults to `100000` bytes.
- `patch_max_bytes` must be positive and no greater than `5000000` bytes.
- `type: "build"` uses schema version 1; no schema bump is needed because the
  new `build` object is required only for the new mode.
- Provider `scope: "web"` is rejected for `type: "build"` in
  `BuildSpec`/work-order validation so `bakeoff validate` catches it before
  execution.

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
- `blocked`

Provider patch is the artifact of record. The final JSON is an index and
explanation, not the implementation.

Provider status mapping:

- runner failure, timeout, cancelled execution, or invalid final JSON maps to
  `provider_failed`
- `blocked` maps to `provider_failed`; any diff is captured for diagnostics but
  is not eligible for verification or selection
- `complete` with no captured diff maps to `no_patch`
- `complete` with a captured diff over `patch_max_bytes` maps to
  `patch_over_cap`
- `complete` with a captured diff under `patch_max_bytes` maps to
  `patch_captured` and proceeds to verification
- concerns belong in `risks`, not in a separate status value

Provider prompt rules:

- implement the requested change in the current working tree
- keep changes scoped to the goal/background
- add or update tests when appropriate
- include benchmarks or probes when they genuinely demonstrate the comparison
  goal, but describe them in `summary` or `manual_checks` and do not assume
  provider-authored evidence is decisive
- do not commit
- emit final JSON only after editing
- do not modify files outside the worktree

## Pipeline

1. Load and validate work order.
2. Run build-mode provider execution preflight:
   - verify each configured provider CLI is available.
   - verify the parent process can launch provider CLIs with their normal
     auth/session/network state.
   - for Codex build providers, require detected `sandbox_workspace_write`
     support.
3. Resolve git root and `base_ref` to `base_commit`.
4. Ensure repository state is acceptable:
   - require a clean source checkout as defined in the worktree section.
   - reject submodules as defined in the worktree section.
   - record branch, head commit, base commit, and git root.
5. Write `build-context.json`.
6. Create a baseline worktree.
7. Run verifier commands in the baseline worktree.
8. If baseline fails, stop by default with a validation/runtime failure and
   artifacts.
9. Create one detached worktree per provider from `base_commit`.
10. Run both providers in parallel with writable codebase permissions.
11. Capture provider final JSON, stdout/stderr/status, changed files, diff
   patch, and workspace metadata using the staged-index diff method.
12. Enforce patch size caps and provider status mapping.
13. Run verifier commands in each eligible provider worktree.
14. Decide by required gates when possible.
15. If both candidates pass required gates, decide by comparative metric
   verifiers when they have a clear thresholded winner.
16. Run position-swapped build judge only when verifier policy says judge is
   needed.
17. Write `decision.json`, `report.md`, `meta.json`, and `manifest.json`.
18. Remove worktrees unless `--keep-worktrees` is set.
19. Print next command:
   - show report
   - inspect winner patch
   - optionally apply the exact selected patch with `git apply --3way --binary`

## Decision Policy

Provider state is recorded in orthogonal fields instead of one flat status
enum:

- `runner_status`: raw provider runner status such as `ok`, `timeout`,
  `output_cap`, `schema_error`, or `scope_error`.
- `patch_state`: `patch_captured`, `no_patch`, `patch_over_cap`,
  `submodule_change_rejected`, or `provider_failed`.
- `verify_state`: `gate_passed`, `gate_failed`, `not_run`, or
  `baseline_failed`.
- `metric_state`: `metric_decisive`, `metric_inconclusive`, or `not_run`.

`provider_statuses` in `decision.json` should include these fields plus compact
artifact paths. Do not overload `runner_status` with patch or verifier results.

Decision rules:

1. If neither provider has a captured patch, decision is `both_failed`, exit 1.
2. If exactly one provider has a captured patch, run gate verifiers for that
   provider. If gates pass, decision is `single_provider_only`,
   `selection_basis: "gate"`, exit 0 with caveat. If gates fail, decision is
   `both_failed_verification`, `selection_basis: "none"`, exit 1.
3. If exactly one of two captured patches passes all required
   gate commands, decision is `pick_winner`, `selection_basis:
   "gate"`, judge skipped, exit 0.
4. If both captured patches fail required gate commands, decision is
   `both_failed_verification`, `selection_basis: "none"`, judge skipped, exit 1.
5. If both captured patches pass required gates, run
   comparative metric verifiers.
6. If a comparative metric verifier has one clear thresholded winner, decision
   is `pick_winner`, `selection_basis: "metric"`, judge skipped, exit 0.
7. If metrics are absent, tied, noisy, or split, run swapped judge.
8. If swapped judge agrees, decision is `pick_winner`,
   `selection_basis: "judge"`, exit 0.
9. If swapped judge disagrees or ties, decision is `tie`,
   `selection_basis: "none"`, exit 3.

Do not let an LLM judge override "one passes, one fails." Do not rank or select
failed patches in v1. Do not let a performance metric override a failing
correctness gate. Do not synthesize a third patch inside the bakeoff decision
path. Synthesis or manual tightening can be useful after the report, but it is
a separate human/agent step and must not be represented as the selected
provider patch.

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
- comparative metric results, when present
- provider-authored benchmarks/probes, clearly labeled as provider-authored

Rubric:

- correctness against acceptance criteria
- gate verifier evidence
- comparative metric evidence
- scope control
- test relevance
- benchmark/probe relevance
- maintainability
- risk and reversibility

Output shape:

```json
{
  "relation": "compare",
  "scores_a": {
    "correctness": 1,
    "verifier_evidence": 1,
    "comparative_evidence": 1,
    "scope_control": 1,
    "test_quality": 1,
    "benchmark_quality": 1,
    "maintainability": 1
  },
  "scores_b": {
    "correctness": 1,
    "verifier_evidence": 1,
    "comparative_evidence": 1,
    "scope_control": 1,
    "test_quality": 1,
    "benchmark_quality": 1,
    "maintainability": 1
  },
  "winner": "A",
  "rationale": "2-4 sentences.",
  "risks": []
}
```

The resolver should mirror `ResolveCompare`: accept a winner only if pass1 and
pass2 map to the same canonical provider. Otherwise tie and exit 3.

`decision.ResolveBuild` should be explicit rather than a vague compare clone:

```go
type BuildResolutionInput struct {
    WorkOrder        *workorder.WorkOrder
    ProviderIDs      []string
    ProviderStatuses map[string]map[string]any
    GateResults      map[string]map[string]map[string]any // provider -> verifier id -> result summary
    MetricResults    map[string]map[string]map[string]any // provider -> verifier id -> metric summary
    MetricDecisions  []map[string]any
    JudgeResults     map[string]map[string]any
    Pass1Order       map[string]string
    Pass2Order       map[string]string
}

func ResolveBuild(input BuildResolutionInput) (decision map[string]any, exitCode int)
```

The returned decision document owns `decision_kind`, `selection_basis`,
`canonical_winner`, `judge_ran`, `provider_statuses`, `gate_results`,
`metric_results`, `metric_decisions`, `order_maps`, `judge_passes`,
`judge_rationale`, and `caveats`. `selection_basis` is only `gate`, `metric`,
`judge`, or `none`.

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
      benchmark-files.json
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

`build-context.json` is run-level workspace metadata. It should include:

- `schema_version: 1`
- run id
- source git root
- git common dir
- whether the source checkout is itself a linked worktree
- source branch, source head commit, and source clean status
- original `base_ref` and resolved `base_commit`
- worktree parent path and whether it is inside ignored source
- whether the default `runs/<run-id>/worktrees` path was used or an out-of-repo
  fallback was required
- baseline worktree path and cleanup status
- provider ids
- verifier ids and verifier kinds
- run creation time

`internal/buildworkspace.ContextMetadata` owns this shape, and
`internal/buildworkspace.WriteContext(runDir, metadata)` writes
`build-context.json` before baseline verification. `runs verify` treats it as a
required artifact for `type: "build"`.

`workspace.json` should include:

- git root
- base ref
- base commit
- worktree path
- worktree retained/removed
- cleanup status
- provider head commit
- whether provider head still equals base commit
- whether provider committed changes
- provider id
- provider backend/model/effort

`build-context.json` answers "what source checkout and base did this run use?"
`workspace.json` answers "what happened in this provider's isolated worktree?"

## Manifest And Verify

Extend manifests to include stable build artifacts:

- `build-context.json`
- `baseline/verify/*/status.json`
- `baseline/verify/*/stdout.txt`
- `baseline/verify/*/stderr.txt`
- `baseline/verify/*/metric.json`, when a metric verifier emitted a metric
- `providers/*/build/workspace.json`
- `providers/*/build/changed-files.txt`
- `providers/*/build/diff.patch`, when captured
- `providers/*/build/diffstat.txt`
- `providers/*/build/test-files.json`
- `providers/*/build/benchmark-files.json`
- `providers/*/build/verify/*/status.json`
- `providers/*/build/verify/*/stdout.txt`
- `providers/*/build/verify/*/stderr.txt`
- `providers/*/build/verify/*/metric.json`, when a metric verifier emitted a
  metric
- `judge/*` artifacts when judge ran, using the existing judge glob pattern

`runs verify` should fail if a captured patch, verifier status, or decision file
has drifted from the manifest fingerprints.

Implementation detail: add type-aware required artifacts and fingerprint paths
instead of extending only the static `manifest.RequiredArtifacts` list.
`manifest.RequiredArtifactsForRun(runDir)` should require `build-context.json`
for build runs, and `manifest.FingerprintArtifactPaths(runDir)` should add the
build globs above after run completion. This follows the existing provider and
judge glob approach and avoids a wildcard convention in `manifest.json`.

## Provider Permissions

Research mode currently prefers read-only or restricted codebase access where
possible. Build mode must be writable inside provider worktrees.

There are two separate permission questions:

1. Does the provider CLI expose a writable code-execution mode for the child
   agent?
2. Can the parent `bakeoff` process launch the provider CLI in an environment
   where that CLI has its normal auth, session, filesystem, and network access?

The first is a provider capability. The second is an execution-environment
preflight. Prior dogfood showed Claude/Codex can fail when Bakeoff itself is
launched from a surrounding sandbox that blocks provider auth/session/network
state. Treat that as a host-environment failure, not as evidence that the build
pipeline or provider patch failed.

Provider adapter changes:

- Claude: run with CWD set to provider worktree. Do not add read-only
  restrictions. Keep web restrictions according to scope.
- Codex: run with `--sandbox workspace-write -C <provider-worktree>`.
- Capability detection: extend `provider.ScopeCapabilitiesFromHelp` with
  `supports["sandbox_workspace_write"]`, true only when help text advertises
  `--sandbox` and the `workspace-write` value.
- Build mode fails Codex provider setup with `scope_error` when
  `sandbox_workspace_write` is unavailable. Do not silently fall back to
  read-only or unsandboxed Codex execution.
- Scope policy: `codebase` means "can edit worktree; no web." `mixed` means
  "can edit worktree and may use web." `web` is not meaningful for build mode
  and should be rejected in v1.

Readiness checks:

- Add `bakeoff doctor --build` or an equivalent build preflight before dogfood.
- The live check creates a temporary directory, launches each configured
  provider with a trivial edit task, verifies the file changed, and deletes the
  directory.
- CI and unit tests use fake providers only; they must not require real
  Claude/Codex auth.
- Build command startup should print a clear failure when the surrounding
  environment prevents provider CLI launch, instead of letting both providers
  fail later with ambiguous runner output.

## Output And Apply Strategy

V1 output should be a durable handoff, not an automatic mutation of the user's
checkout. The winning artifact is a patch plus evidence, not a hidden stateful
workspace.

Options considered:

1. Auto-apply the winner to the source checkout.
   - UX: lowest friction when it works.
   - Value: weak, because the human loses the natural review checkpoint.
   - Complexity: high. Bakeoff would need target checkout preflight, conflict
     handling, rollback, post-apply verification, binary patch behavior,
     branch/base drift handling, and clear failure recovery.
   - Cleanup: provider worktrees can still be removed, but the source checkout
     is now mutated and must be treated as a second output surface.
   - V1 decision: no.

2. Add `bakeoff apply <run-id> <provider>`.
   - UX: better than copying a patch path by hand.
   - Value: real if dogfood shows repeated manual apply friction.
   - Complexity: medium. It still needs clean-target checks, winner/provider
     validation, base compatibility, conflict reporting, optional post-apply
     verifier execution, and careful exit codes.
   - Cleanup: independent of provider worktrees because it applies the captured
     patch from the ledger.
   - V1 decision: defer. It deserves a separate plan after build mode is useful.

3. Keep the winning worktree and tell the user to continue there.
   - UX: appealing for inspection, but surprising as a default because Bakeoff
     becomes a workspace manager.
   - Value: good for debugging provider behavior.
   - Complexity: medium over time. Retained worktrees accumulate, can pin git
     metadata, and require cleanup education.
   - Cleanup: default deletion keeps Bakeoff small; `--keep-worktrees` is an
     explicit debugging escape hatch and the report records the retained paths.
   - V1 decision: support only through `--keep-worktrees`; do not retain by
     default, do not add a cleanup subcommand, and do not add per-worktree
     cleanup-command rendering in the report.

4. Write report, decision, patches, verifier logs, and a clear handoff section.
   - UX: one small manual step, but the step is useful: the user can inspect the
     winner, hand the report to a fresh Claude/Codex session, or run the printed
     apply command.
   - Value: high. It preserves the human checkpoint and gives another agent a
     clean, evidence-rich input.
   - Complexity: low. It uses artifacts Bakeoff already writes.
   - Cleanup: provider worktrees are removed by default after patch capture and
     verification. The ledger remains replayable.
   - V1 decision: yes. This is the default output model.

5. Create a branch, commit, or PR for the winner.
   - UX: polished for teams, too opinionated for v1.
   - Value: depends heavily on project workflow.
   - Complexity: high. It introduces branch naming, commit message policy,
     remote auth, PR templates, CI state, and cleanup of failed branches.
   - Cleanup: branch/remote lifecycle becomes Bakeoff's problem.
   - V1 decision: no.

V1 report handoff contract:

- terminal output prints `run_id`, decision, winner, selection basis, report
  path, winner patch path, and the first next command
- `report.md` includes a `Winner Handoff` section with:
  - why the winner won
  - verifier and metric summary
  - patch path and diffstat
  - provider risks/manual checks
  - whether provider-authored tests or benchmarks affected confidence
  - retained worktree path, only when `--keep-worktrees` was used
  - a plain apply command: `git apply --3way --binary <patch>`
  - explicit wording that Bakeoff has not applied the patch
  - explicit wording that post-run edits, synthesis, or reimplementation are
    derived patches outside the bakeoff decision and require fresh verification
- the handoff section should be concise enough to paste into a new agent
  session for "review and apply this winning patch" without requiring that
  agent to parse the whole ledger first
- no separate `handoff.md` artifact in v1; keep the handoff inside `report.md`
  to avoid another durable file and manifest surface

This is slightly less automatic than auto-apply, but it is a better fit for
Bakeoff's job: produce trustworthy evidence and make the next human or Claude
step obvious.

## Reports

Build reports should lead with:

- decision kind
- selection basis: gate, metric, judge, or none
- canonical winner, if any
- verifier matrix
- comparative metric matrix, if any
- patch paths
- changed-file summaries
- provider-authored tests and benchmarks/probes
- judge audit, if judge ran
- risks and manual checks
- winner handoff section
- next command

Example next commands:

```text
next: bakeoff show <run-id>
patch: runs/<run-id>/providers/<winner>/build/diff.patch
apply: git apply --3way --binary runs/<run-id>/providers/<winner>/build/diff.patch
```

Do not auto-apply in v1. Do not auto-synthesize in v1. The report hands off
the selected provider patch and the evidence behind that selection; follow-up
modification belongs to a new human/agent step.

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

### Phase 0: Build readiness spike

- Add `bakeoff doctor --build` or an equivalent internal preflight for provider
  write access.
- Detect Codex `sandbox_workspace_write` from `codex exec --help`.
- Verify fake-provider tests do not depend on real Claude/Codex auth.
- Manually confirm one Claude and one Codex live edit smoke in a temporary
  directory from a non-sandboxed host environment.
- Document surrounding-sandbox failures as environment readiness failures.

### Phase 1: Schema and prompts

- Add `build` to `workorder.modes` and `initKinds`.
- Add `BuildSpec` and `VerifierSpec` validation.
- Add verifier kinds: `gate` and `metric`.
- Reject `scope: "web"` for `type: "build"` in work-order validation.
- Keep work-order schema version at `1`; `build` is a new mode-specific object.
- Add `internal/workorder/templates/build.work-order.json`.
- Add `internal/prompt/fixtures/worker-build-claude.txt`.
- Add `internal/prompt/fixtures/worker-build-codex.txt`.
- Add `internal/prompt/fixtures/judge-build.txt`.
- Add worker and judge validators.
- Add prompt fixture tests.

### Phase 2: Worktree package

- Add `internal/buildworkspace`.
- Resolve git root and base commit with context-aware git subprocesses.
- Resolve `base_ref` with `git rev-parse --verify <base_ref>^{commit}`.
- Detect dirty source checkouts with
  `git status --porcelain=v1 --untracked-files=all` and reject.
- Detect `.gitmodules` or gitlink index entries and reject submodule repos.
- Add a per-repository advisory build lock under the git common dir and use it
  around worktree admin operations and `--force` cleanup.
- Create detached provider worktrees under a run-scoped path.
- Verify worktree parent is ignored when project-local.
- Capture changed files, diffstat, and diff patch with the staged-index diff
  method.
- Support symlink, mode-only, executable-bit, and binary-file patch capture;
  reject gitlink/submodule changes.
- Remove worktrees or retain with `--keep-worktrees`.
- Unit-test worktree creation, cleanup, dirty rejection, submodule guard, and
  cleanup failure metadata.

### Phase 3: Verifier runner

- Add `internal/buildverify`.
- Add or extract a raw `runner.RunCommand` path that reuses timeout,
  output-cap, heartbeat, process-group, and cancellation behavior without
  final-JSON parsing or format retry.
- Build verifier entry point:
  `func Run(ctx context.Context, opts buildverify.Options) buildverify.Result`.
- Add verifier result status enum: `passed`, `failed`, `timeout`,
  `output_cap`, `missing_command`, `cancelled`.
- Add verifier heartbeat labels: `baseline:<verify-id>` and
  `verify:<provider-id>:<verify-id>`.
- Add metric result capture for JSON-emitting metric verifiers.
- Parse metrics from the last non-empty stdout line only.
- Add threshold/noise-floor comparison for metric verifiers.
- Run baseline verifier before providers.
- Run provider verifier after patch capture.
- Write verifier artifacts.
- Unit-test pass/fail/timeout/output-cap behavior and metric parsing.

### Phase 4: Build command

- Add `internal/commands/buildcmd`.
- Implement pipeline through provider execution and patch capture.
- Add `bakeoff build` to root command.
- Add `--keep-worktrees`, `--json`, `--quiet`, `--force`, `--run-id`, and
  `--out`.
- Add build-specific provider execution setup: Claude writable worktree CWD,
  Codex `--sandbox workspace-write -C <provider-worktree>`, and clear
  `scope_error` when required controls are unavailable.
- Make `--json` emit the compact summary shape defined in User Surface.
- Add fake-provider integration tests that mutate files in their own worktrees.

### Phase 5: Decision, report, manifest

- Add `decision.ResolveBuild`.
- Add build report rendering.
- Add the `Winner Handoff` report section.
- Extend meta/manifest for build artifacts.
- Add type-aware `manifest.RequiredArtifactsForRun` and build fingerprint
  globs.
- Extend `ls`, `show`, and `runs verify` as needed.
- Add parity-style tests for verifier winner, both-pass judge winner, both-fail
  verifier failure, metric winner, metric inconclusive judge fallback, judge
  disagreement exit 3, and single-provider-only.

### Phase 6: Dogfood and tighten

- Dogfood evidence: `docs/competitive-builds-phase-6-dogfood-2026-05-18.md`.
- Dogfood the five concrete Bakeoff cases below before calling v1 ready.
- Inspect whether the judge prompt overweights patch size or verbosity.
- Inspect artifact size and manifest verification performance.
- Collect evidence for whether a future `bakeoff apply` helper deserves its own
  separate plan; do not add it in v1.

## Concrete Bakeoff Dogfood Cases

These are the first real tasks that should exercise competitive builds. They
are chosen because two competent implementations could differ meaningfully, and
because the verifier contract can be declared before providers write code.

1. Worktree and patch capture package.
   - Provider work: implement `internal/buildworkspace` git root detection,
     dirty rejection, detached worktree creation, staged-index diff capture,
     patch cap handling, and cleanup metadata.
   - Gate verifiers: `go test ./internal/buildworkspace ./internal/ledger`
     and integration tests using temporary git repositories.
   - Comparison lens: prefer the patch with simpler git subprocess boundaries,
     clearer cleanup failure metadata, and fewer assumptions about source-tree
     layout.
   - Plan pressure: validates the repo lock, submodule rejection, binary/mode
     diff capture, and `--force` run-dir cleanup rules.

2. Raw verifier runner extraction.
   - Provider work: extract a raw command runner from `internal/runner` or add a
     small shared execution primitive, then implement `internal/buildverify`.
   - Gate verifiers: runner/buildverify unit tests for pass, non-zero exit,
     timeout, output cap, cancellation, missing command, and heartbeat labels.
   - Metric verifier: a fixture command prints log lines and then
     `{"elapsed_ms": 123}` as the last non-empty stdout line.
   - Plan pressure: validates that verifier commands do not require provider
     final JSON or format retry, and that metric parsing is deterministic.

3. Build manifests and `runs verify` parity.
   - Provider work: extend manifest required artifacts and fingerprint globs for
     build runs, plus `ls`, `show`, and `runs verify` projections.
   - Gate verifiers: `go test ./internal/manifest ./internal/verify` and
     `go test ./internal/commands/runscmd ./internal/commands/lscmd`.
   - Comparison lens: prefer the patch that keeps manifests compact and
     type-aware without duplicating full artifacts.
   - Plan pressure: validates `build-context.json` schema/version handling and
     drift detection for patches, verifier statuses, and metric files.

4. Provider permission and build execution setup.
   - Provider work: add build-specific scope validation, Codex
     `sandbox_workspace_write` detection, Codex `--sandbox workspace-write -C`,
     Claude writable worktree CWD, and build preflight/doctor smoke behavior.
   - Gate verifiers: fake help-output tests, argv construction tests,
     `scope:web` build validation rejection, and fake-provider edit tests.
   - Manual verifier: run the build preflight outside the surrounding Codex
     sandbox so real Claude/Codex auth/session/network access is available.
   - Plan pressure: validates the distinction between CLI capability and host
     execution-environment readiness.

5. Manifest scan performance for large ledgers.
   - Provider work: optimize `bakeoff ls --json` or manifest row projection for
     many run directories without adding SQLite in v1.
   - Gate verifiers: existing `ls`/manifest tests and parity fixtures.
   - Metric verifier: a script creates hundreds or thousands of fake manifests
     and emits `{"elapsed_ms": N}` as the last non-empty stdout line.
   - Plan pressure: validates the gate-to-metric-to-judge hierarchy on a real
     performance-sensitive Bakeoff change.

## Test Plan

Unit tests:

- work-order validation for build specs
- build validation rejects `scope: "web"`
- verifier argv validation
- metric verifier validation and threshold comparison
- build worker final JSON validation
- build judge final JSON validation
- build decision matrix
- worktree path and cleanup behavior
- base ref resolution
- clean source checkout detection
- submodule rejection
- staged-index diff capture, including untracked files and provider commits
- binary, symlink, executable-bit, and mode-only diff capture
- patch cap enforcement
- Codex `sandbox_workspace_write` capability detection
- provider build argv construction

Integration tests with fake providers:

- provider A edits `a.txt`, provider B edits `b.txt`; original checkout remains
  unchanged
- exactly one verifier passes; judge skipped
- both verifiers pass and one metric is decisively better; judge skipped
- both verifiers pass and metrics are tied/noisy; judge runs pass1/pass2
- both verifiers fail; judge skipped and exit 1
- work order with no gate verifier fails validation
- judge swap disagreement returns exit 3
- provider emits valid final JSON but no diff; report says `no_patch`
- dirty base rejects before provider launch
- repository with submodules rejects before provider launch
- `--json` emits summary fields and artifact paths without embedding patches or
  logs
- `report.md` includes a winner handoff with selection basis, patch path,
  diffstat, risks, checkpoint wording, derived-patch wording, and
  `git apply --3way --binary`
- `--keep-worktrees` retains paths and records them
- same-repo concurrent build attempts serialize or fail clearly on the build
  lock
- `--force` removes the entire old run directory, including old run-scoped
  worktrees, only after path-safety checks

Manual dogfood:

- the five concrete Bakeoff dogfood cases above
- one explicit negative dogfood: a build work order with no gate verifier must
  be rejected, not downgraded to judge-only
- one explicit environment dogfood: launching from a surrounding sandbox that
  blocks provider auth/session/network should fail as readiness, not as a
  provider patch result

## Risks

- Verifier commands may be flaky or environment-sensitive.
- Provider-authored tests can make a weak patch appear stronger than it is.
- Provider-authored benchmarks can be self-serving or too narrow.
- Performance benchmarks can be noisy and environment-sensitive.
- Worktree dependency setup can be slow or missing.
- Large diffs can overwhelm judge prompts and ledger storage.
- Codex/Claude write permission flags may drift across CLI versions.
- A surrounding execution sandbox can block provider auth/session/network even
  when Bakeoff's own code is correct.
- Dirty or untracked local state can make "same base" ambiguous.
- Manual apply can feel clumsy if the winner is obviously safe.
- LLM judge self-preference and style bias remain after position swap.

Mitigations:

- require baseline verifier pass by default
- cap patches and logs
- record provider-authored tests separately
- record provider-authored benchmarks/probes separately
- preflight provider build readiness before provider launch
- require declared metric thresholds and treat noisy/split metrics as judge
  inputs, not automatic winners
- keep exactly two providers in v1
- skip judge when verifier has a clear winner
- require human apply step
- make the report handoff short enough to paste into a new agent session
- pin all decisions in `decision.json`

## Deferred Future Work

These are intentionally not part of v1:

- dirty-base support that copies local changes into each provider worktree
- judge-only build runs
- advisory verifier kind
- advisory ranking of failed patches
- `bakeoff apply <run-id> <provider>`
- first-class parsers for ecosystem benchmark formats such as `go test -bench`
- submodule-aware worktree and diff capture

## Recommendation

Proceed with a small experimental build mode only if v1 holds this boundary:

```text
two isolated patches
same verifier commands
gate verifiers decide correctness when they can
comparative metrics decide "which is better" only when predeclared and clear
swapped judge only when needed
no automatic apply
no extra agents
```

That is the part supported by the research and compatible with Bakeoff's
existing design.
