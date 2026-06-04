# Same-Model Duplicate Provider Implementation Plan

Date: 2026-06-01

Status: proposed

Scope: allow explicit two-worker duplicate runs such as Claude + Claude or
Codex + Codex without changing Bakeoff's canonical default pair.

## Summary

Add support for exactly two independent attempts from the same backend/model
when the user explicitly asks for that shape or supplies a work order with two
unique provider IDs.

Default generated work orders stay unchanged:

- Worker A: `claude` / `sonnet`
- Worker B: `codex` / `gpt-5.5`
- Judge: `claude` / `opus`

The new capability is only this:

```json
"providers": [
  { "id": "claude-a", "backend": "claude", "model": "sonnet", "scope": "codebase", "effort": "high" },
  { "id": "claude-b", "backend": "claude", "model": "sonnet", "scope": "codebase", "effort": "high" }
]
```

The implementation should treat `providers[].id` as the attempt identity and
artifact/worktree key. `backend`, `model`, and `scope` are the current
deduplication key that blocks same-model pairs; `effort` is not part of that
existing key. For the exact duplicate baseline, both workers should receive the
same prompt, same scope, same tools, same effort, same runtime budgets, and
separate artifact directories or build worktrees.

Do not add N-agent work orders, debate rounds, worker personas, provider-level
facets, shared memory, or a new scheduler.

## Research Basis

The research supports same-model duplicate runs as a small repeated-sampling
primitive, not as proof by consensus.

