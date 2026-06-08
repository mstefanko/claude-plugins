# Single-Provider Run Mode Option 4 Implementation Plan

Date: 2026-06-08

Status: proposed implementation plan

Scope: add an intentional one-provider run shape to Bakeoff core without
turning Bakeoff into an experiment scheduler or weakening existing pairwise
bakeoffs.

## Summary

Add a core `run_mode` field with two values:

```json
"run_mode": "pairwise"
```

```json
"run_mode": "single_provider"
```

`pairwise` remains the default and requires exactly two provider entries.
`single_provider` requires exactly one provider entry, skips the judge phase,
and records the result as an intentional single-provider run rather than as a
degraded two-provider run.

This is option 4: allow single-provider work orders directly. It is not an
experiment-only subcommand, not an automatic baseline attached to every
bakeoff, and not an N-provider framework.

The important distinction:

- `providers: [claude-a, claude-b]` with the same backend/model remains a
  pairwise same-model duplicate run.
- `run_mode: "single_provider"` with `providers: [claude]` is a one-provider
  baseline or one-off run.
- `single_provider_only` remains a degraded pairwise survivor state, not the
  name of an intentional baseline.

## Recommendation

Implement `single_provider` as a small Bakeoff-core run primitive.

This belongs in core because it affects validation, prompt wording, runner
branching, decisions, reports, manifests, and build patch handoff. A wrapper
script can schedule repetitions and attach experiment labels, but it cannot
cleanly prevent core from misreporting a one-provider run as "only one provider
survived" or "winner."

Keep the feature deliberately narrow:

- one provider only;
- no judge;
- no automatic paired baseline scheduling;
- no matrix runner;
- no statistics or cross-run aggregation;
- no changes to the default Claude + Codex pair.

## Why Not An Experiment-Only Feature

An experiment runner could create a baseline run outside Bakeoff, but the run
itself still needs valid core semantics:

- `work-order.json` must validate with one provider;
- worker prompts must not reference peer workers or judges;
- `decision.json` must avoid fake comparative winners;
- `manifest.json`, `summary.json`, `ls --json`, `show`, and `runs verify` must
  describe the run correctly;
- build mode must still expose a usable selected patch when a single provider
  passes gates.

That makes `single_provider` a core execution mode. Experiment scripts can sit
above it later.

## Existing Implementation State

The runner loops are mostly close to ready because they already iterate over
`wo.Providers`. The missing pieces are the two-provider contracts embedded
around those loops.

### Work Order Validation

`internal/workorder/workorder.go` currently requires exactly two providers:

```go
if !ok || len(items) != 2 {
	return nil, Validationf("providers must have exactly 2 entries")
}
```

It also reserves but rejects the experiment run kind:

```go
if runKind == "single_agent_baseline" {
	return nil, Validationf("experiment.run_kind single_agent_baseline is reserved but not executable in this version")
}
```

`internal/workorder/draft.go` also rejects explicit provider lists unless they
contain exactly two entries. Drafting must be updated too, or hand-written
single-provider work orders would be the only usable path.

### Same-Provider Duplicate Runs

Same-model duplicate support is already scoped correctly:

```go
func SameBackendModelScopeRun(wo *WorkOrder) bool {
	return wo != nil && len(wo.Providers) == 2 && SameBackendModelScope(wo.Providers[0], wo.Providers[1])
}
```

Do not change that helper to include single-provider runs. A same-provider
duplicate run is two independent attempts with two unique provider IDs; a
single-provider run is one attempt.

### Research Command

`internal/commands/researchcmd/run.go` currently maps one successful provider
to degraded pairwise decision kind `single_provider_only`:

```go
} else if len(okResults) == 1 {
	decisionDoc = decision.SingleProviderOnly(wo, workerResults, survivor)
} else {
	judgePhase, err := runJudgePhase(...)
```

For `run_mode: "single_provider"`, that branch should become an intentional
single-provider result. Pairwise mode should continue to use
`single_provider_only` when exactly one of two providers succeeds.

The judge phase hard-indexes two providers:

```go
providerIDs := []string{wo.Providers[0].ID, wo.Providers[1].ID}
```

Single-provider runs must never call this path.

### Build Command

Build provider execution already loops over providers and should work with one
provider after validation allows it.

`internal/buildverify/buildverify.go` already skips metric comparisons unless
there are exactly two providers:

