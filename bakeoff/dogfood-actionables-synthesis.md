# Dogfood Actionables Synthesis

Sources synthesized:

- `dogfood-metric-lint.actionable-items.md`
- `dogfood-ls-manifest-perf-actionables.md`
- `dogfood-artifacts-telemetry-split.report-actionables.md`
- `runs/dogfood-manifest-telemetry-lenses.actionable-findings-report.md`
- `runs/2026-05-24-4f7d/dogfood-actionable-items.md`

Validation date: 2026-05-25. Current working tree was inspected directly, then these package tests were run and passed:

- `go test ./internal/manifest ./internal/commands/lscmd ./internal/commands/researchcmd ./internal/commands/escalatecmd -count=1`
- `go test ./internal/provider ./internal/workorder ./internal/commands/doctorcmd ./internal/commands/validatecmd -count=1`

Confidence labels:

- **Multi-source**: found in more than one input report, or independently converged by multiple providers plus escalation.
- **Validated**: found once, then confirmed against the current code.
- **Closed**: current code already handles it, or the claim was refuted by source inspection.

Risk labels:

- **Higher risk**: wire-contract change, output/UI change, possible behavior regression, or needs product/schema decision before implementation.
- **Normal risk**: straightforward bug fix or test/doc update with contained blast radius.

---

## Reviewer Verdict (added 2026-05-25)

I walked the synthesis row by row against the working tree. **Every claim under "Fix Now" is reproducible in the current code.** No false positives. Three observations worth flagging up front:

1. **F8, F9, F10 are all wire-contract changes hiding inside the "Fix Now" table.** They are correct fixes, but they are not "bug fixes" — they change what consumers see in `manifest.json` / `bakeoff ls --json`. Bumping `telemetry.schema_version` from 1 → 2 should be part of the same PR, and the run skill / `bakeoff inspect` formatting should be re-tested with both old and new manifests.
2. **F6 and D3 are entangled.** F6 adds `winner_backend` / `winner_family` to telemetry. D3 is the route-type-vs-artifact-type precedence question. Both touch the same `telemetrySummary` block and the same "what is authoritative?" question. Decide D3 first, then land F6 — otherwise F6 has to be re-touched.
3. **The "Suggested Order" at the bottom is right.** Replay correctness first (F2-F5) is the highest-value batch — those are the only items where the current code can corrupt a run ledger. Everything else is observability / cleanup.

I'd also collapse F11 into the F2-F5 batch — it is a five-line guard with no behavioral surface area and lives in the same package as F10.

Per-item detail follows.

---

## Fix Now

### F1 — `highestSeverity` counts false positives as actionable severity

| | |
|---|---|
| Confidence | Validated |
| Risk | **Higher risk** (manifest telemetry behavior changes) |

**Where the bug lives.** `internal/manifest/manifest.go:834-853`:

```go
func highestSeverity(items []any) any {
    if len(items) == 0 { return nil }
    seen := map[string]bool{}
    for _, item := range items {
        obj, ok := item.(map[string]any)
        if !ok { continue }
        severity, _ := obj["severity"].(string)
        seen[severity] = true                       // every classification counted
    }
    for _, severity := range []string{"high", "medium", "low", "none"} {
        if seen[severity] { return severity }
    }
    return nil
}
```

The function records the severity of every item — `real_issue`, `false_positive`, `needs_repro`, `wont_fix`. The triage telemetry exposes this as `triage.highest_severity`, so a high-severity false positive raises the run's apparent severity even though triage already marked it not actionable.

**Test that demonstrates the bug.** `internal/manifest/manifest_test.go:390-403`:

```go
items: []any{
    map[string]any{"classification": "real_issue",     "severity": "medium"},
    map[string]any{"classification": "false_positive", "severity": "high"},
},
// ...
wantHighestSeverity: "high",
```

The test currently asserts `"high"` even though the only real_issue is medium.

**Implementation.**

- Filter on classification before recording severity. Default actionable set: `{"real_issue"}`. Add `needs_repro` only if we explicitly want pending verifications to roll up.
- Update `internal/manifest/manifest_test.go:390-403` so the same fixture produces `"medium"`.
- Add a regression case where two false positives at `high` + one real_issue at `low` yields `"low"`.
- Pairs with **F9** — once the field can legitimately be `nil` for "no actionable findings", we need it to always be emitted as a nullable key (currently the key disappears).