- Wang et al.,
  [Self-Consistency Improves Chain of Thought Reasoning in Language Models](https://arxiv.org/abs/2203.11171):
  repeatedly samples the same model on the same task and aggregates independent
  reasoning paths. The setup supports identical prompts and independent samples.
  Its strongest aggregation method is majority vote, which does not apply cleanly
  to exactly two Bakeoff workers.
- Li et al.,
  [More Agents Is All You Need](https://arxiv.org/abs/2402.05120):
  evaluates repeated querying of the same LLM or agent framework. It supports
  parallel independent attempts, but open-ended and code tasks still need a
  strong selector instead of simple frequency voting.
- Brown et al.,
  [Large Language Monkeys: Scaling Inference Compute with Repeated Sampling](https://arxiv.org/abs/2407.21787):
  supports repeated same-model candidate generation, especially when an external
  verifier can select candidates. This maps well to Bakeoff build mode where
  gates and metrics should dominate judge opinion.
- Du et al.,
  [Improving Factuality and Reasoning in Language Models through Multiagent Debate](https://arxiv.org/abs/2305.14325):
  starts with multiple same-model agents answering independently, then adds
  debate rounds. The initial independent round is relevant; the debate loop is
  intentionally out of scope because it adds sequencing, coordination, and
  failure modes.
- Wang et al.,
  [Large Language Models are not Fair Evaluators](https://arxiv.org/abs/2305.17926):
  documents position bias and motivates Bakeoff's existing A/B and B/A swapped
  judging. Same-model duplicate runs should still use swapped judging because
  position bias is separate from model-family bias.
- Zheng et al.,
  [Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena](https://arxiv.org/abs/2306.05685):
  supports LLM judges as useful but imperfect rubric evaluators. It reinforces
  that judges are evidence summarizers, not ground truth.
- Research on LLM judge self-preference, including
  [Self-Preference Bias in LLM-as-a-Judge](https://arxiv.org/abs/2410.21819),
  supports treating same-family judge results cautiously. For a Claude + Claude
  run, a Claude judge is acceptable as a fallback, but a ready non-contestant
  judge such as Codex is preferable when validation and provider support allow
  it.
- Verga et al.,
  [Replacing Judges with Juries](https://arxiv.org/abs/2404.18796):
  supports judge diversity as a mitigation. Bakeoff should not add a jury in
  this change; a single cross-family judge is the small version that fits the
  existing pairwise design.

Research implication: v1 should use independent parallel duplicate attempts
with identical prompts when the execution settings match, then rely on
deterministic verifiers first and swapped, anonymized, preferably cross-family
judging second.

## Goals

- Allow explicit Claude + Claude and Codex + Codex work orders.
- Preserve exactly two worker providers.
- Preserve the Claude + Codex generated default.
- Keep all run artifacts under the existing `providers/<provider-id>/` layout.
- Preserve build isolation by creating one worktree per provider ID.
- Preserve swapped judging for compare, analyze, and build.
- Prefer a non-contestant judge family for same-model duplicates when available,
  but allow same-family judging with clear warnings.
- Make duplicate-run caveats visible in preview, validation, reports, or all
  three where practical.

## Non-Goals

- Do not change the default pair away from Claude + Codex.
- No automatic same-model fallback when Codex or Claude is missing.
- No three-provider or N-provider work-order schema.
- No majority voting.
- No debate rounds or sequential peer feedback.
- No personas or "lens A vs lens B" prompt changes in the duplicate baseline.
- No provider-level facets.
- No automatic judge switching for existing work-order files.
- No full judge jury or multi-judge panel.
- No hidden model discovery or model router.

## User-Facing Behavior

### Natural-Language Drafting

Only draft duplicate providers when the user explicitly asks for the same
provider twice, for example:

```text
/bakeoff:run research this with Claude + Claude
/bakeoff:run build with two Claude attempts ...
/bakeoff:run compare with Codex + Codex
```

For implicit provider choice, keep the current doctor-selected pair behavior.
The normal path remains Claude + Codex when both are ready.

If the user asks for "two Claude attempts", "Claude twice", or "Claude +
Claude", draft:

```json
"providers": [
  { "id": "claude-a", "backend": "claude", "model": "sonnet", "scope": "<mode scope>", "effort": "high" },
  { "id": "claude-b", "backend": "claude", "model": "sonnet", "scope": "<mode scope>", "effort": "high" }
]
```

If the user asks for "Codex + Codex", draft `codex-a` and `codex-b` with the
current Codex default model.

The preview should include this note:

```text
Same-model note: this runs two independent attempts with the same backend,
model, scope, and prompt. Treat agreement as duplicate sampling, not independent
model corroboration; there is no majority vote with two workers.
```

### Judge Selection In Drafts

For same-model duplicate natural-language drafts:

- Claude + Claude: prefer `codex/gpt-5.5` as judge when doctor reports Codex
  ready.
- Codex + Codex: prefer `claude/opus` as judge when Claude is ready.
- Gemini + Gemini or Copilot + Copilot, if later supported by explicit user
  choice, prefer a ready judge from a different provider family.
- If no cross-family judge is ready, keep the default generated judge when it
  validates and show a same-family warning.

This is a draft-time preference, not a runtime mutation. Existing work-order
paths should run exactly as authored after validation.

Preview text when cross-family judge is available:

```text
Judge note: using Codex as a non-contestant judge for this Claude + Claude run.
Verifier evidence and swapped judging still matter more than judge preference.
```

Preview text when falling back to same-family judge:

```text
Judge note: the judge shares provider-family metadata with both workers. This is
allowed, but judge-heavy conclusions are less independent; prefer verifier
evidence or rerun with a non-contestant judge when available.
```

### Manual Work Orders

Manual work orders may use same backend/model/scope as long as provider IDs are
unique. The CLI should validate the example below:

```json
{
  "schema_version": 1,
  "id": "same-claude-example",
  "type": "compare",
  "goal": "Compare approach A and approach B.",
  "background": "Decision criteria and evidence.",
  "providers": [
    { "id": "claude-a", "backend": "claude", "model": "sonnet", "scope": "mixed", "effort": "high" },
    { "id": "claude-b", "backend": "claude", "model": "sonnet", "scope": "mixed", "effort": "high" }
  ],
  "judge": { "backend": "codex", "model": "gpt-5.5", "effort": "xhigh" },
  "budgets": {
    "wall_clock_seconds": 900,
    "max_output_bytes": 60000,
    "heartbeat_seconds": 60,
    "output_cap_grace_seconds": 10,
    "max_output_overrun_bytes": 60000
  }
}
```

## Implementation Details

### 1. Work-Order Validation

File:

- `internal/workorder/workorder.go`

Change `validateProviders`:

- Keep `providers` length exactly `2`.
- Keep `providers[].id` required and unique.
- Keep valid backend, model, scope, and effort validation.
- Keep rejecting provider-level `facet`.
- Remove the hard error keyed by `backend + model + scope`. The current
  validation map is named `triples`, but it does not include `effort`:

```go
triples[participant.Backend+"\x00"+participant.Model+"\x00"+participant.Scope] = true
if len(triples) == 1 {
	return nil, Validationf("providers must differ on at least one of backend, model, or scope")
}
```

Do not replace it with schema fields such as `duplicate: true` or
`attempt_group`. The existing two-provider array plus unique IDs is enough.

If a helper is useful, keep it tiny and named after the actual current key:

```go
func SameBackendModelScope(a, b Participant) bool {
	return a.Backend == b.Backend &&
		a.Model == b.Model &&
		a.Scope == b.Scope
}
```

Do not define a broader execution-identity abstraction unless implementation
needs it. `effort` may still be compared in tests and warnings to distinguish
an exact duplicate baseline from a same backend/model/scope run with different
runtime effort.

### 2. Validate Warnings

File:

- `internal/commands/validatecmd/validate.go`

Add a warning in `validateWarnings` when both providers have the same
`backend`, `model`, and `scope`:

```text
same-model duplicate advisory: providers claude-a and claude-b share backend,
model, and scope. They are independent attempts, not independent model
corroboration; no majority vote is possible with two workers.
```

If the two providers also share `effort`, the advisory may call it an exact
duplicate baseline. If effort differs, keep validation successful but phrase the
warning as same backend/model/scope with different effort, not exact duplicate
sampling.

Do not rework the existing same-family judge helper in v1. Claude + Claude with
a Claude judge enters the `JudgeFamilyRelationSameAsAll` branch and currently
reports `all providers`; that is accurate enough for the first cut. The
duplicate advisory above carries the provider IDs.

Keep warnings advisory-only. Validation should still succeed.

### 3. Draft Build Provider Parsing

Files:

- `internal/commands/draftbuildcmd/draft_build.go`
- `internal/workorder/draft.go`

Change `parseProviderFlags` so repeated backend flags are allowed:

```text
bakeoff draft-build ... --provider claude --provider claude
```

This requires two concrete edits:

- remove the duplicate-backend rejection in `parseProviderFlags`;
- stop assigning `participant.ID = backend` inside the first parse loop when
  duplicate backends are present. Parse both flags first, compute IDs from the
  full pair, then build participants.

Desired output IDs:

- distinct backends keep existing IDs: `claude`, `codex`
- duplicate backend pair uses suffixes: `claude-a`, `claude-b`
- duplicate backend with explicit model keeps suffixes:
  `--provider claude:sonnet --provider claude:sonnet`
- same backend with different models also uses suffixes:
  `claude-a`, `claude-b`

Do not require a new CLI syntax for IDs in v1. If explicit provider IDs become
necessary later, add a separate `--provider-id` design instead of overloading
`backend:model`.

Implementation sketch:

```go
type parsedProviderFlag struct {
	Backend string
	Model   string
}

func providerIDsForFlags(parsed []parsedProviderFlag) []string {
	counts := map[string]int{}
	for _, p := range parsed {
		counts[p.Backend]++
	}
	seen := map[string]int{}
	ids := make([]string, len(parsed))
	for i, p := range parsed {
		if counts[p.Backend] == 1 {
			ids[i] = p.Backend
			continue
		}
		seen[p.Backend]++
		ids[i] = fmt.Sprintf("%s-%c", p.Backend, 'a'+seen[p.Backend]-1)
	}
	return ids
}
```

Since the command still accepts exactly two providers, suffix generation only
needs `-a` and `-b`.

### 4. Natural-Language Drafting Rules

File:

- `skills/bakeoff-run/SKILL.md`

Update provider-pair extraction rules:

- If the user explicitly names the same known provider twice, use a duplicate
  pair with generated IDs `<backend>-a` and `<backend>-b`.
- Do not treat "use Claude" as duplicate intent.
- Do not choose a duplicate pair as fallback when the canonical pair is
  degraded.
- Do not infer duplicate mode from "retry", "rerun", or "second opinion" unless
  the same provider is named twice or "same model twice" is explicit.
- In duplicate previews, include the same-model note.
- For duplicate natural-language drafts, prefer a ready cross-family judge when
  doctor data is already available. Do not run additional provider discovery
  beyond the existing doctor preflight.

Update build fast-path instructions:

- `draft-build` may receive repeated `--provider` flags when the user explicitly
  asks for duplicate providers.
- Pass duplicate provider flags in the order shown in preview.

### 5. Research Run Behavior

Files:

- `internal/commands/researchcmd/run.go`
- `internal/prompt/prompt.go`

No fanout architecture change should be needed.

Current behavior already:

- launches both workers through `errgroup` in `runWorkers`;
- keys artifacts by `participant.ID`;
- writes prompts to `providers/<id>/prompt.txt`;
- builds prompts from shared work-order fields plus backend prompt flavor;
- uses A/B and B/A swapped judging for compare and analyze.

Add tests proving that exact duplicate providers receive identical prompt text
for the same prompt flavor and repo-layout eligibility. If a prompt includes
provider ID in the future, this test should fail and force a conscious decision.

For gather/code-review, the judge produces a structured union, not a winner. The
report should continue to describe source labels as A/B or provider IDs, but it
should not upgrade confidence because both sources are the same model family.
The current judge fixture already says confidence reflects evidence strength,
not corroboration; keep that invariant.

### 6. Deferred Analyze Tie Behavior

Defer this from the v1 cut line.

Files:

- `internal/decision/decision.go`
- `internal/commands/researchcmd/run.go`

Current analyze fallback can choose provider A when swapped judges disagree and
claim counts are equal:

```go
tiebreak = "position_a"
```

For exact duplicate provider runs, that fallback is arbitrary. However, changing
it is more invasive than the core duplicate-provider enablement because analyze
currently returns exit `0` unconditionally after successful judge passes. A real
tie result would need both decision-shape work and an explicit exit-code
contract change.

Do not include this in the first implementation unless dogfood shows duplicate
analyze runs are a priority. If implemented later, do all of the following in
one change:

- If swapped judges agree, keep `decision_kind: "pick_winner"`.
- If swapped judges disagree and atomic claim counts differ, keep the existing
  `atomic_count` tiebreak, but include a same-model caveat.
- If swapped judges disagree and claim counts are equal for exact duplicate
  providers, return `decision_kind: "tie"`, `canonical_winner: nil`,
  `stalled_at: "selection"`, and a caveat:

```text
same-model duplicate analyze run had judge swap disagreement with no objective
tiebreak; inspect both analyses or rerun with a non-contestant judge
```

- Add an early tie branch before assigning `decision_kind: "pick_winner"` and
  `canonical_winner` in `ResolveAnalyze`.
- Update `runJudgePhase` so analyze returns exit `3` when the resolved decision
  is a tie. This is mandatory for a tie behavior change; otherwise the CLI would
  silently exit `0`.
- Update `/bakeoff:run` recovery guidance for analyze exit `3` if needed.

### 7. Build Run Behavior

Files:

- `internal/commands/buildcmd/run.go`
- `internal/commands/buildcmd/providers.go`
- `internal/commands/buildcmd/judge.go`
- `internal/decision/decision.go`

No worktree architecture change should be needed. Build already creates one
detached worktree per provider ID:

```go
path := filepath.Join(parent.Path, participant.ID)
```

For same-model duplicate runs:

- create `.../claude-a` and `.../claude-b` worktrees;
- run the same prompt and same verifier specs in each;
- let gates and metrics decide first;
- if both eligible patch digests are identical, keep current
  `selection_basis: "identical_patch"` tie behavior;
- if verifier evidence is inconclusive, run the existing swapped build judge.

Build judge payload currently exposes provider IDs in two places:

- top-level `provider_id` in `buildJudgePayload`;
- nested `verify.provider_id` produced by `compactVerifyResult`.

For duplicate providers, those fields can reveal same-backend identity and
invite familiarity bias. Add a judge-payload-specific anonymization path so the
judge sees positional candidate labels, verifier evidence, patch excerpts, and
diffstats, but not real provider IDs. Do not remove provider IDs from durable
operator artifacts.

If the judge payload keeps artifact paths such as `providers/claude-a/...`, that
also leaks the candidate ID. Prefer omitting judge-only path fields when the
prompt already includes the relevant excerpt or summary. Keep artifact paths in
the report and decision metadata for operator traceability.

Keep real provider IDs in:

- `decision.json.order_maps`
- `providers/<id>/...`
- `manifest.json`
- report artifact links

Do not hide IDs from the operator. Hide them only from the judge prompt when
possible.

### 8. Judge Selection And Swaps

Files:

- `skills/bakeoff-run/SKILL.md`
- `internal/commands/validatecmd/validate.go`
- optionally `internal/provider/provider.go`

Policy:

1. Still run swapped judging for compare, analyze, and build.
2. Prefer a judge whose provider family differs from all workers when drafting
   a same-model duplicate run and such a judge is already ready.
3. Allow same-family judges as fallback.
4. Warn that same-family judge results are less independent.
5. Do not add a `judge_policy` schema field in v1.
6. Do not auto-switch judges for existing work-order paths.

Rationale:

- Swapping addresses position bias.
- Cross-family judge selection addresses same-family/style/shared-blind-spot
  risk.
- These mitigations are complementary, so a Codex judge should still do A/B and
  B/A passes on a Claude + Claude run.

### 9. Artifacts, Manifest, And Reporting

Files:

- `internal/artifact/artifact.go`
- `internal/manifest/manifest.go`
- `internal/report/report.go`
- `internal/commands/buildcmd/report.go`

The existing artifact layout should continue working because it is keyed by
provider ID.

Do not add a `same_execution_identity` field to the manifest in v1. The report
caveat is enough, and the state is already derivable from `work-order.json` if a
future command needs it.

- `providers.count` remains `2`.
- `providers.backends` may be `["claude", "claude"]`.
- `providers.families` keeps the current manifest behavior.

Report caveat text should be enough for v1:

```text
Same-model duplicate run: both workers used claude/sonnet with the same scope.
Agreement is duplicate sampling, not independent model-family corroboration.
```

Do not add a new report section unless the warning is otherwise too easy to
miss.

### 10. Same-Provider Concurrency And Rate Limits

Same-model duplicate runs launch the same provider backend twice in parallel
because the existing research and build runners are parallel by design. Do not
add a sequential worker mode in v1; that would be a larger scheduling feature
for a risk that may or may not matter in practice.

Mitigation for the first cut:

- include a preview caveat that running the same provider twice can hit provider
  rate limits or local CLI concurrency limits sooner than a heterogeneous pair;
- rely on existing per-provider status, stderr, failure, and report artifacts
  when one duplicate attempt fails;
- add fake-provider coverage that a duplicate pair still writes separate
  artifacts when one provider exits with a rate-limit-like failure message;
- track real rate-limit or concurrency failures during dogfood before adding
  scheduler controls.

## Test Plan

### Work-Order Validation

Add tests in `internal/workorder/workorder_test.go`:

- exact duplicate providers with IDs `claude-a`, `claude-b` validate;
- duplicate provider IDs still fail;
- unknown backend still fails;
- provider-level `facet` still fails;
- judge with the same backend/model as either provider still fails;
- same backend/model/scope but different effort validates, because the removed
  dedupe key is backend/model/scope only.

### Validate Command Warnings

Add tests in `internal/commands/validatecmd/validate_test.go`:

- exact duplicate providers print the same-model duplicate advisory;
- same backend/model/scope with different effort prints an advisory but does not
  call the run an exact duplicate baseline;
- Claude judge on Claude + Claude may continue to say `all providers` in the
  existing judge-family advisory;
- Codex judge on Claude + Claude does not print same-family warning;
- compare/analyze/build and code-review gather contexts still trigger judge
  family warnings;
- ordinary gather without code-review facet keeps current warning suppression.

### Draft Build

Add tests in `internal/commands/draftbuildcmd/draft_build_test.go`:

- `parseProviderFlags([]string{"claude", "claude"})` returns IDs
  `claude-a`, `claude-b`;
- `parseProviderFlags([]string{"codex:gpt-5.5", "codex:gpt-5.5"})` returns
  `codex-a`, `codex-b`;
- distinct providers keep old IDs and ordering;
- single `--provider` still fails;
- generated duplicate build work order validates.

### Research Runner

Add tests in `internal/commands/researchcmd/run_test.go` or prompt tests:

- duplicate providers write separate `providers/claude-a` and
  `providers/claude-b` artifact directories;
- duplicate providers receive byte-identical prompt files when same backend,
  model, scope, effort, and repo-layout eligibility are equal;
- both providers launch through the parallel worker path;
- compare/analyze still write swapped judge prompts and order maps.

### Build Runner

Add tests in `internal/commands/buildcmd/run_test.go`:

- duplicate providers create distinct worktree metadata and artifact dirs;
- verifier results are keyed by duplicate provider IDs;
- identical patch digest behavior still produces a tie without judge;
- inconclusive verifier evidence still runs swapped build judge;
- judge prompt for duplicate providers does not expose `claude-a` and
  `claude-b` in top-level `provider_id`, nested `verify.provider_id`, or
  retained judge-only path fields.

### Provider Failure Isolation

Add fake-provider tests in research and/or build command packages:

- a duplicate pair can launch both attempts without artifact directory
  collision;
- if one duplicate attempt exits with a rate-limit-like stderr message, the
  failure artifact is captured under that provider ID and the sibling artifacts
  remain readable.

### Deferred Decision Logic

Only add these tests if the deferred analyze tie behavior is implemented:

- duplicate analyze with swap agreement still picks a winner;
- duplicate analyze with swap disagreement and different claim counts uses
  `atomic_count` with a caveat;
- duplicate analyze with swap disagreement and equal claim counts returns tie
  and exits `3`;
- non-duplicate analyze keeps current deterministic fallback unless separately
  changed.

## Experiment Plan

Measure same-model duplicate value before expanding the feature.

Suggested metrics from existing artifacts:

- duplicate output rate: compare `final.json` claim overlap for gather/analyze
  and patch digests for build;
- unique evidence yield: count claims or citations found by only one duplicate
  worker;
- verifier selection rate: how often gates/metrics pick a build winner without
  judge;
- judge instability: how often pass1/pass2 swapped judging disagrees;
- cross-family judge effect: compare same work orders judged by Claude vs Codex
  when both are available;
- cost and latency: use `wall_seconds`, output bytes, and provider status
  artifacts;
- human acceptance: track whether same-model duplicate runs produced actionable
  outcomes beyond a normal Claude + Codex run.

Initial dogfood matrix:

| Mode | Pair | Judge | What To Measure |
| --- | --- | --- | --- |
| gather/code-review | Claude + Claude | Codex if ready | unique findings, false positives, triage result |
| compare | Claude + Claude | Codex if ready | swap stability, consensus vs tie |
| analyze | Claude + Claude | Codex if ready | duplicate reasoning, unresolved ties |
| build | Claude + Claude | verifiers first, Codex judge if needed | patch diversity, gate pass rate, identical patch ties |
| build | Codex + Codex | verifiers first, Claude judge if needed | same as above |

Do not call this feature generally better until duplicate runs show enough
unique evidence or patch diversity to justify the doubled worker cost.

## Caveats

- Same-model agreement is not independent model-family corroboration.
- Two workers cannot produce a majority vote.
- A same-family judge can share style preferences or blind spots with the
  workers.
- A cross-family judge is not automatically correct; it is just less entangled
  with the contestants.
- Swapped judging remains necessary even with a cross-family judge because
  position bias is separate from family bias.
- Build verifiers are stronger than judge preferences, but tests are still not
  proof of full correctness.
- Duplicate attempts may collapse to near-identical outputs if backend sampling
  is too deterministic.
- Running the same provider twice can hit provider CLI rate limits or local
  concurrency limits sooner than heterogeneous runs.

## Bloat Risks To Avoid

- Do not add `providers[]` length greater than two.
- Do not add `attempts`, `samples`, `debate_rounds`, `roles`, `personas`, or
  `provider_facets` fields.
- Do not create a batch schema for duplicate runs.
- Do not add a generalized same-model experiment framework before dogfood.
- Do not add judge juries in v1.
- Do not make duplicate providers a fallback default.
- Do not combine duplicate outputs into a synthesized third patch.
- Do not mutate existing work orders to "improve" judge independence.
- Do not describe same-model agreement as higher confidence unless evidence
  strength independently supports the claim.

## Implementation Order

1. Allow duplicate `backend + model + scope` pairs in work-order validation
   while preserving unique provider IDs.
2. Add the same-model duplicate advisory in `bakeoff validate`; keep the
   existing judge-family advisory behavior.
3. Update `draft-build --provider` parsing for repeated backends.
4. Update `/bakeoff:run` skill drafting rules and preview text.
5. Add research prompt/artifact tests for duplicate providers.
6. Add build worktree/artifact tests for duplicate providers.
7. Anonymize build judge duplicate candidate payloads, including top-level and
   nested provider IDs.
8. Add provider failure isolation coverage for rate-limit-like duplicate
   failures.
9. Update README and `docs/work-orders.md` with a short explicit-provider
   example and caveat.
10. Dogfood with the experiment matrix before considering any broader feature.
11. Defer analyze tie/exit-code behavior until dogfood proves it is worth the
    contract change.

## Recommended Cut Line

The smallest valuable release is:

- validation permits exact duplicate providers with unique IDs;
- natural-language drafting supports explicit Claude + Claude and Codex + Codex;
- duplicate previews and `bakeoff validate` warn clearly;
- build and research tests prove separate artifacts/worktrees;
- build judge payloads are anonymized for duplicate candidates where judge
  evidence is needed;
- provider failure isolation is covered for one duplicate attempt failing;
- swapped judging remains in place;
- no work-order schema version or default changes.

Analyze tie cleanup is below the cut line. If duplicate analyze runs later show
unresolved swap disagreements are common enough to matter, implement the
deferred decision and exit-code change as a separate, explicit behavior change.