```go
if len(providerOrder) != 2 {
	return nil
}
```

`internal/commands/buildcmd/judge.go` skips the judge unless exactly two
eligible patches passed gates:

```go
if len(gatePassed) != 2 {
	return false
}
```

That is the right behavior. The decision layer still needs cleanup because
`internal/decision/decision.go` treats one captured passing patch as
`single_provider_only` with a `canonical_winner`.

### Prompt Fixtures

Worker prompts mention peers and judges, for example:

```text
A separate judge will deduplicate your output against a peer worker's output later.
```

Single-provider prompts need conditional wording so the provider is asked for a
standalone result instead of preparing for a comparison that will not happen.

### Reports, Summaries, Manifests, And Listings

Current reports special-case `single_provider_only` as a partial/degraded state.
That is correct for pairwise survivor runs, but wrong for intentional baselines.

Manifest and summary output currently expose `decision_kind`,
`canonical_winner`, and judge fields, but not the run shape. Add `run_mode` and
single-provider identity fields so downstream scripts can separate:

- pairwise run;
- same-model duplicate pairwise run;
- intentional single-provider baseline;
- degraded pairwise survivor.

### Triage

`internal/triage/state.go` suppresses auto-triage for `single_provider_only`.
Intentional single-provider code-review runs should also avoid automatic
triage by default. They are useful as baseline evidence, but triage introduces
another model pass and makes baseline purity harder to reason about.

The current switch suppresses only `both_failed`, `single_provider_only`, and
`tie`. A new `single_provider_result` would otherwise fall through to the
default code-review auto-triage path. This change must explicitly suppress
`single_provider_result` and `single_provider_failed`, and add recommendation
messages that distinguish intentional baselines from degraded pairwise survivor
runs.

### Rerun

`bakeoff rerun --judge-only` currently rejects build runs before calling the
research judge-only path, but it does not reject one-provider research source
runs. The new run mode needs an early rerun validation error so a
single-provider source run never reaches a two-provider judge path.

### Escalation

`bakeoff escalate` currently rejects build source runs, then loads the source
work order, decision, report, provider finals, and source decision. Its source
decision packet copies `canonical_winner`, and the command is built around
adding another opinion to an existing research result.

The first single-provider implementation should reject intentional
single-provider source runs with a clear message. Turning a baseline into a
later comparison can be useful, but it needs a separate decision contract.

### Manifest Telemetry

Manifest telemetry already handles one provider for backend family diversity,
but the new run mode needs tests that lock the intended single-provider values
instead of relying on incidental behavior.

## User-Facing Behavior

### Default Pairwise Run

No behavior change:

```json
{
  "type": "gather",
  "run_mode": "pairwise",
  "providers": [
    { "id": "claude", "backend": "claude", "model": "sonnet", "scope": "codebase" },
    { "id": "codex", "backend": "codex", "model": "gpt-5.5", "scope": "codebase" }
  ]
}
```

If `run_mode` is omitted, it defaults to `pairwise`.

### Same-Provider Duplicate Pairwise Run

Still valid and still two providers:

```json
{
  "run_mode": "pairwise",
  "providers": [
    { "id": "claude-a", "backend": "claude", "model": "sonnet", "scope": "codebase" },
    { "id": "claude-b", "backend": "claude", "model": "sonnet", "scope": "codebase" }
  ]
}
```

This gets same-model duplicate warnings and report caveats. It is duplicate
sampling, not independent model-family corroboration.

### Intentional Single-Provider Run

New valid shape:

```json
{
  "run_mode": "single_provider",
  "providers": [
    { "id": "claude", "backend": "claude", "model": "sonnet", "scope": "codebase" }
  ]
}
```

No judge should run. Reports should say "Single-provider result" or
"Single-provider patch" rather than "Winner."

### Experiment Baseline Label

Allow this only with `run_mode: "single_provider"`:

```json
{
  "experiment": {
    "id": "exp-2026-06-08-baselines",
    "task_id": "review-auth-flow",
    "condition_id": "claude-single",
    "run_kind": "single_agent_baseline",
    "repetition_index": 1
  }
}
```

Reject `experiment.run_kind: "single_agent_baseline"` for pairwise runs.

`run_mode` and `experiment.run_kind` are orthogonal:

- `run_mode` controls execution shape: one provider or two providers.
- `experiment.run_kind` labels the run's role in external analysis.