**My take: fix now, but bundle with F9 in the same PR.** The change is small, the test fixture is the only existing pinner, and the two changes together create a coherent contract: `triage.highest_severity` is always present and reflects only actionable items. Recommend defaulting to `real_issue` only for the first cut and filing a separate ticket for "should `needs_repro` count?" — that question has product/UX implications, not just code.

---

### F2 — Judge-only rerun updates `latest` before replay copies complete

| | |
|---|---|
| Confidence | Multi-source |
| Risk | Normal risk (user-visible ledger pointer) |

**Where the bug lives.** `internal/commands/researchcmd/run.go:232-244`:

```go
if err := os.MkdirAll(runDir, 0o700); err != nil { ... }
if err := ledger.UpdateLatest(opts.Out, runID); err != nil { ... }   // line 235
if err := copyRequiredRunFile(opts.SourceRunDir, runDir, "work-order.json"); err != nil { ... }
if err := copyReplayContextArtifacts(opts.SourceRunDir, runDir); err != nil { ... }
if err := copyProviderArtifactDirs(wo, opts.SourceRunDir, runDir); err != nil { ... }
```

`latest` is updated to point at a directory that contains only `mkdir`'d emptiness. If any of the three copy steps fails, `latest` points at a half-populated run while the previous run is no longer reachable via `latest`.

**Implementation.**

- Move `ledger.UpdateLatest(opts.Out, runID)` after the three copy calls succeed (before `runJudgePhase`).
- Add a test that forces `copyReplayContextArtifacts` to fail (chmod source `review-context.json` unreadable, or short-circuit via test-only seam). Assert `latest` still points at the prior run.
- Note: leaving the partial run dir on disk is fine — operators can inspect/delete it. The only requirement is `latest` doesn't move.

**My take: fix now.** Trivial change, real correctness win, and the test gap is the main reason it survived. Should be in the same PR as F4/F5.

---

### F3 — Review-context artifact names are hardcoded in multiple places despite a shared constant

| | |
|---|---|
| Confidence | Multi-source |
| Risk | Normal risk |

**Where the bug lives.** Constant exists at `internal/manifest/manifest.go:45`:

```go
var ReviewContextArtifacts = []string{"source-work-order.json", "review-context.md", "review-context.json"}
```

But both call sites redeclare it:

- `internal/commands/researchcmd/run.go:1010` — `names := []string{"source-work-order.json", "review-context.md", "review-context.json"}`
- `internal/commands/escalatecmd/escalate.go:1061` — identical literal

**Implementation.**

- Import `manifest` (already imported by `researchcmd`; `escalatecmd` already imports it too) and replace both `names := []string{...}` with `names := manifest.ReviewContextArtifacts`.
- No test changes required — the order in `manifest.ReviewContextArtifacts` is the same.

**My take: fix now.** Trivial. The risk of these drifting from each other is real — `review-context.json` was added later than the other two and only happened to land in all three places. Land this as part of any F2/F4/F5 PR.

---

### F4 — Replay copy writes directly and can leave partial target files

| | |
|---|---|
| Confidence | Multi-source |
| Risk | Normal risk (if implemented with a binary-safe helper) |

**Where the bug lives.** `internal/commands/researchcmd/run.go:942-957`:

```go
func copyFile(source string, target string) error {
    info, err := os.Stat(source)
    if err != nil { return err }
    if info.IsDir() { return fmt.Errorf("%s is a directory", source) }
    data, err := os.ReadFile(source)
    if err != nil { return err }
    if err := os.MkdirAll(filepath.Dir(target), 0o700); err != nil { return err }
    return os.WriteFile(target, data, 0o600)        // not atomic
}
```

A crash or out-of-space mid-`WriteFile` leaves a partial target file. Other ledger writes use `workorder.WriteJSONAtomic` / `WriteTextAtomic` (temp + rename) but those are JSON/text-specific. Replay handles binary content — patch files can include binary diffs — so the JSON-string round trip used by `copyReplayContextArtifacts` (line 1037, `WriteTextAtomic(..., string(data))`) is also wrong for the binary case, though all current review-context artifacts are text.

**Implementation.**

- Add a binary-safe helper in `internal/fsutil` — e.g. `WriteAtomic(target string, source io.Reader, mode os.FileMode) error` using temp file in same dir + `os.Rename`. (Or `WriteBytesAtomic(target, data, mode)`.)
- Route `researchcmd/run.go:copyFile` and `copyReplayContextArtifacts` (line 1037) through it.
- Add a test using a mid-write fault injector (or assert no `.tmp` file is left and the target file has the full bytes).
- Mode `0o600` is correct.

