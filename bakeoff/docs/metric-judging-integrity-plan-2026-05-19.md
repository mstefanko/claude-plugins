# Metric Judging Integrity Plan

Date: 2026-05-19

Status: proposed implementation plan. This file is intentionally a plan, not a
behavior change.

## Short Version

Bakeoff already has the right basic shape: the work order defines the official
verifiers, both providers are measured with the same commands, and the LLM judge
only helps when tests and metrics do not settle the run.

The next fix is to protect the measuring stick. If a metric command is
`./scripts/bench-json`, and a provider can edit `scripts/bench-json` in its own
worktree, then both providers are not really being measured by the same trusted
harness anymore. The lightest useful answer is:

1. Tell providers not to edit verifier scripts, metric data, fixtures, or
   expected outputs.
2. Tell users to put official metric harnesses in shared, predeclared, protected
   places.
3. Add optional protected-path enforcement so provider patches that touch the
   measuring stick become ineligible.
4. Let metrics report simple reliability metadata, such as run count and
   confidence information, without making Bakeoff a statistics engine.
5. Defer fail-to-pass target gates until the integrity basics are solid.

## Current Bakeoff Behavior

Build mode is already verifier-first.

- The work order owns `build.verify`. Providers do not choose the official gate
  or metric commands for the run.
- `internal/commands/buildcmd/run.go` creates a baseline detached worktree and
  runs the same verifier list before launching providers. If baseline gate
  verification fails, providers are not launched.
- `internal/commands/buildcmd/providers.go` runs each provider in its own
  detached worktree, captures its patch, then runs the same `wo.Build.Verify`
  list in that provider worktree.
- `internal/buildverify/buildverify.go` runs each verifier command, records
  stdout/stderr/status artifacts, and parses metrics from the last non-empty
  stdout line as JSON.
- Metric JSON only has to contain the configured metric name as a finite number.
  `CompareMetric` uses `max(min_delta_percent, noise_floor_percent)` as the
  conclusive threshold.
- `internal/decision/decision.go` resolves build decisions in this order:
  captured patches, gate results, metric comparisons, then swapped LLM judge.
- `internal/commands/buildcmd/judge.go` skips the build judge unless both
  providers passed gates and metrics are inconclusive or conflicting.
- `internal/prompt/fixtures/judge-build.txt` already tells the judge that
  provider-authored tests and benchmarks are claims to inspect, not neutral
  ground truth.

That means the current policy is good: executable evidence comes before LLM
preference. The gap is that the official executable evidence may still be
editable if the verifier command points at a repo-local script or data file.

## Product Rule

Providers should not own the official metric script during the same run.

Provider-authored tests and benchmarks are still valuable. They can show how a
provider thought about the problem, improve the final patch, or become a
follow-up verifier. But in the run where they were authored, they are advisory
evidence only. A human can promote them into a new work order after review.

Plain-English rule:

> The contestants may improve the product. They do not get to rewrite the
> scoreboard for the current match.

## Main Risks

### 1. Editable Verifier Harness

Today the same `argv` is used for baseline and providers, but the command runs
inside each worktree. If the work order says:

```json
{
  "id": "latency",
  "kind": "metric",
  "argv": ["./scripts/bench-json"],
  "metric": {
    "name": "elapsed_ms",
    "direction": "lower",
    "min_delta_percent": 10
  }
}
```

then a provider patch can modify `scripts/bench-json` unless the harness lives
outside the editable worktree or Bakeoff rejects that patch. Bakeoff already
captures changed files and detects benchmark-looking paths in
`internal/buildworkspace/buildworkspace.go`, but that is advisory reporting. It
does not make a provider ineligible for changing `./scripts/bench-json` or its
input fixtures.

### 2. Single-Scalar Metrics Hide Reliability

Current metric output is a single number. This is simple and useful, but it does
not say whether the number came from one run or twenty, whether variance was
high, whether a statistical test found a meaningful difference, or which method
produced the value.

`noise_floor_percent` helps, but it is a configured threshold. It is not
measurement evidence by itself.

### 3. Fail-To-Pass Target Checks Are Not First-Class

Baseline gates must pass before providers run. That is correct for environment
sanity checks such as `go test ./...`, type checks, lint, and smoke tests.

Some bug-fix work wants a target reproducer that fails on baseline and passes
after a fix. Bakeoff can model that today only awkwardly, because a failing
baseline gate stops the run. This is useful future work, but it should not come
before verifier integrity.

## Recommended Phases