Legal combinations for this first implementation:

- `run_mode: "pairwise"` with `run_kind: "pairwise"`, `"ad_hoc"`,
  `"multi_lens_child"`, `"split_child"`, or `"rerun"`;
- `run_mode: "single_provider"` with `run_kind:
  "single_agent_baseline"`, `"ad_hoc"`, or `"rerun"`;
- no `experiment` object at all, for ordinary one-off runs.

Reject `run_mode: "single_provider"` with `run_kind: "pairwise"`,
`"multi_lens_child"`, or `"split_child"` in v1. Multi-lens and split
single-provider children are out of scope until a concrete scheduler or child
generator needs them.

## Decision Contract

### Pairwise Survivor Decision

Keep current degraded pairwise behavior:

```json
{
  "decision_kind": "single_provider_only",
  "canonical_winner": "claude",
  "judge_ran": false,
  "caveats": [
    "single_provider_only: codex timeout; no comparison possible - surfacing claude result only"
  ]
}
```

This means two providers were planned and one did not produce usable evidence.

### Intentional Research Single-Provider Decision

Add:

```json
{
  "decision_kind": "single_provider_result",
  "selection_basis": "none",
  "canonical_winner": null,
  "single_provider": "claude",
  "judge_ran": false,
  "judge_attempted": false,
  "judge_completed": false,
  "caveats": []
}
```

For a failed single-provider research run, use existing failure semantics where
possible:

```json
{
  "decision_kind": "single_provider_failed",
  "selection_basis": "none",
  "canonical_winner": null,
  "single_provider": "claude",
  "judge_ran": false,
  "stalled_at": "providers"
}
```

Use `single_provider_failed` rather than overloading `both_failed`. The feature
already needs report and summary changes, and a distinct failure kind keeps
baseline rows separate from pairwise runs where two planned providers failed.

### Intentional Build Single-Provider Decision

Build mode has a practical patch-handoff need. Do not force users to fish
through artifacts when a single provider produced a verified patch.

Recommended contract:

```json
{
  "decision_kind": "single_provider_result",
  "selection_basis": "gate",
  "canonical_winner": null,
  "single_provider": "claude",
  "selected_patch_provider": "claude",
  "selected_patch_path": "providers/claude/build/diff.patch",
  "judge_ran": false
}
```

This preserves useful build handoff while avoiding the false claim that Claude
"won" a comparison.

For backward compatibility, selected patch helpers should read
`selected_patch_provider` first and fall back to `canonical_winner` for old
pairwise build runs.

## Schema And Validation Plan

1. Add constants:
   - `RunModePairwise = "pairwise"`
   - `RunModeSingleProvider = "single_provider"`

2. Add `RunMode string` to `workorder.WorkOrder`.

3. Extend known top-level keys to allow `run_mode`.

4. During validation:
   - default empty `run_mode` to `pairwise`;
   - reject unknown `run_mode`;
   - require exactly two providers for `pairwise`;
   - require exactly one provider for `single_provider`;
   - keep provider IDs unique;
   - allow duplicate backend/model/scope only through existing pairwise logic.

5. Extend experiment validation:
   - add `single_agent_baseline` to allowed experiment run kinds;
   - require `run_mode == "single_provider"` when `run_kind ==
     "single_agent_baseline"`;
   - reject `single_agent_baseline` for pairwise duplicate runs;
   - allow `single_provider` experiment runs only with
     `single_agent_baseline`, `ad_hoc`, or `rerun`;
   - reject `single_provider` with `multi_lens_child` or `split_child`.

6. Update `workorder.ExperimentMap` and any copied metadata plumbing only if
   needed. Existing experiment metadata projection should otherwise continue to
   work.

7. Update the top-level required/known field handling in
   `internal/workorder/workorder.go` so `run_mode` is accepted and defaulted
   before provider-count validation.

8. Keep `judge` required in the v1 work-order schema for compatibility unless
   a separate schema change explicitly makes it optional. In `single_provider`
   mode the judge config is allowed but unused; all judge execution and judge
   completion fields must remain false/not-run.

## Research Runner Plan

1. After `runWorkers`, branch on `wo.RunMode`.