**My take: fix now.** This is the kind of bug that only bites once, and the failure mode is silent corruption. The helper is ~20 lines.

---

### F5 — Provider artifact replay interleaves preflight and mutation

| | |
|---|---|
| Confidence | Multi-source |
| Risk | Normal risk |

**Where the bug lives.** `internal/commands/researchcmd/run.go:853-865`:

```go
func copyProviderArtifactDirs(wo *workorder.WorkOrder, sourceRunDir string, runDir string) error {
    for _, participant := range wo.Providers {
        source := filepath.Join(sourceRunDir, "providers", participant.ID)
        target := filepath.Join(runDir, "providers", participant.ID)
        if err := requireProviderReplayArtifacts(source, participant.ID); err != nil {
            return err
        }
        if err := copyDirectoryTree(source, target); err != nil {  // mutates before validating provider N+1
            return err
        }
    }
    return nil
}
```

If providers `[A, B, C]` are configured and B's `status.json` is missing, `A` will already be copied into `runDir` by the time `B`'s preflight fails. Combined with F2, `latest` may also already have moved.

**Implementation.**

- Split into two passes:
  ```go
  for _, p := range wo.Providers {
      if err := requireProviderReplayArtifacts(...); err != nil { return err }
  }
  for _, p := range wo.Providers {
      if err := copyDirectoryTree(...); err != nil { return err }
  }
  ```
- Add a test where provider K has valid artifacts and K+1 is missing `status.json`. Assert nothing was written under `runDir/providers/` and that the run dir is in pre-replay state.

**My take: fix now.** Pair with F2 and F4 — same PR, same correctness theme.

---

### F6 — Manifest telemetry omits decision metadata needed for judge-bias and selector analysis

| | |
|---|---|
| Confidence | Multi-source |
| Risk | Normal risk (additive schema fields) |

**Where the gap lives.** `decision.json` already carries:

- `selection_basis` (`internal/decision/decision.go:235, 279, 297, 303, 312, 345`)
- `canonical_winner` (`internal/decision/decision.go:42, 79, 135, ...`)
- `order_maps` (`internal/decision/decision.go:92, 116, 189, 331`)
- `judge_passes` (`internal/decision/decision.go:117, 190, 332`)

But `telemetrySummary` at `internal/manifest/manifest.go:358-364` only projects:

```go
"judge": map[string]any{
    "backend":         nilIfEmpty(judgeBackend),
    "family":          judgeFamily,
    "family_relation": provider.JudgeFamilyRelation(judgeBackend, providerBackends),
    "ran":             truthy(decision["judge_ran"]),
    "completed":       truthy(decision["judge_completed"]),
},
```

There is no way to slice telemetry by selection mechanism (gate vs metric vs judge), by winner backend/family, or by judge-bias signals like position-swap and pass disagreement.

**Implementation.**

- Add to `telemetry.judge`: `selection_basis`, `winner_backend`, `winner_family`, `order_maps`, `judge_passes`, `position_swap_used`.
- `winner_backend` derives from `decision["canonical_winner"]` (a provider ID) by looking up the resolved or work-order backend.
- `winner_family` uses `provider.FamilyForBackend(winner_backend)`; emit `"unknown"` on catalog miss for consistency with existing `family` semantics (but see F8 — null may be the better long-term move).
- `position_swap_used` derives from whether `order_maps.pass1` ≠ `order_maps.pass2`.
- Pure additive — existing consumers see new keys, no existing keys change shape, **provided D3 is resolved first**. If D3 lands later, the precedence of `runType` will shift and F6's tests will need to be re-pinned.
- Add tests covering: gate winner (no judge), metric winner, judge winner with same pass1/pass2, judge winner with swapped passes.

**My take: fix now, after D3.** The fields are valuable and the schema is open for additions. Bumping `telemetry.schema_version` to 2 in the same PR signals consumers can opt in. Don't bundle with F8/F9 — those are wire-changes; this one is additive.

---

### F7 — Judge-only rerun metadata is not queryable through telemetry or `ls`

| | |
|---|---|
| Confidence | Multi-source |
| Risk | Normal risk (mostly additive) |

**Where the gap lives.** `RunResearchJudgeOnly` writes the meta extras at `internal/commands/researchcmd/run.go:289-293`:

```go
MetaExtra: map[string]any{
    "source_run_id":  sourceRunID,
    "source_run_dir": opts.SourceRunDir,
    "rerun_mode":     "judge_only",
},
```

But:

- `telemetrySummary` (`manifest.go:344-371`) doesn't read meta at all for `route` — it reads `manifest`. Even if it did, `source_run_id` and `rerun_mode` aren't in the manifest unless it's an escalation (`addEscalationManifestFields` at line 320-332 is gated on `isEscalationRun`).
- `RowForLS` (`manifest.go:152-165`) only emits `source_run_id` when `loaded.Type == "escalation"`.

So a `bakeoff ls --json` row for a judge-only rerun gives no hint that it was a rerun.

**Implementation.**

- In `BuildRunManifest`, project `meta["source_run_id"]` and `meta["rerun_mode"]` into the top-level manifest (or into a new `rerun` sub-object — slightly cleaner schema-wise).
- In `telemetrySummary`, add `telemetry.source_run_id` and `telemetry.rerun_mode` at the top level (peer to `route`, `providers`, etc.) — they aren't really "route" attributes.
- In `RowForLS`, emit `source_run_id` for any run type that has it (drop the `loaded.Type == "escalation"` gate, or change the gate to `loaded.SourceRunID != ""`). Also project `rerun_mode` when set.
- Tests: add a fixture for a judge-only rerun manifest and assert `source_run_id` and `rerun_mode` appear in both the manifest and the ls row.

**My take: fix now.** Pure additive. Operators currently have no way to spot rerun rows in `bakeoff ls`. The escalation gate in `RowForLS` is a vestige of when escalations were the only rerun type.

---

### F8 — `telemetry.judge.family` can be `"unknown"` while `telemetry.judge.backend` is null

| | |
|---|---|
| Confidence | Multi-source |
| Risk | **Higher risk** (wire contract change) |

**Where the inconsistency lives.** `internal/manifest/manifest.go:339-360`:

```go
judgeBackend := telemetryJudgeBackend(workOrder, meta)
judgeFamily := provider.ProviderFamilyUnknown        // initialized even when judgeBackend == ""
if judgeBackend != "" {
    judgeFamily = provider.FamilyForBackend(judgeBackend)
}
// ...
"judge": map[string]any{
    "backend":         nilIfEmpty(judgeBackend),   // null when empty
    "family":          judgeFamily,                // never null — "unknown" sentinel
    ...
},
```

For a run with no judge, the manifest emits `{"backend": null, "family": "unknown", "family_relation": ...}`. Consumers can't tell whether `family: "unknown"` means "no judge" or "judge backend not in catalog".

**Implementation.**

- When `judgeBackend == ""`, emit `family: nil` (and `family_relation: nil`).
- Keep `"unknown"` semantics only for the "judge exists but catalog miss" case.
- **Bump `telemetry.schema_version` from 1 → 2.**
- Do NOT add tests that pin the current `"unknown"` behavior for absent judges — the test in `manifest_test.go:269-270` ("unknown judge" case) already exists for the catalog-miss case and remains valid because it sets `judge: "mystery"` (non-empty backend).
- Add a new test case: no judge configured at all → both `judge.backend` and `judge.family` are nil.

**My take: fix now, paired with F9 and the schema bump.** This is the right contract. The risk is that downstream consumers (run skill, `bakeoff inspect`) may assume `family` is always a string. Audit those callers as part of the PR. Bumping schema_version is the safety valve.

---

### F9 — `telemetry.triage.highest_severity` is omitted instead of explicit null

| | |
|---|---|
| Confidence | Validated |
| Risk | **Higher risk** (wire contract change) |

**Where the inconsistency lives.** `internal/manifest/manifest.go:505-511`:

```go
func telemetryTriageSummary(triageSummary map[string]any) map[string]any {
    return compactNilMap(map[string]any{
        "state":            triageSummary["state"],
        "item_count":       triageSummary["item_count"],
        "highest_severity": triageSummary["highest_severity"],
    })
}
```

`compactNilMap` drops nil values, so a triage with no items disappears the `highest_severity` key entirely. After F1 lands, this becomes worse — a triage with only false positives also produces nil, and consumers can't distinguish "no actionable findings" from "field missing".

**Implementation.**

