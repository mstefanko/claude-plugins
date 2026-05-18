# Competitive Builds Plan — Implementation-Readiness Audit

Date: 2026-05-18
Plan reviewed: `docs/competitive-builds-implementation-plan-2026-05-18.md`
Codebase: `bakeoff/` (Go module `github.com/mstefanko/claude-plugins/bakeoff`)

## Verdict: NEEDS-WORK

The plan is conceptually strong, research-grounded, and correctly identifies the architectural seams (worktrees + verifiers + position-swapped judge). The boundaries (no DAG, no apply, no test agent) are well-defended. However, several execution-critical specifics are missing or under-specified — a writer would have to invent them, and two engineers would invent different things.

Note on codebase fit: the plan correctly targets the Go `bakeoff/` subproject (`internal/...`, `cmd/bakeoff`). The marketplace `CLAUDE.md` describes `swarm-do/` Python, but this plan is for the sibling Go project — that is intentional and correct. References to `internal/commands/researchcmd/run.go`, `internal/decision/decision.go`, `internal/runner/runner.go`, `internal/workorder/workorder.go`, and `internal/manifest/manifest.go` all resolve to real files.

## Must-Fix Gaps

1. **Verifier runner package location and interface are unspecified.** Plan §"Phase 3" (lines 1064–1076) says "Reuse runner lifecycle concepts" but does not name a package, struct, or function signature. The existing `internal/runner/runner.go` is tightly coupled to provider final-JSON extraction (`ExtractFinalJSON`, `FormatRetry`). The plan needs to declare: new package `internal/verifyrun/` (or reuse `internal/verify/` — currently used for manifest verification, name collision risk), exported `Run(ctx, spec VerifierSpec, cwd string) Result` signature, and how it shares timeout/heartbeat code with `runner.Run` without dragging in final-JSON parsing.

2. **`internal/verify` name collision.** `internal/verify/verify.go` already exists for manifest-fingerprint verification ("runs verify"). The plan introduces "verifier" as a build-mode concept and references `runs verify` separately. The writer needs explicit naming guidance: rename one, namespace the new one (e.g., `internal/buildverify/`), or accept the overload. Resolve in the plan.

3. **`scope:web` rejection mechanics are vague.** Plan §"Provider Permissions" (lines 905–908) says `scope: web` "should be rejected in v1" but does not say where: workorder validation (`workorder.go:230`), scope policy (`internal/scope/scope.go:63`), or buildcmd preflight. Since other modes accept `web`, this is a build-only validation rule and must be added explicitly to `BuildSpec` validation with a test case.

4. **Codex writable-sandbox flag is unverified.** Plan §"Provider Permissions" (line 906) says Codex needs "writable sandbox mode when the CLI supports it." Existing scope code (`internal/scope/scope.go:87-89`) only emits `--sandbox read-only`. The writer needs: the actual writable flag value (likely `--sandbox workspace-write` per recent Codex CLI, but UNVERIFIED), capability detection key (e.g., `supports["sandbox_writable"]`), and fallback behavior when unavailable. Without this the writer will guess.

5. **`decision.ResolveBuild` signature and base-doc shape unspecified.** Plan §"Build Judge" (line 806) says "mirror `ResolveCompare`" but the build pipeline carries far more state (gate results per provider, metric results, baseline status, patch status enum). Existing `ResolveCompare(base, judgeResults, pass1Order, pass2Order)` (decision.go:82) has no slot for verifier or metric inputs. Plan must declare the `base` doc fields that ResolveBuild consumes (decision_kind, selection_basis, per-provider gate/metric/status maps) and the function signature.

6. **CoreFingerprintArtifacts extension is undefined.** Plan §"Manifest And Verify" (lines 881–889) lists build artifact categories but does not enumerate fingerprint paths. `manifest.CoreFingerprintArtifacts` (manifest.go:18) is a flat string list — variable per-provider/per-verifier paths require either a glob expansion strategy or explicit enumeration after run completion. Writer needs guidance: do we fingerprint `providers/<id>/build/diff.patch`, `baseline/verify/<id>/status.json`, etc., by enumerating after the run, or by extending the static list with a wildcard convention? Currently `runs verify` would silently skip them.

7. **Metric verifier JSON contract is under-specified.** Plan §"Test, Benchmark, And Verifier Strategy" (lines 482–485) says the metric command must "emit a JSON object on stdout with a finite numeric top-level property matching `metric.name`." But: where in stdout (last line? whole stdout? marker block like `<final_json>`)? What if multiple JSON objects? What about extra non-JSON output? Without a parser spec the writer will invent one and break dogfood. Recommend: last non-empty stdout line must be a JSON object; the verifier prompt template (none exists — providers write benchmarks freely) must communicate this rule. Currently nothing enforces it before runtime.

8. **Concurrency safety of parallel `bakeoff build` runs is asserted, not proven.** Plan (line 332) claims "Parallel `bakeoff build` invocations in the same repository are safe because all worktree and artifact paths are scoped by run id." This ignores `git worktree add`'s repository-wide lock (`.git/worktrees/`) and the "clean source checkout" precondition (lines 357–366) which is global state. Two simultaneous runs racing on a dirty-check are not safe. Add: explicit mutex strategy (advisory file lock under `.git/`?) or a documented "do not run concurrently in same repo" limitation.

9. **`build-context.json` schema version and manifest registration missing.** Plan describes the content (lines 845–860) but not the JSON schema version field, location of the writer function, or whether `runs verify` checks it. Add to required-artifact list explicitly and define schema_version handling.