2. For `single_provider`:
   - if the provider succeeded, call a new `decision.SingleProviderResult`;
   - if it failed, call a new `decision.SingleProviderFailed`;
   - never call `runJudgePhase`;
   - write an empty judge summary or `status: "not_run"`;
   - skip auto-triage by default.

3. For `pairwise`, keep the existing behavior:
   - zero successful providers: `both_failed`;
   - one successful provider: `single_provider_only`;
   - two successful providers: judge phase.

4. Add a defensive guard in `runJudgePhase` that returns a validation/runtime
   error unless `len(wo.Providers) == 2`. This protects future call sites.

## Build Runner Plan

1. Let baseline verification run unchanged.

2. Let provider execution run over the single provider.

3. Let metric comparison return nil for non-two-provider runs, as it already
   does.

4. Ensure `buildJudgeNeeded` remains false for single-provider runs.

5. Add an intentional single-provider branch in build decision resolution:
   - captured patch plus gates passed: `single_provider_result`,
     `selection_basis: "gate"`, `selected_patch_provider` set, exit 0;
   - captured patch plus gates failed: `single_provider_failed`, no selected
     patch, `stalled_at: "provider_verify"`, exit failed or unresolved
     according to existing build semantics;
   - no captured patch: `single_provider_failed`, no selected patch.

6. Update selected patch helpers:
   - prefer `decision["selected_patch_provider"]`;
   - fall back to `decision["canonical_winner"]`;
   - continue to emit existing selected patch paths for old pairwise decisions.

7. Update `runs verify` dynamic required artifacts so it uses the selected
   patch provider fallback logic instead of only `canonical_winner`.

## Cross-Command Plan

### Triage

Update `internal/triage/state.go`:

- add `single_provider_result` and `single_provider_failed` to the
  `ShouldAutoTriage` suppression case;
- add `ShouldRecommendTriage` messages for intentional single-provider results
  and failures;
- keep the existing `single_provider_only` message as the degraded pairwise
  survivor message.

Intentional baseline message:

```text
single-provider baseline; inspect provider output and run triage explicitly if needed
```

Failure message:

```text
single-provider run failed; inspect decision.json before acting
```

### Rerun

Update `internal/commands/reruncmd/rerun.go`:

- preserve `run_mode` on full reruns;
- reject `--judge-only` when the loaded source work order has
  `run_mode: "single_provider"`;
- use a clear validation message such as
  `--judge-only requires a pairwise source run with judge evidence`.

Also add a defensive validation check in the research judge-only command path
so direct internal calls cannot reach a two-provider judge with one provider.

### Escalate

Update `internal/commands/escalatecmd/escalate.go`:

- reject source runs with `run_mode: "single_provider"` or decision kind
  `single_provider_result` / `single_provider_failed`;
- use a clear validation message such as
  `single-provider source runs cannot be escalated yet; run a pairwise bakeoff for comparison`;
- add tests for both success-path pairwise escalation still working and
  single-provider source rejection.

Do not try to turn escalation into "add a second provider to the baseline" in
this change. That is useful, but it needs a separate decision contract.

## Prompt Plan

Do not fork every fixture if a small conditional block will do.

Recommended approach:

1. Add a placeholder such as `<run_mode_instructions>` to worker prompt
   fixtures.

2. In `internal/prompt/prompt.go`, replace it with pairwise or single-provider
   text:

   Pairwise:

   ```text
   A separate judge will compare your output against a peer worker's output later.
   ```

   Single-provider:

   ```text
   This is a standalone single-provider run. Produce the best complete result
   you can; no peer worker or judge will merge, compare, or rescue the output.
   ```

3. For gather prompts, avoid "deduplicate against a peer" in single-provider
   mode.

4. For compare/analyze prompts, avoid telling the worker to mount a case for a
   judge. Ask for the strongest standalone answer instead.

5. Build prompts can keep most wording if they focus on producing a patch, but
   should not reference a competing provider or judge when in single-provider
   mode.

## Report, Summary, Manifest, And Listing Plan

### `decision.json`

Add fields:

- `run_mode`
- `single_provider` when applicable
- `selected_patch_provider` for build when a patch is selected
- `selected_patch_path` for build when a patch is selected

### `summary.json`

Research summary:

- add `run_mode`;
- add `single_provider`;
- keep `canonical_winner: null` for intentional single-provider runs;
- set judge status to `not_run`.

Build summary:

- add `run_mode`;
- add `single_provider`;
- keep existing `selected_patch_status`;
- emit `selected_patch_provider` and `selected_patch_path` when available.

### `manifest.json`

Add:

- `run_mode`;
- `single_provider`;
- `selected_patch_provider` when applicable;
- preserve existing `canonical_winner` for pairwise compatibility;
- keep telemetry provider count and diversity calculations working with one
  provider;
- for intentional single-provider runs, expect telemetry provider fields:
  - `providers.count: 1`;
  - `providers.backends: ["<backend>"]`;
  - `providers.families: ["<family>"]` when the backend family is known;
  - `providers.family_diversity: "single"` when the backend family is known;
  - `judge.ran: false`;
  - `judge.completed: false`;
  - `judge.winner_backend: null`;
  - `judge.winner_family: null`.

### `ls --json`

Project:

- `run_mode`;
- `single_provider`;
- `selected_patch_provider` for build rows if present.

Filtering by run mode can be deferred. The first implementation only needs the
field in JSON output.

### Reports

Research reports:

- header should render `Run mode: single_provider`;
- result line should say `Result: single-provider result`;
- no `Winner:` line;
- no `Partial result:` note.

Build reports:

- say `Selected patch provider: claude` or `Single-provider patch: claude`;
- avoid `Winner:` for intentional single-provider runs;
- keep existing handoff advisory when a patch is selected.

## Triage Plan

For intentional single-provider gather/code-review runs:

- do not auto-start triage;
- explicitly add `single_provider_result` and `single_provider_failed` to
  `ShouldAutoTriage` suppression;
- add `ShouldRecommendTriage` messages that distinguish intentional baselines
  from degraded pairwise survivor runs;
- recommend manual inspection or explicit triage if the user asks for it;
- avoid treating baseline output as judge-deduplicated findings.

This mirrors the current caution around `single_provider_only`, but the message
should distinguish intentional baseline from degraded pairwise survivor.

## Drafting And Skill Plan

Update natural-language drafting so `single_provider` appears only when the
user explicitly asks for it:

- "single agent baseline";
- "single provider";
- "Claude only";
- "Codex only";
- "run just Claude";
- "baseline run with one agent".

Do not draft `single_provider` when the user says:

- "Claude + Claude";
- "two Claude attempts";
- "same provider twice";
- "duplicate run".

Those remain pairwise same-model duplicate runs with two provider IDs.

Update `skills/bakeoff-run/SKILL.md` to teach the same distinction.

## Documentation Plan

Update:

- `README.md`
- `docs/work-orders.md`
- `docs/cli-reference.md`
- `docs/artifacts-and-ledger.md`
- `examples/README.md`
- `examples/repetition-loop.sh`, if it should demonstrate single-provider
  baselines in an experiment loop
- `skills/bakeoff-run/SKILL.md`

Docs should use three examples side by side:

1. normal pairwise Claude + Codex;
2. same-provider duplicate Claude + Claude;
3. intentional single-provider Claude-only baseline.

## Test Plan

### Work Order Validation

- accepts omitted `run_mode` with exactly two providers;
- accepts `run_mode: "pairwise"` with exactly two providers;
- rejects `pairwise` with one provider;
- accepts `single_provider` with one provider;
- rejects `single_provider` with two providers;
- rejects unknown `run_mode`;
- accepts `experiment.run_kind: "single_agent_baseline"` only for
  `single_provider`;
- accepts `single_provider` with `experiment.run_kind: "ad_hoc"` and
  `"rerun"`;
- rejects `single_provider` with `experiment.run_kind: "pairwise"`,
  `"multi_lens_child"`, or `"split_child"`;
- keeps same-provider duplicate validation and advisory tests unchanged.

### Research Runs

- single-provider gather success:
  - one provider artifact directory;
  - no judge artifacts;
  - `decision_kind: "single_provider_result"`;
  - `canonical_winner: null`;
  - `single_provider` set;
  - report has no winner line.

- single-provider compare/analyze success:
  - no swapped judge;
  - no comparison/overlay language that implies a peer result.

- single-provider failure:
  - no judge;
  - `decision_kind: "single_provider_failed"`;
  - `stalled_at` set appropriately.

- pairwise one-provider survivor still produces `single_provider_only`.

### Build Runs