- Replace `compactNilMap` with a builder that keeps `highest_severity` (and probably `item_count`) as nullable keys even when nil.
- Keep `state` always present (it's always non-nil in practice).
- Bump `telemetry.schema_version` to 2 (same bump as F8).
- Add tests: triage with no items, triage with only false positives (after F1), triage with mixed → assert key is always present.

**My take: fix now, in the same PR as F1 and F8.** All three are the same contract decision: "telemetry keys are always present; nullability is meaningful." Bundling them avoids a confusing two-step schema transition.

---

### F10 — `lsManifest.Triage` drops new triage summary fields

| | |
|---|---|
| Confidence | Validated |
| Risk | **Higher risk** (`ls --json` output/schema change) |

**Where the gap lives.** `internal/manifest/manifest.go:181-184`:

```go
Triage struct {
    State string `json:"state"`
} `json:"triage"`
```

Only `state` is unmarshaled. `RowForLS` at `manifest.go:137-146` only projects `triage_state` from `loaded.Triage.State`. New triage fields (`item_count`, `highest_severity`, `item_counts_by_classification`) are in the manifest but not in `ls --json`.

**Implementation.**

- Extend `lsManifest.Triage` to include `ItemCount *int`, `HighestSeverity *string` (pointer so we can distinguish absent from zero/empty).
- In `RowForLS`, add to the row map (under a nested `"triage"` key, not new top-level columns):
  ```go
  triage := map[string]any{"state": state}
  if loaded.Triage.ItemCount != nil    { triage["item_count"] = *loaded.Triage.ItemCount }
  if loaded.Triage.HighestSeverity != nil { triage["highest_severity"] = *loaded.Triage.HighestSeverity }
  row["triage"] = triage
  ```
  And keep the existing flat `triage_state` for backward compatibility (or document its removal in CHANGELOG).
- **Do not** add `triage.item_count` or `triage.highest_severity` as default human columns in `bakeoff ls`. Either JSON-only, or behind `--verbose`.
- Tests: golden ls rows for a run with non-zero items, a run with zero items (post-F1), a missing/legacy manifest.

**My take: fix now, but JSON-first.** Human `ls` columns drift slowly because operators rely on them. JSON consumers are downstream of `--json` and should expect additive growth. The risk is mostly about default human output, so just don't change it.

---

### F11 — `triageStateForLS` and `legacyLSRow` do avoidable triage I/O

| | |
|---|---|
| Confidence | Validated |
| Risk | Normal risk (for the guard-only fix) |

**Where the cost lives.**

`triageStateForLS` (`manifest.go:201-216`):

```go
func triageStateForLS(runDir string, manifestState string) string {
    if manifestState == "" { manifestState = "no" }
    if manifestState == "no" {
        info, err := os.Stat(filepath.Join(runDir, "triage"))
        if err != nil || !info.IsDir() { return manifestState }
    }
    state, _ := triage.StateDetail(runDir)    // called even when manifestState != "no", regardless of triage/ presence
    if state != "" { return state }
    return manifestState
}
```

When `manifestState == "yes"` and `triage/` exists, the function calls `triage.StateDetail`, which re-reads `triage/status.json` + `triage/final.json` + recomputes input hashes — even though the manifest is already trustworthy. The intent is to catch staleness, but staleness only matters if `triage/` exists.

`legacyLSRow` (`manifest.go:786`) unconditionally calls `triage.StateDetail` even when there's no triage dir.

**Implementation.**

- In `triageStateForLS`, add an `os.Stat(triageDir)` guard at the top:
  ```go
  if _, err := os.Stat(filepath.Join(runDir, "triage")); err != nil { return manifestState }
  ```
  Then the existing logic only runs for runs with triage. This preserves disk-as-source-of-truth semantics — if the dir is gone, manifest is the only source we have.
- In `legacyLSRow`, same guard before `state, _ := triage.StateDetail(runDir)`.
- Tests: fast `ls` benchmark over a 100-run dir with no triage. Should drop from N×hash-compute to N×stat.

**My take: fix now.** Five-line change, pure perf, no behavior change. Bundle with the F2-F5 replay PR or the F8-F10 telemetry PR — either works.

---

### F12 — `TestWorkOrderTypeControlsBuildDiagnosticsEvenWhenMetaTypeDrifts` is non-discriminating

| | |
|---|---|
| Confidence | Validated |
| Risk | Normal risk (test-only) |

**Where the bug lives.** `internal/manifest/manifest_test.go:536-547`:

```go
{
    name: "work order type controls build diagnostics even when meta type drifts",
    setup: func(t *testing.T, runDir string) {
        writeJSON(t, filepath.Join(runDir, "meta.json"), map[string]any{"run_id": "build1", "type": "gather", ...})
        writeJSON(t, filepath.Join(runDir, "diagnostics.json"), map[string]any{
            "output_truncation": []any{ ... 2 entries ... },
        })
    },
    want: 2,
},
```

The outer fixture (`manifest_test.go:554-561`) sets `provider_statuses.claude` with both `stdout_truncated: true` and `stderr_truncated: true` → the fallback path produces 2.

The diagnostics has 2 entries → the build path also produces 2.

The test passes regardless of which branch is taken. The named invariant ("work order type controls") is not actually tested.

**Implementation.**

- Change the diagnostics fixture to 3 entries (or 1). Different from the fallback count.
- Or change `provider_statuses` so it would produce 1 entry (only `stdout_truncated`).
- Assert the test fails when `outputTruncationCount` is changed to use meta type instead of work-order type.

**My take: fix now.** Test-only. Should be in the same PR as F6 since both touch `telemetrySummary` test invariants.

---

### F13 — Manifest telemetry docs are missing/incomplete

| | |
|---|---|
| Confidence | Multi-source |
| Risk | Normal risk (docs-only) |

**Where the gap lives.**

- `docs/artifacts-and-ledger.md:18` — `manifest.json` is described as "Manifest with artifact paths and SHA-256 fingerprints." No mention of telemetry.
- `docs/cli-reference.md` — no manifest telemetry field reference (verified: only mention of `manifest.json` is at line 318, in escalation context).

**Implementation.**

- Add a "Manifest telemetry" section to `docs/cli-reference.md` covering: `schema_version`, `route`, `providers`, `judge`, `artifacts`, `triage`, nullability conventions, the backends-vs-families contract (after D1 lands), and how `family_diversity` relates to `families`.
- Update `docs/artifacts-and-ledger.md:18` row to mention the telemetry section.
- Link from `README.md` (the existing manifest mention in the artifact list).

**My take: fix now, but after F1/F6/F8/F9 land.** Writing the doc before the contracts settle just creates churn. Block this on the schema-changes PR.

---

### F14 — Docs disagree with emitted "judge family advisory" wording

| | |
|---|---|
| Confidence | Validated |
| Risk | Normal risk (docs-only) |

**Where the inconsistency lives.**

- Emitted: `internal/commands/validatecmd/validate.go:256` — `"judge family advisory: judge "` (non-hyphenated)
- Emitted: `internal/commands/doctorcmd/doctor.go:223` — `"judge family advisory: %s\n"` (non-hyphenated)
- Docs: `README.md:94` — `"compact judge-family advisory"` (hyphenated)
- Docs: `README.md:311` — `"a judge-family advisory for the default generated judge"` (hyphenated)
- Docs: `docs/cli-reference.md:492` — `"prints a `judge family advisory` line"` (non-hyphenated — already correct)

**Implementation.**

- Two `README.md` edits: line 94 and line 311, replace `judge-family advisory` with `judge family advisory`.
- No code changes — the emitted form is correct and grepping for log lines is a real operator pattern.

**My take: fix now.** Two characters. Should be in the same PR as F13.

---

## Higher Risk Or Needs Decision

### D1 — `telemetry.providers.backends`, `families`, and `count` need a clear contract

| | |
|---|---|
| Confidence | Multi-source |

**The tension.** Two reports disagree on the contract:

- Report A: "dedupe + sort `backends`, count unique." Reasoning: `backends` is metadata about *what families are involved*.
- Report B: "preserve order and duplicates; document `families` as a set." Reasoning: `backends` represents the *participants in this run*, useful for spotting config bugs like the same backend listed twice.

Current code (`manifest.go:373-409`) preserves work-order order *and duplicates*. Existing test (`manifest_test.go:269-271`) intentionally pins the duplicate case:

```go
{name: "duplicate provider backend", ..., providers: []string{"claude", "claude"}, ..., backends: []string{"claude", "claude"}, count: 2},
```

**My recommendation.** Preserve order and duplicates. Document `families` as a set (already de facto — it's built from a `map[string]bool`). Independently, exclude the `"unknown"` sentinel from the `families` list (`manifest.go:436-457`) and keep `family_diversity: "unknown"` as the signal that an unknown backend exists. Reasoning:

1. `backends` is a faithful record of run configuration. Duplicates are diagnostic, not noise.
2. `count` already mirrors `len(backends)`; if we dedupe, operators lose the participant count.
3. `families` is genuinely set-like and dedup is the right behavior there.
4. The `"unknown"` sentinel in `families` is confusing — `family_diversity` already carries that signal.

**Implementation (after decision).**

- Code change in `telemetryProviderFamilies` (`manifest.go:436-457`): drop the unknown family from the returned slice; keep the `unknown` diversity flag.
- Update test `manifest_test.go:265-272`:
  - `"unknown provider"` case: `families: []string{}` (was `[ProviderFamilyUnknown]`), `diversity: "unknown"` (unchanged).
- Document the contract in the new telemetry section (F13).

**My take: defer until decision, then a tight PR.** This is one of those decisions where shipping the wrong contract now is worse than waiting a day. Block F6/F13 on this — once decided, all three move together.

---

### D2 — Lazy `ls` triage refresh after filter/limit

| | |
|---|---|
| Confidence | Validated |

**The risk.** `internal/commands/lscmd/ls.go:278-307` calls `manifest.RowForLS` for every run before filtering. `RowForLS` calls `triageStateForLS`, which calls `triage.StateDetail` for runs with a `triage/` dir — recomputing input hashes per call. For a 1000-run output dir, this is the bulk of `ls` wall time.

Deferring the triage call until after `--triage-state` and `--limit` are applied would be a big win, but:

1. `--triage-state` filtering needs the resolved state, so you can only defer for the *non-filter* path.
2. Staleness detection becomes weaker — a stale-triage row sorted out by `--limit` will never have its staleness recomputed.

**My take: defer until F11 lands.** F11 already collapses the unnecessary I/O for the no-triage case, which is probably 80% of the win. After F11, profile the remaining cost and decide whether lazy refresh is worth the correctness complexity.

**Before doing the lazy refresh:** Add golden `ls`/history tests for present, missing, invalid, escalation, and stale-triage manifests. Otherwise this is a stealthy-regression risk.

---

### D3 — `telemetry.route.type` and artifact route type can diverge

| | |
|---|---|
| Confidence | Validated |

**Where the divergence lives.** `internal/manifest/manifest.go:335-336`:

```go
runType := jsonutil.StringValue(manifest["type"])              // used for telemetry.route.type
artifactRunType := runTypeFromWorkOrder(workOrder)             // used for outputTruncationCount
```

`manifest["type"]` is set at line 86 as `FirstNonNil(meta["type"], workOrder["type"])`, then potentially overridden to `"escalation"` at line 321. `runTypeFromWorkOrder` only reads work-order. If meta drifts (which the existing F12 test demonstrates is possible), `route.type` and `artifacts.*` disagree about what kind of run this is.

**My recommendation.** Collapse to one resolved value, work-order-controlled. Work-order is what the operator configured; meta is post-hoc state that can drift. The F12 test name ("work order type controls...") already implies this is the intended semantics.

**Implementation (after decision).**

- Change `telemetrySummary` to use `artifactRunType` for both `route.type` and artifact counts. Note: this loses the escalation override at line 321 (which forces `out["type"] = "escalation"`) — keep that override but apply it through a single `resolveRunType` helper.
- Add an explicit precedence test: meta type ≠ work-order type ≠ "escalation" → route.type follows work-order.

**My take: defer to a focused PR, but do it before F6.** F6 adds more telemetry that depends on the run-type contract. Settling D3 first means F6 doesn't need to be re-touched.

---

### D4 — `facet_id` telemetry privacy/product contract

| | |
|---|---|
| Confidence | Validated |

**The constraint.** `internal/workorder/workorder.go:459-468` validates facet.id as a slug matching `^[A-Za-z0-9][A-Za-z0-9._-]*$`, must not duplicate a provider id, and not match reserved names. So `facet_id` is bounded — it can't carry arbitrary text.

**The question.** Is "stable non-sensitive slug" a strong enough guarantee, or do we need a closed enum for generated facets?

**My recommendation.** Keep `facet_id` with the documented "stable non-sensitive slug" contract. The existing slug regex already prevents injection of PII-like content. A closed enum would force a code change every time a new facet kind is added, which is the wrong tradeoff for what's essentially a telemetry tag.

**My take: defer, low priority.** This is a product decision that doesn't block any other work. File as a product ticket and move on.

---

### D5 — `readJSON` hides malformed optional JSON

| | |
|---|---|
| Confidence | Validated |

**Where the silence lives.** `internal/manifest/manifest.go:906-915`:

```go
func readJSON(path string) any {
    data, err := os.ReadFile(path)
    if err != nil { return nil }
    var value any
    if err := json.Unmarshal(data, &value); err != nil { return nil }
    return value
}
```

Both read errors and JSON parse errors return nil. Callers can't tell "file absent" from "file corrupt." This is intentional for optional artifacts (status.json, final.json, review-context.json) but means corrupt optional files silently degrade the manifest.

**My take: defer.** Surfacing errors touches many callers (every `readJSON` call site) and changes manifest behavior for partially corrupt ledgers. Worth doing but bundling with telemetry fixes would obscure the blast radius. File as a standalone reliability ticket.

---

### D6 — `RowForLS` metric benchmark/harness

| | |
|---|---|
| Confidence | Validated |

`RowForLS` is simple and I/O-bound. No benchmark exists today. A metric verifier would be noisy on macOS (filesystem cache warmups, mtime resolution).

**My take: defer until a concrete perf complaint.** The current code is fast enough for hundreds of runs. Building a metric-verifier-protected benchmark is preemptive optimization.

---

### D7 — Metric-harness precheck in skill/doctor

| | |
|---|---|
| Confidence | Validated |

**My take: defer.** Skill copy is the right first move. A doctor probe only if this pattern recurs. UX, not correctness.

---

### D8 — Judge/rubric and runner hygiene from `dogfood-ls-manifest-perf`

| | |
|---|---|
| Confidence | Validated |

Three separate issues:

1. Decision rationale vs pass verdict tension.
2. `diff.patch` paths prefixed with `bakeoff/`.
3. Codex stderr retained at ~80 KB.

**My take: defer to separate harness tickets.** These are runner-level issues, not core code. They share no implementation surface with the F-items. File them with the harness team.

---

## Test And Benchmark Backlog

- Add replay edge-case tests for copy failure after run-dir creation, provider K copied/provider K+1 fails, symlink-inside-root vs symlink-outside-root, and partial review-context artifacts in judge-only rerun.
- Add `ls`/history golden tests across present, missing manifest, invalid manifest, escalation, stale triage, and manifest/disk divergence. Current lscmd tests partially cover disk divergence indirectly, but not as an explicit invariant.
- Add empty-provider and empty-judge telemetry tests after F8/D1 are decided; avoid pinning the current absent-judge `"unknown"` family behavior.
- Add benchmarks only after the semantics are pinned: `BenchmarkRunLsLargeDir` and `BenchmarkRowForLSWithTriageDir`.

## Closed Or Refuted

- `BackendSpec.Family` doc comment is already present at `internal/provider/provider.go:48`.
- The claimed fallback-provider drop in `telemetryProviderBackends` is refuted. `fallback` is derived from `workOrder["providers"]`, and the current loop covers work-order provider IDs before adding extra resolved IDs.
- The `(0, true) -> (0, false)` `buildDiagnosticsOutputTruncationCount` claim is not a behavior bug. With `omitempty`, missing and zero-record diagnostics are indistinguishable; falling back to provider statuses when the key is absent is the safe behavior.
- The resolved-models family-relation path is already covered by `TestWriteRunManifestTelemetryResolvedProviderBackendsKeepWorkOrderOrder` at `internal/manifest/manifest_test.go:295-344`.
- The partial review-context all-or-none helper is already tested in `internal/commands/researchcmd/run_test.go:49-66`; the remaining replay test gap is failure after mutation begins.
- `F011/F015` from the older slice-8 report are stale; the current code checks for a missing `output_truncation` key at `internal/manifest/manifest.go:494-502` and tests the fallback at `internal/manifest/manifest_test.go:528-534`.

## Suggested Order (revised)

1. **PR-1 — Replay correctness:** F2, F3, F4, F5, F11. One package boundary (`researchcmd` + `escalatecmd` + `manifest` ls guard). The only batch where current code can corrupt a ledger.
2. **PR-2 — Decide D1 and D3.** Document-only or a one-line code change per decision. Block PR-3 on this.
3. **PR-3 — Telemetry wire contract:** F1, F8, F9, F12. Bump `telemetry.schema_version` 1 → 2. All wire-changes land together.
4. **PR-4 — Telemetry additive:** F6, F7, F10. Pure additive (lsManifest gains optional fields). No schema bump needed beyond PR-3's.
5. **PR-5 — Docs:** F13, F14. After contracts settle.
6. Backlog: D2 (only after F11 perf is measured), D5 (standalone reliability ticket), D4/D6/D7/D8 (defer).