10. **Patch capture binary-file behavior unspecified.** Plan (line 382) uses `git diff --cached --binary`. Behavior for: very large binary blobs vs `patch_max_bytes`, symlinks, executable-bit-only changes, file-mode-only changes, and submodule add attempts are all undefined. At minimum, write the test matrix expected. Earlier apply-command wording is superseded by the current contract: reports hand off patch artifacts and intentionally do not print apply commands.

## Open Questions (decide before writers start)

- **Judge gating after `both_failed_verification` (rule 4, line 733):** "judge skipped by default" — does "by default" imply a flag? If no flag exists in v1, drop the qualifier.
- **`allow_judge_only` + verifier present:** if `allow_judge_only: true` AND verifier is configured AND both pass gates AND metrics inconclusive, do we still call it `selection_basis: judge`, or `judge_only`? Plan uses both terms.
- **What counts as `provider_authored_tests`?** "Files matching project test patterns" (line 497) is vague; need a concrete heuristic (e.g., path contains `_test.`, `/tests/`, `/spec/`, or matches a per-language list).
- **Run-id collision with existing `runs/<id>/`:** plan says "existing `--force` semantics" (line 334). Confirm `--force` for build wipes worktrees/ subtree as well — easy to forget.
- **Heartbeat output for verifiers:** the runner emits per-tick `OnTick` callbacks. Build mode runs verifiers per-provider in parallel — interleaved heartbeats need a label scheme.
- **Where does `bakeoff init build` template live and what is its filename?** Plan implies `internal/workorder/templates/build.work-order.json` (line 1041); confirm `initKinds` membership (`workorder.go:26`) and template-loading path.
- **Schema version bump?** Plan says "extend schema version 1 conservatively" (line 552). A new required `build` object on `type: build` is additive; confirm no bump needed, document the rule.

## Bloat Candidates

- **`advisory` verifier kind** (line 156, 486): adds a third enum value, validation paths, and report wiring for evidence the judge can already see via raw logs. Defer — start with `gate` and `metric` only; add `advisory` when a real use case appears.
- **`benchmarks_or_probes_added` provider final-JSON field** (lines 634–640): structured data for a thing v1 explicitly will not auto-run as decisive evidence. The judge prompt could read raw diff. Either drop the structured field or use it — currently it's data plumbing without a consumer beyond report rendering.
- **`--keep-worktrees` report enrichment with `git worktree remove` commands** (line 947, line 1146): nice-to-have, but it expands report schema and adds a test. Could be a follow-up.
- **`build.patch_max_bytes` as a per-workorder override** (line 621): a single global default (500 KB, max 5 MB) is fine for v1. Per-workorder configurability adds validation surface for marginal value.
- **`build.allow_judge_only`** (line 612): combined with the v1 "verifier is required unless explicitly opted out" stance, this is one flag exposing a configuration that mostly defeats the point of build mode. Consider: ship without it; if a user needs judge-only, they can use `compare`/`analyze` mode against patches written by hand.
- **`selection_basis` enum has six values** ("gate, metric, judge, judge_only, single_provider_only, failed"). `judge` vs `judge_only` and `failed` (vs decision_kind `both_failed`) are partially redundant with `decision_kind`. Collapse.

## Internal Consistency Findings

- **Judge prompt fixture naming:** plan adds `judge-build.txt` (line 1043) but existing fixtures use `judge-compare.txt`, `judge-analyze.txt`, `judge-gather.txt`. Naming is consistent. `worker-build-claude.txt` and `worker-build-codex.txt` (lines 1043–1044) also follow the convention. Good.
- **Provider status enum vs decision_kind:** plan introduces `gate_passed`, `gate_failed`, `verify_unavailable`, `metric_decisive`, `metric_inconclusive` as "provider completion categories" (lines 717–722) alongside `no_patch`, `patch_captured`, `patch_over_cap`, `provider_failed`. These are mixed-domain (patch state vs verifier state). They should be two orthogonal fields per provider (`patch_state` and `verify_state`), not one flat enum. Otherwise decision logic becomes a nested switch.
- **Exit codes:** existing `apperror.JudgeDisagreementError` returns 3 (research mode). Plan reuses exit 3 for build tie (line 743) and exit 1 for `both_failed`/`both_failed_verification`. Good — consistent.
- **`runs verify` parity:** plan says (line 1093) "Extend `ls`, `show`, and `runs verify` as needed" — but the existing `manifest.CoreFingerprintArtifacts` and `manifest.RequiredArtifacts` (manifest.go:18, manifest.go:32) are static. Build mode needs a different artifact set per-run (different verifier ids). The plan does not address this asymmetry. See Gap #6.
- **`compare`/`analyze` work orders include `scope_policy` and per-provider `scope`; build does too** (line 564), but build forbids `scope: web` (line 908). Validation for this conflict must live in workorder validation, not buildcmd; otherwise `bakeoff validate` won't catch it.
- **`build-context.json` vs `workspace.json` split** is well-motivated and consistent (lines 845–878). One nit: `workspace.json` includes `provider backend/model/effort` (line 875) — these are already in `work-order.json`. Duplication is OK if explicitly framed as snapshot-at-execution.

## Recommended Next Steps Before Writers Start

1. Resolve Gaps #1, #2, #3, #5 (package/file/signature decisions). These block Phase 2–4.
2. Verify Codex writable-sandbox flag against the actual CLI version pinned by bakeoff (Gap #4).
3. Reduce decision/status enum surface (Internal Consistency #2 + Bloat #6).
4. Pick: keep `advisory` kind, or defer.
5. Decide manifest fingerprint extension strategy (Gap #6) — this is the most invasive open question.