### Phase 1: Prompt And Docs Tightening

Goal: close the easiest integrity gap without changing Go code.

Update provider prompts so build workers are explicitly told:

- Do not modify verifier scripts, benchmark harnesses, metric data, fixtures,
  golden files, expected-output files, or commands named by `build.verify`
  unless the work order goal explicitly says that the verifier itself is the
  target.
- Do not fake metric output.
- Do not hardcode known benchmark inputs.
- Do not disable tests, skip assertions, weaken fixtures, or change expected
  outputs just to pass the run.
- Provider-authored tests and benchmarks are welcome as patch evidence, but the
  official winner is selected from the predeclared verifier suite.

Affected files:

- `skills/bakeoff/SKILL.md`
- `internal/prompt/fixtures/worker-build-claude.txt`
- `internal/prompt/fixtures/worker-build-codex.txt`
- `internal/prompt/fixtures/judge-build.txt`
- `tests/parity/fixtures/prompts/worker-build-claude.txt`
- `tests/parity/fixtures/prompts/worker-build-codex.txt`
- `tests/parity/fixtures/prompts/judge-build.txt`

Tests:

- Update prompt fixture tests in `internal/prompt/prompt_test.go`.
- Run focused prompt tests first, then `go test ./...` if feasible.

Acceptance:

- Provider prompts contain verifier-tampering rules.
- Judge prompt still treats provider-authored benchmarks as claims, not truth.
- Prompt parity fixtures match generated fixtures.

### Phase 2: Work-Order Guidance For Shared Metrics

Goal: make user-authored work orders safer by default.

Update `docs/work-orders.md` to explain:

- Official metric verifiers should be predeclared in `build.verify`.
- Metric harnesses should be shared and stable before providers run.
- Prefer harnesses outside provider-editable source paths when practical.
- If the metric harness lives inside the repo, list its scripts/data as
  protected once protected-path support exists.
- Provider-created benchmarks are advisory until a human promotes them into a
  new work order.

Add a Go benchmark recipe:

```sh
go test -run='^$' -bench='BenchmarkName' -benchmem -count=10 ./pkg/...
benchstat old.txt new.txt
```

For a Bakeoff metric verifier, the command should do the repeated measurement
and emit one final JSON object as the last non-empty stdout line. Example:

```json
{
  "elapsed_ns_per_op": 12345,
  "unit": "ns/op",
  "n": 10,
  "statistic": "benchstat",
  "p_value": 0.012,
  "method": "go test -bench -count=10 plus benchstat"
}
```

Affected files:

- `docs/work-orders.md`
- Optionally `README.md` if later we want a short user-facing warning.
- Optionally `examples/build.work-order.json` if we want a metric example.

Tests:

- Documentation-only phase does not need Go tests.
- If examples change, run `bakeoff validate` on changed example work orders.

Acceptance:

- Users can tell who owns the official metric harness.
- The docs explain that one-off provider metrics are not decisive.
- The docs show how to emit a JSON metric after repeated measurement.

### Phase 3: Protected Paths

Goal: make verifier integrity enforceable.

Add optional protected paths to the build work order. Two reasonable shapes:

```json
{
  "build": {
    "protected_paths": [
      "scripts/bench-json",
      "testdata/latency-corpus.json"
    ],
    "verify": []
  }
}
```

or:

```json
{
  "build": {
    "verify": [
      {
        "id": "latency",
        "kind": "metric",
        "argv": ["./scripts/bench-json"],
        "protected_paths": [
          "scripts/bench-json",
          "testdata/latency-corpus.json"
        ]
      }
    ]
  }
}
```

Recommendation: start with `build.protected_paths`.

Why: it is easier to explain, easier to validate, and covers shared fixtures
used by more than one verifier. Per-verifier protected paths can come later if
needed.

Implementation details:

- Add `ProtectedPaths []string` to `workorder.BuildSpec`.
- Validate entries in `internal/workorder/workorder.go`:
  - non-empty strings;
  - normalized slash paths;
  - relative to repo root;
  - no absolute paths;
  - no `..` traversal;
  - no duplicate entries after normalization.
- After `buildworkspace.CaptureChanges`, compare captured changed files against
  `wo.Build.ProtectedPaths`.
- If a provider changed a protected path, append an ineligible reason such as
  `patch changed protected verifier path: scripts/bench-json`.
- Record protected-path violations in provider build artifacts so reports and
  summaries explain the decision.
- Keep baseline behavior unchanged.

Affected files/functions:

- `internal/workorder/workorder.go`
  - `BuildSpec`
  - `validateBuildSpec`
  - validation tests in `internal/workorder/workorder_test.go`
- `internal/commands/buildcmd/providers.go`
  - provider ineligibility after patch capture
- `internal/buildworkspace/buildworkspace.go`
  - helper for normalized changed paths or protected-path matching
- `internal/commands/buildcmd/report.go`
  - report ineligible protected-path changes clearly
- `internal/commands/buildcmd/decision.go`
  - existing ineligible status may already be enough; confirm report shape
- `docs/work-orders.md`
  - field reference and examples
- `skills/bakeoff/SKILL.md`
  - drafting guidance

Tests:

- `internal/workorder/workorder_test.go`
  - accepts valid `build.protected_paths`;
  - rejects absolute paths, empty strings, `..`, duplicates.
- `internal/commands/buildcmd/run_test.go`
  - provider that modifies a protected metric script becomes ineligible;
  - other provider can win by gate if it passes and does not touch protected
    paths;
  - report or decision artifacts include the ineligible reason.
- Existing build tests should continue to pass.

Acceptance:

- A provider cannot win after changing a protected verifier script or protected
  data file.
- Protected paths are opt-in, so existing work orders remain valid.
- The reason is auditable in artifacts and the human report.

### Phase 4: Metric Metadata

Goal: improve metric transparency without overbuilding statistics.

Keep the decisive metric value exactly as today: the configured metric name maps
to the number Bakeoff compares. Add optional metadata fields that are parsed,
stored, and reported when present.

Suggested metric JSON fields:

```json
{
  "elapsed_ms": 42.1,
  "unit": "ms",
  "n": 10,
  "statistic": "median",
  "p_value": 0.018,
  "ci_low": 39.8,
  "ci_high": 44.3,
  "method": "benchstat over go test -bench -count=10"
}
```

Implementation details:

- Extend `buildverify.MetricResult` with optional metadata:
  - `Unit string`
  - `N *int`
  - `Statistic string`
  - `PValue *float64`
  - `CILow *float64`
  - `CIHigh *float64`
  - `Method string`
- Parse only known metadata keys from the final JSON object.
- Validate metadata gently:
  - `n` must be a positive integer if present;
  - `p_value` must be finite and between `0` and `1` if present;
  - confidence bounds must be finite if present;
  - strings are trimmed and capped to a reasonable length.
- Do not use metadata for winner selection in the first implementation.
- Report metadata in:
  - metric artifact JSON;
  - build report verifier lines;
  - summary payload if it already includes metric results.
- Add caveats when useful:
  - no `noise_floor_percent`;
  - metric has no run count;
  - metric has `n < 10` for performance-style metrics;
  - metric command was decisive but no method was reported.

Affected files/functions:

- `internal/buildverify/buildverify.go`
  - `MetricResult`
  - `ParseMetric`
  - tests around metadata parsing and invalid metadata
- `internal/commands/buildcmd/report.go`
  - include metadata in metric lines
- `internal/commands/buildcmd/summary.go`
  - confirm metric result JSON includes metadata automatically
- `internal/commands/buildcmd/diagnostics.go`
  - optional caveats for low-evidence metrics
- `docs/work-orders.md`
  - metric output reference

Tests:

- `internal/buildverify/buildverify_test.go`
  - parses metadata;
  - ignores unknown keys;
  - rejects or records errors for invalid decisive metric values;
  - handles invalid optional metadata without making an otherwise valid metric
    unusable, unless we choose stricter validation.
- `internal/commands/buildcmd/run_test.go`
  - report includes metric metadata.

Acceptance:

- Existing metric JSON remains valid.
- Metadata appears in artifacts and reports.
- Winner selection remains backward-compatible and easy to reason about.

### Phase 5: Future Target Gates

Goal: support bug repro checks that should fail on baseline and pass on the
provider patch.

Do not implement this first. It changes the mental model more than protected
paths or metric metadata.

Possible shape:

```json
{
  "id": "repro",
  "kind": "target_gate",
  "baseline": "may_fail",
  "argv": ["go", "test", "./internal/importer", "-run", "TestRetryDoesNotDuplicateLines"],
  "wall_clock_seconds": 60,
  "max_output_bytes": 20000
}
```

Open design questions:

- Does `target_gate` require baseline failure, or merely allow it?
- How do we distinguish environment gates from target gates in summaries?
- Can one provider win by passing target gates if another passes general gates
  but fails target gates?
