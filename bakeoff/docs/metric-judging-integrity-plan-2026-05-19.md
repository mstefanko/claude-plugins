# Metric Judging Integrity Plan

Date: 2026-05-19

Status: proposed implementation plan, updated after readiness/UX/soundness
review. This file is intentionally a plan, not a behavior change.

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
   measuring stick become ineligible before provider verification runs.
4. Let metrics report simple reliability metadata, such as run count, unit, and
   method information, and let work orders require a minimum run count for
   metrics that should not be decided from one sample.
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

## Review Validation Decisions

The review findings are good and should be treated as execution constraints, not
future nice-to-haves. Pin the following decisions before implementation starts:

- Prompt fixtures: `internal/prompt/fixtures/*.txt` are embedded source
  templates. `tests/parity/fixtures/prompts/*.txt` are frozen rendered outputs
  used by `internal/prompt/prompt_test.go`. There is no generator today. For this
  plan, update the embedded templates first, then manually refresh the rendered
  parity fixtures from the prompt test output. Do not maintain divergent prompt
  text by hand in both places.
- Phase 1 and Phase 3 release boundary: prompt-only language is advisory. The
  user-visible claim that protected verifier files cannot be edited should ship
  only with Phase 3 enforcement. If Phase 1 lands earlier, release notes and docs
  must say it is prompt guidance only.
- Protected-path short-circuit: run `buildworkspace.CaptureChanges` first, check
  protected-path violations from the captured changed-file list, and skip
  provider verification when a protected path changed. A provider that changed a
  protected path must not satisfy the "eligible captured patch" checks used by
  build decision resolution.
- Decision-kind restraint: do not add a new public `decision_kind` just for
  protected-path ineligibility in v1. Reuse existing build failure/tie decision
  kinds, and put the specific protected-path reason in provider status,
  artifacts, reports, and caveats.
- Metadata strictness: decisive metric values remain strict; invalid optional
  metadata is non-fatal. Drop invalid optional fields from the structured metric
  metadata and record a warning instead of rejecting an otherwise valid metric.
- Worker schema: build workers do not emit official metric metadata. Metric
  metadata comes only from verifier command stdout. Worker prompts should tell
  providers not to fake metric output or metric metadata.
- Protected path UX: use plain language in user docs: "official verifier",
  "protected path", and "provider patch". Keep the scoreboard metaphor only in
  rationale sections like this plan.
- Build judge bias: port the broader anti-bias rule from the legacy
  `agent-writer-judge` prompt into the build judge prompt. The current build
  judge prompt names verbosity bias, but should also explicitly guard against
  position, self-preference, consensus/familiarity, and fabrication of test or
  metric evidence.
- Identical outputs: if two eligible captured patches are identical after
  normalization, skip metric noise and LLM preference. Record an explicit
  identical-patch tie.
- Metric metadata v1 scope: keep the first metadata pass to fields that directly
  improve trust or explainability: run count, unit, statistic/method labels, and
  warnings about ignored stdout. Defer p-values and confidence intervals until
  the simpler metadata has been dogfooded.

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

Two current details make this easy to over-trust:

- `CompareMetric` currently folds `min_delta_percent` and
  `noise_floor_percent` into one `max(...)` threshold. That produces the same
  winner in many cases, but it hides whether the metric cleared the practical
  effect-size gate, the noise gate, or both.
- `MetricResult.Conclusive` currently ignores sample count. If a verifier emits
  one JSON value from one benchmark run, Bakeoff can treat it as decisive.

Metric parsing also intentionally reads only the last non-empty stdout line as
the final JSON object. That contract is simple, but the implementation should
warn when it detects earlier JSON metric-looking lines so authors do not think
multiple samples were consumed.

### 3. Fail-To-Pass Target Checks Are Not First-Class

Baseline gates must pass before providers run. That is correct for environment
sanity checks such as `go test ./...`, type checks, lint, and smoke tests.