- single-provider build with passing gates:
  - no judge;
  - `decision_kind: "single_provider_result"`;
  - `canonical_winner: null`;
  - `selected_patch_provider` set;
  - `selected_patch_status: "selected"`;
  - `runs verify` requires selected patch artifacts.

- single-provider build with failing gates:
  - no selected patch;
  - no judge;
  - `decision_kind: "single_provider_failed"`;
  - `stalled_at: "provider_verify"`.

- pairwise build with one surviving patch keeps existing
  `single_provider_only` behavior.

- same-model duplicate build tests continue to pass unchanged.

### Commands And Artifacts

- `bakeoff validate` prints no same-model duplicate advisory for
  single-provider runs.
- `bakeoff show` renders single-provider result correctly.
- `bakeoff ls --json` includes `run_mode` and `single_provider`.
- `bakeoff runs verify` validates selected build patch using
  `selected_patch_provider`.
- `bakeoff rerun` preserves `run_mode`.
- judge-only rerun rejects single-provider runs.
- `bakeoff escalate` rejects single-provider source runs with a clear message.
- intentional single-provider code-review runs do not auto-start triage.

### Manifest Telemetry

- single-provider known backend:
  - provider count is 1;
  - backend list contains the one backend;
  - family list contains the one known family;
  - family diversity is `single`;
  - judge ran/completed are false;
  - winner backend/family are null.

- single-provider unknown backend:
  - provider count is 1;
  - backend list contains the one backend;
  - family list is empty;
  - family diversity is `unknown`;
  - winner backend/family are null.

## Migration And Backward Compatibility

Existing work orders without `run_mode` default to `pairwise`.

Existing run artifacts remain valid:

- old `single_provider_only` decisions keep their current meaning;
- old build selected patch logic still works through `canonical_winner`;
- new helpers should fall back to `canonical_winner` when
  `selected_patch_provider` is absent.

No manifest schema bump is required if new fields are additive and optional,
but tests should confirm `ls --json` and `runs verify` remain compatible with
older manifests.

## Implementation Order

1. Add `run_mode` schema, defaults, and validation.

2. Add decision constructors for intentional single-provider research/build
   results.

3. Branch research runner before judge phase.

4. Branch build decision resolution and selected patch helpers.

5. Add triage, rerun judge-only, and escalation guards.

6. Add report, summary, manifest, listing, telemetry, and verify projections.

7. Add prompt conditional wording.

8. Update drafting and `bakeoff-run` skill rules.

9. Update docs and examples.

10. Run focused tests:

   ```sh
   go test ./internal/workorder ./internal/commands/researchcmd ./internal/decision ./internal/report ./internal/commands/buildcmd ./internal/buildverify ./internal/manifest ./internal/summary ./internal/commands/lscmd ./internal/commands/showcmd ./internal/verify ./internal/commands/validatecmd ./internal/commands/reruncmd ./internal/commands/escalatecmd ./internal/triage
   ```

11. Run full test suite if focused tests pass:

   ```sh
   go test ./...
   ```

## Non-Goals

- No `bakeoff experiment run` command.
- No automatic baseline alongside every pairwise bakeoff.
- No provider matrix scheduler.
- No repeated-run manager.
- No CSV/JSONL aggregate exporter in this change.
- No evaluator packs.
- No trace normalization.
- No N-provider work orders.
- No majority voting.
- No single-provider multi-lens or split-child scheduler.
- No baseline-to-comparison escalation flow in this change.

## Resolved Decisions

1. Failed intentional single-provider runs use `single_provider_failed`, not
   `both_failed`.

   Reason: this feature already touches decision/report/summary semantics, and
   separate failure rows are cleaner for later analysis.

2. Build verifier failures also use `single_provider_failed`; do not add a
   third decision kind such as `single_provider_failed_verification`.

   Reason: `selection_basis`, `stalled_at`, provider statuses, and selected
   patch status carry the verifier details without expanding the enum.

3. Build reports use the phrase "Selected patch provider" or
   "Single-provider patch"?

   Decision: use "Selected patch provider" in JSON and "Single-provider patch"
   in human reports.

4. `bakeoff ls` does not get a `--run-mode` filter immediately.

   Reason: adding `run_mode` to JSON is enough for the first implementation.
   Filtering can come once experiments produce enough runs that it is needed.

5. Single-provider code-review gather runs do not auto-triage.

   Reason: keep baseline runs clean by default; allow explicit triage as a
   separate operator action.