- Should target gates be allowed to stop provider launch if they unexpectedly
  pass on baseline?

Recommendation: document as future work only. Protected paths and metric
metadata give more safety per unit of complexity.

## Evidence Base

### Execution Evidence Should Beat Text-Only Judging

- [CodeT](https://arxiv.org/abs/2207.10397) shows code selection improves when
  candidates are executed against generated tests and compared by execution
  agreement.
- [MBR-EXEC](https://arxiv.org/abs/2204.11454) selects programs using execution
  semantics and finds execution-aware selection beats execution-unaware
  selection.
- [DOCE](https://arxiv.org/abs/2408.13745) compares execution-based decoding
  and reranking methods, and highlights trial-unit-test filtering as a simple
  effective ingredient.

Bakeoff implication: keep gate and metric verifiers ahead of the LLM judge.

### LLM Judges Are Useful But Biased

- [FairEval](https://arxiv.org/abs/2305.17926) finds that answer order can skew
  LLM evaluator rankings and recommends balanced position calibration.
- [MT-Bench / Chatbot Arena judge paper](https://arxiv.org/abs/2306.05685)
  reports useful agreement with human preferences, while also documenting
  position, verbosity, self-enhancement, and reasoning limitations.

Bakeoff implication: keep swapped judging as a fallback, not the primary
selector when executable evidence exists.

### Tests And Benchmarks Can Be Too Weak

- [EvalPlus](https://arxiv.org/abs/2305.01210) shows limited tests can
  overestimate correctness, reduce pass rates once strengthened, and even change
  model rankings.
- [SWE-bench correctness audit](https://arxiv.org/abs/2503.15223) finds some
  plausible patches pass benchmark tests while diverging from developer
  expectations or ground-truth behavior.
- OpenAI's 2026 note on
  [why SWE-bench Verified no longer measures frontier coding capabilities](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/)
  adds a practical warning about benchmark contamination and benchmark
  lifecycle.

Bakeoff implication: passing gates are strong evidence, not mathematical proof.
Reports should preserve caveats, and user-authored metrics should be protected
from accidental or intentional weakening.

### Performance Metrics Need Repetition And Noise Control

- Go's [benchstat documentation](https://pkg.go.dev/golang.org/x/perf/cmd/benchstat)
  is the standard Go reference for comparing repeated benchmark runs.
- LLVM's [benchmarking tips](https://llvm.org/docs/Benchmarking.html) emphasize
  reducing noise, running benchmarks multiple times, and remembering that low
  noise does not eliminate measurement bias.

Bakeoff implication: metric verifiers should be allowed to report run count,
method, and statistical metadata, but Bakeoff does not need to become the
statistics package. The verifier command can do the domain-specific comparison
and emit final JSON.

### Reward Hacking And Verifier Gaming Are Real Risks

- [EvilGenie](https://arxiv.org/abs/2511.21654) studies reward hacking in
  programming settings where agents can hardcode test cases or edit testing
  files.
- [RewardHackingAgents](https://arxiv.org/abs/2603.11337) measures evaluator
  tampering and train/test leakage in ML-engineering agents, and finds evaluator
  locking eliminates natural-agent tampering attempts in their setup.
- [LLMs Gaming Verifiers](https://arxiv.org/abs/2604.15149) shows imperfect
  verifiers can induce shortcut strategies that satisfy the verifier without
  learning the intended general rule.

Bakeoff implication: protected metric harnesses are not paranoia. They are the
smallest practical version of evaluator locking for a local code-build tool.

## Non-Goals

- Do not let each provider author the official metric script for the same run.
- Do not make provider-authored benchmarks decisive without a separate human
  promotion step.
- Do not use LLM judge scores as a substitute for executable gates or metrics.
- Do not synthesize a third patch from benchmark ideas during the Bakeoff run.
- Do not build a hidden benchmark platform into Bakeoff.
- Do not add complex statistical decision-making until metric metadata is
  captured and dogfooded.
- Do not implement `target_gate` before protected paths and metric metadata.

## Suggested Implementation Order

1. Phase 1 prompt tightening.
2. Phase 2 docs guidance.
3. Phase 3 `build.protected_paths`.
4. Phase 4 metric metadata capture/reporting.
5. Revisit Phase 5 only after real work orders show repeated need for
   fail-to-pass target gates.

This order keeps the cheap safety wins first and avoids turning Bakeoff into a
larger benchmark orchestration system before the current pairwise contract needs
it.