Some bug-fix work wants a target reproducer that fails on baseline and passes
after a fix. Bakeoff can model that today only awkwardly, because a failing
baseline gate stops the run. This is useful future work, but it should not come
before verifier integrity.

## Recommended Phases

### Phase 1: Prompt And Docs Tightening

Goal: close the easiest integrity gap in prompt policy, while being explicit
that enforcement arrives in Phase 3.

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

Use this exact idea in provider-facing copy:

> You may add tests, benchmarks, or probes as evidence in your patch. Do not
> modify predeclared verifier commands or the data, fixtures, golden files, or
> expected outputs they depend on, unless the task explicitly says the verifier
> itself is the target. Do not fake metric output or metric metadata.

Update the build judge prompt so it does not reward fabricated evidence:

- Do not invent test counts, metric values, file names, or command results that
  are not present in the artifacts.
- Treat unknown test or metric details as unknown, not as zero and not as
  support for either candidate.
- Resist position, verbosity, self-preference, and familiarity bias when
  verifier evidence is not decisive.

Affected files:

- `skills/bakeoff/SKILL.md`
- `internal/prompt/fixtures/worker-build-claude.txt`
- `internal/prompt/fixtures/worker-build-codex.txt`
- `internal/prompt/fixtures/judge-build.txt`
- `tests/parity/fixtures/prompts/worker-build-claude.txt`
- `tests/parity/fixtures/prompts/worker-build-codex.txt`
- `tests/parity/fixtures/prompts/judge-build.txt`

Fixture sync:

- Source of truth: edit `internal/prompt/fixtures/*.txt`.
- Rendered parity outputs: refresh matching files under
  `tests/parity/fixtures/prompts/*.txt` after prompt rendering changes.
- There is no automatic generator today. Do not copy raw embedded fixture files
  over parity fixtures; the parity fixtures contain rendered work-order values.

Tests:

- Update prompt fixture tests in `internal/prompt/prompt_test.go`.
- Run focused prompt tests first, then `go test ./...` if feasible.

Definition of done:

- Provider prompts contain verifier-tampering rules.
- Judge prompt still treats provider-authored benchmarks as claims, not truth.
- Prompt parity fixtures match generated fixtures.
- If Phase 1 ships before Phase 3, user-facing docs and release notes call it
  advisory prompt policy, not enforced protection.

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
- User-facing docs should use plain language. Say "provider patch changed an
  official verifier path"; do not use the contestants/scoreboard metaphor in
  docs users read while fixing a run.

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
  "method": "go test -bench -count=10 plus benchstat"
}
```

When `build.protected_paths` ships, add a visible example to
`examples/build.work-order.json`:

```json
{
  "build": {
    "protected_paths": [
      "scripts/bench-json",
      "testdata/latency-corpus.json"
    ],
    "verify": [
      {
        "id": "latency",
        "kind": "metric",
        "argv": ["./scripts/bench-json"],
        "metric": {
          "name": "elapsed_ms",
          "direction": "lower",
          "min_delta_percent": 10,
          "noise_floor_percent": 5,
          "min_runs": 10
        },
        "wall_clock_seconds": 300,
        "max_output_bytes": 60000
      }
    ]
  }
}
```

Add a simple non-failing `bakeoff validate` warning after Phase 3:

- If `build.protected_paths` is empty and a metric verifier's `argv[0]` is a
  repo-relative command such as `./scripts/bench-json` or `scripts/bench-json`,
  warn that the metric harness is provider-editable and suggest adding that
  script plus any data fixtures to `build.protected_paths`.
- Keep this as a focused warning in the existing validate output. Do not build a
  general advisory/warning framework just for this feature.

Affected files:

- `docs/work-orders.md`
- Optionally `README.md` if later we want a short user-facing warning.
- `examples/build.work-order.json` when `build.protected_paths` is implemented.
- `internal/commands/validatecmd/validate.go` when validation warnings are added.

Tests:

- Documentation-only phase does not need Go tests.
- If examples change, run `bakeoff validate` on changed example work orders and
  assert the protected-path warning behavior with focused validate tests.

Definition of done:

- Users can tell who owns the official metric harness.
- The docs explain that one-off provider metrics are not decisive.
- The docs show how to emit a JSON metric after repeated measurement.
- The example work order makes `protected_paths` discoverable once the field is
  supported.

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
  - no glob syntax in v1;
  - no duplicate entries after normalization.
  Keep matching case-sensitive in v1. Do not add a general validation-warning
  mechanism just to warn on case-folded duplicates; revisit only if real macOS
  work orders hit confusing duplicates.
- Add a helper in `internal/buildworkspace/buildworkspace.go` instead of
  reinventing changed-path parsing. It should share the path normalization used
  by `ClassifyBuildEvidenceFiles`, while extending it for protected paths:
  - compare repository-relative slash paths;
  - match exact files and directory descendants;
  - for rename/copy-style name-status entries, check both the old path and the
    new path;
  - do not lowercase paths for matching;
  - do not follow symlinks. If a protected path is a symlink, changing the
    symlink path is a violation; changing a repo-local target is a violation
    only if the target path is also listed.
- Enforcement order:
  1. Run the provider.
  2. Run `buildworkspace.CaptureChanges`.
  3. Check captured changed files against `wo.Build.ProtectedPaths`.
  4. If any protected path changed, mark the provider ineligible and skip
     `buildverify.Run` for that provider.
  5. Reflect that in the existing eligibility path. Either set an explicit
     `patch_state` such as `protected_path_changed` or centralize an
     `eligiblePatchCaptured` helper; in either case, protected-path violators
     must not be counted by `buildPatchCaptured`.
- Use this exact ineligible reason for one path:
  `patch changed protected path "scripts/bench-json"; revise the patch or remove that path from build.protected_paths if it is intentionally editable`
- Use this exact ineligible reason for multiple paths:
  `patch changed protected paths "scripts/bench-json", "testdata/latency-corpus.json"; revise the patch or remove those paths from build.protected_paths if they are intentionally editable`
- Record protected-path violations in provider build artifacts so reports and
  summaries explain the decision. Suggested artifact:
  `providers/<id>/build/protected-paths.json`.
- Keep baseline behavior unchanged.
- Do not add `decision_kind: "both_ineligible"` in v1. If both providers become
  ineligible because they changed protected paths, return the existing
  `both_failed` no-winner decision with `selection_basis: "none"` and a caveat
  naming the protected paths. If one provider remains eligible, let the existing
  gate, metric, and judge flow decide among eligible providers only.
- Add an identical-patch guard. Store a normalized patch digest during capture.
  If both eligible providers have identical patch digests after capture, skip
  metric comparison and the LLM judge, then return a tie with
  `selection_basis: "identical_patch"` and a caveat that the captured patches
  were identical.

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
  - provider status, protected-path artifact references, explicit patch-state or
    eligibility helper, and identical-patch digest plumbing
- `internal/decision/decision.go`
  - reuse existing build failure decisions for protected-path ineligibility
  - identical-patch tie before metric and judge fallback
- `docs/work-orders.md`
  - field reference and examples
- `skills/bakeoff/SKILL.md`
  - drafting guidance
- `examples/build.work-order.json`
  - visible `protected_paths` example once the field exists

Tests:

- `internal/workorder/workorder_test.go`
  - accepts valid `build.protected_paths`;
  - rejects absolute paths, empty strings, `..`, duplicates, and glob syntax.
- `internal/buildworkspace/buildworkspace_test.go`
  - protected matcher handles exact paths, directory descendants, renames, case
    sensitivity, and symlink paths without following targets.
- `internal/commands/buildcmd/run_test.go`
  - provider that modifies a protected metric script becomes ineligible;
  - other provider can win by gate if it passes and does not touch protected
    paths;
  - both providers violating protected paths return existing `both_failed`, with
    no new `decision_kind`;
  - identical captured patches return the identical-patch tie without running
    the build judge;
  - report or decision artifacts include the exact ineligible reason.
- `internal/commands/validatecmd` tests
  - repo-relative metric command with empty `protected_paths` emits a warning.
- Existing build tests should continue to pass.

Definition of done:

- A provider cannot win after changing a protected verifier script or protected
  data file.
- Protected paths are opt-in, so existing work orders remain valid.
- The reason is auditable in artifacts and the human report.
- The recoverable next action is clear: revise the patch, or remove the path
  from `build.protected_paths` if the verifier really is intended to be edited.
- The implementation reuses existing buildworkspace changed-file classification
  and normalization helpers.

### Phase 4: Metric Metadata

Goal: improve metric transparency without overbuilding statistics.

Keep the decisive metric value exactly as today: the configured metric name maps
to the number Bakeoff compares. Add optional metadata fields that are parsed,
stored, and reported when present. Keep v1 narrow: collect evidence that helps a
human trust the number without turning Bakeoff into a statistics library.

Suggested metric JSON fields:

```json
{
  "elapsed_ms": 42.1,
  "unit": "ms",
  "n": 10,
  "statistic": "median",
  "method": "benchstat over go test -bench -count=10"
}
```

Defer `p_value`, `ci_low`, and `ci_high` in v1. They are useful in some
domains, but parsing and explaining them well is more statistical surface area
than Bakeoff needs before `n`, `method`, and `min_runs` have been dogfooded.

Suggested metric work-order fields:

```json
{
  "metric": {
    "name": "elapsed_ms",
    "direction": "lower",
    "min_delta_percent": 10,
    "noise_floor_percent": 5,
    "min_runs": 10
  }
}
```

Implementation details:

- Extend `buildverify.MetricResult` with optional metadata:
  - `Unit string`
  - `N *int`
  - `Statistic string`
  - `Method string`
  - `MetadataWarnings []string`
  - `SampleJSONLinesIgnored int`
- Extend `workorder.MetricSpec` with optional `MinRuns int`, defaulting to `1`
  for backward compatibility.
- Keep the last-non-empty-line contract: the final non-empty stdout line is the
  aggregate JSON object Bakeoff compares.
- Detect earlier stdout lines that parse as JSON objects and contain the metric
  name. Do not consume them as samples in v1; record a warning such as
  `ignored 3 earlier metric JSON line(s); emit one final aggregate JSON object`.
- Parse only known metadata keys from the final JSON object.
- Validate metadata gently and non-fatally:
  - `n` must be a positive integer if present;
  - strings are trimmed and capped to a reasonable length.
- Invalid optional metadata fields are dropped from structured metadata and
  recorded in `MetadataWarnings`. Invalid or missing decisive metric values still
  make the metric inconclusive.
- Use `n` for winner selection only when the work order opts in with
  `metric.min_runs > 1`:
  - if `n` is missing, the metric comparison is inconclusive;
  - if `n < min_runs`, the metric comparison is inconclusive;
  - otherwise continue to effect-size and noise-floor checks.
- Separate the practical effect-size gate from the noise gate:
  - `min_delta_percent` answers "is the improvement large enough to matter?";
  - `noise_floor_percent` answers "is the difference above the configured noise
    floor?";
  - a metric comparison is conclusive only when both gates pass.
- Report both gates separately in `MetricComparison`, for example
  `min_delta_percent`, `noise_floor_percent`, `meets_min_delta`, and
  `meets_noise_floor`. Keep `threshold_percent` only as a compatibility field if
  existing consumers need it.
- Report metadata in:
  - metric artifact JSON;
  - compact build report verifier lines;
  - summary payloads through existing metric result/summary surfaces.
- Add caveats only when they change interpretation or recovery:
  - earlier metric JSON lines were ignored;
  - metric is configured with `min_runs` but output omitted `n`;
  - metric output had `n < min_runs`.
  Do not emit generic caveats for every missing optional metadata field.
- Document determinism limits: Bakeoff does not currently set provider or judge
  temperature/seed, and some CLIs may not expose stable seed controls. The
  reproducibility controls in v1 are predeclared verifiers, repeated metric
  runs, metric metadata, source/base commit capture, and swapped judging.

Affected files/functions:

- `internal/workorder/workorder.go`
  - `MetricSpec.MinRuns`
  - validation tests for `min_runs`
- `internal/buildverify/buildverify.go`
  - `MetricResult`
  - `ParseMetric`
  - `CompareMetric`
  - tests around metadata parsing, invalid metadata, ignored earlier JSON lines,
    `min_runs`, and separate threshold reasons
- `internal/commands/buildcmd/report.go`
  - include compact metadata in metric lines
- `internal/commands/buildcmd/summary.go`
  - confirm metric result JSON includes metadata automatically
- `internal/commands/buildcmd/diagnostics.go`
  - only if needed for targeted metric caveats above
- `docs/work-orders.md`
  - metric output reference

Tests:

- `internal/buildverify/buildverify_test.go`
  - parses metadata;
  - ignores unknown keys;
  - drops invalid optional metadata with warnings;
  - rejects or records errors for invalid decisive metric values;
  - warns when earlier metric JSON lines are ignored;
  - makes a comparison inconclusive when `metric.min_runs` is unmet;
  - reports separate effect-size and noise-floor gates.
- `internal/commands/buildcmd/run_test.go`
  - report includes metric metadata.

Definition of done:

- Existing metric JSON remains valid.
- Metadata appears in artifacts and reports.
- Winner selection remains backward-compatible and easy to reason about.
- Work orders can opt out of one-sample decisiveness by setting `metric.min_runs`.
- Metric comparison output shows whether the practical delta gate, the noise
  gate, or the run-count gate decided the result.

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

Definition of done for this phase in the current plan:

- No target-gate implementation is added during the protected-path or metric
  metadata work.
- The open questions remain documented so a later plan can answer them with real
  usage evidence.
- Existing baseline gate behavior remains unchanged.

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

Bakeoff implication: metric verifiers should report run count and method first.
More statistical fields can come later after the simpler metadata has proven
useful. Bakeoff does not need to become the statistics package; the verifier
command can do the domain-specific comparison and emit final JSON.

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

## Rollback Notes

The implementation should be additive and easy to unwind:

- `build.protected_paths` is opt-in. Removing the field returns a work order to
  the previous behavior.
- `metric.min_runs` is opt-in. Removing it returns metric selection to the
  previous single-value behavior, though docs should continue to recommend
  repeated measurements.
- Optional metric metadata is additive. Older consumers can ignore the extra
  fields in metric artifacts and summaries.
- Protected-path enforcement does not add a new public decision kind in v1;
  rollback is removing `build.protected_paths` or disabling the protected-path
  eligibility check while retaining captured protected-path artifacts for audit.
- No data migration is required; all changes affect work-order validation,
  prompts, run artifacts, and report/summary rendering.

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

1. Implement Phase 1 prompt tightening and Phase 3 `build.protected_paths` as
   one releasable milestone. Phase 1 may be committed first internally, but it
   must be described as advisory until Phase 3 enforcement is present.
2. Ship Phase 2 docs, examples, and validate warnings with the protected-path
   milestone so users can discover and recover from the feature.
3. Add the identical-patch tie guard with the protected-path decision work.
4. Implement the limited Phase 4 metric metadata v1, `metric.min_runs`, and
   separate effect-size/noise-floor reporting.
5. Revisit Phase 5 only after real work orders show repeated need for
   fail-to-pass target gates.

This order keeps the cheap safety wins first and avoids turning Bakeoff into a
larger benchmark orchestration system before the current pairwise contract needs
it.
