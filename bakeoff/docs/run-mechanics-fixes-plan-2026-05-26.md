# Run-Mechanics Fixes Plan (2026-05-26)

Investigation and remediation plan for issues exposed by the
`docs-cli-consistency-audit` Bakeoff run on 2026-05-26. Scope is the **run
mechanics** — validation errors, advisory warnings, provider lifecycle — that
fired during the run. The 24 audit findings about README/commands docs vs
the Go CLI are tracked separately and out of scope for this plan.

## Run identification

| field | value |
|---|---|
| run id | `2026-05-26-f96d` |
| work order | `docs-cli-consistency-audit.work-order.json` (repo root) |
| mode | `gather` · facet `code-review` |
| providers | `claude-sonnet` ok 602.473s · `codex-gpt5` ok 280.459s |
| judge | `claude/opus` ok 118.276s |
| decision | `structured_union` (merged) |
| triage | complete · 24 items · 1 `fix_now` · 23 `document`/`defer`/`reproduce`/`ignore` |
| report | `runs/2026-05-26-f96d/report.md` |
| triage | `runs/2026-05-26-f96d/triage/triage.md` |
| HEAD at run time | `08c10a4 tweaking` (recent chain: `86e1f94 Tightening`, `afc0c7c narrow third-party judge advisory`) |

## What we investigated

The run completed cleanly (exit 0), but five run-mechanics events fired during
it. We traced each to source and assessed whether it was a real defect, a
documentation drift, or working-as-designed.

1. Drafting validation failure (`exit 2: facet.include must be an array of strings`).
2. Advisory warnings about `background` referencing `commands/rerun.md` and
   `commands/verify.md` not existing under `<context-root>`.
3. Advisory `judge family advisory: same_as_some` warning.
4. `codex-gpt5` emitting ~351 KB of stderr (truncated to 60 KB on disk),
   classified `diagnostic` and exiting `ok`.
5. `claude-sonnet` running 600+ seconds with no stdout, surfacing the CLI's
   long-quiet hint.

Each was investigated against current source, recent commits, and existing test
coverage.

## Issues identified

### Issue 1 — `facet.include must be an array of strings` is shape-only

| field | value |
|---|---|
| where it fires | `internal/workorder/workorder.go:1414-1418` (`validateFacetStringList`) and `:1707-1716` (`validateStringList`) |
| recent commit | `86e1f94 Tightening` touched `workorder.go` |
| symptom | first draft submitted `facet.include` as a single string; validator returned exit 2 with `error: facet.include must be an array of strings` |
| diagnostic quality | message states expected shape only; does not name the detected JSON type, the offending value, or the 1-8 item count constraint the validator already knows |
| test coverage | none — grepping `internal/` and `tests/` for `facet.include must be` returns zero hits; only the success path is exercised |

Real friction, low severity. A more diagnostic message would have shortened
the drafting round-trip from "rewrite the work order" to "convert the string
to a one-element array."

### Issue 2 — SKILL.md drafting invariants do not state field shapes

| field | value |
|---|---|
| where it fires | `skills/bakeoff-run/SKILL.md` drafting-invariants section |
| symptom | skill prose says "use `facet.include` / `facet.exclude` as descriptive criteria, not path globs"; it does not say the values are JSON arrays of strings; only `examples/review.work-order.json` shows the shape |
| consequence | drafting agents following the prose without re-reading the example produce string-shaped fields, then hit Issue 1 at validate |

This is the upstream cause of Issue 1. Fixing this is the highest-leverage
change because it prevents the friction at the source.

### Issue 3 — Prose-path warning has no negation awareness

| field | value |
|---|---|
| where it fires | `internal/repocontext/repocontext.go:163` (`ValidateProsePaths`) surfaced via `internal/commands/validatecmd/validate.go:206` |
| recent commit | `7e77373 code review` (most recent touch to repocontext) |
| symptom | background text "At draft time no commands/rerun.md or commands/verify.md were present; that absence is itself in scope" produced two advisory warnings, even though the surrounding prose explicitly names the absence |
| consequence | for audit-shaped work orders that name missing files as their subject, the warning is a false positive. Validation still exits 0, but the noise erodes signal value of future warnings |

The current suppression filter `plausibleMissingPath` only considers token
shape and suggestion proximity; it does not consider whether the surrounding
sentence negates existence. Tests in `internal/repocontext/repocontext_test.go`
cover slash-delimited prose, absolute paths under root, markdown link targets,
and root typos — but not negation context.

### Issue 4 — `bakeoff validate` advisory-warning categories are not documented

| field | value |
|---|---|
| where it fires | `docs/cli-reference.md` under `## bakeoff validate` (around line 195) |
| symptom | reference documents that validation "may also emit an advisory-only warning" but does not enumerate the categories or assure callers that exit 0 still ships |
| categories | prose-path missing under context-root, judge-family same_as_some/same_as_all, metric-verifier hygiene (noise-floor, one-run, unprotected repo-relative command, missing final-JSON n), goal/background path-like-token mentions |

Not a defect; a documentation completeness gap. Users running `validate` in CI
or scripts benefit from knowing which advisory categories are stable and
script-safe to ignore.

### Non-issues (working as designed)

| event | finding |
|---|---|
| `codex-gpt5` stderr volume (351 KB observed, truncated to 60 KB on disk) | classifier in `internal/runner/runner.go` already labels this `diagnostic` and the run exits `ok`. Expected codex CLI behavior. No action. |
| `claude-sonnet` 600 s quiet streak | heartbeat surfaces "long quiet; provider output may be buffered until completion" at the right time. No action. |
| Judge-family `same_as_some` advisory | `afc0c7c narrow third-party judge advisory` intentionally narrowed scope; message is short, advisory-only, and accurate. No action. |

## Proposed fixes

### Fix 1 — Tighter `must be an array of strings` diagnostic (Issue 1)

| field | value |
|---|---|
| files | `internal/workorder/workorder.go`, `internal/workorder/workorder_test.go` |
| change | include the detected JSON type in the error message; for `validateFacetStringList`, also include the item-count expectation already known to the function. Example wording: `facet.include must be an array of strings (got string); facet.include holds 1-8 items` |
| test | add a unit test in `workorder_test.go` covering the type-error path for both `validateFacetStringList` (facet.include, facet.exclude) and `validateStringList` (triage final_json fields) |
| size | ~15 lines including the test |
| risk | nil — message-only change; existing call sites unaffected |

### Fix 2 — SKILL.md field-shape line (Issue 2)

| field | value |
|---|---|
| file | `skills/bakeoff-run/SKILL.md` (drafting-invariants section) |
| change | one-line addition: `background`, `facet.include`, and `facet.exclude` are JSON arrays of strings; one criterion per element. `facet.include` accepts 1-8 items; `facet.exclude` accepts 0-8. |
| size | one line |
| risk | nil |

### Fix 3 — Negation-aware prose-path warning (Issue 3)

| field | value |
|---|---|
| files | `internal/repocontext/repocontext.go`, `internal/repocontext/repocontext_test.go` |
| change | in `ValidateProsePaths` (or `plausibleMissingPath`), check whether the missing token's containing sentence (or a ~30-character window around the token) contains a negation/absence marker: `no`, `not`, `absent`, `missing`, `does not exist`, `not present`, `was not`, `absence`, `removed`, `does not have`. If yes, suppress the warning |
| tests | (a) negated mention does not warn; (b) plain mention still warns; (c) typos near a negation still warn when the suggestion list is non-empty (typo signal beats negation signal) |
| size | ~30 lines including tests |
| risk | low — heuristic-only; warning is advisory so a wrong call in either direction has no execution impact |
| alternative considered | schema escape `validation.expected_missing_paths: [...]`. Rejected: more schema surface for a non-blocking warning |

### Fix 4 — Document `bakeoff validate` advisory-warning categories (Issue 4)

| field | value |
|---|---|
| file | `docs/cli-reference.md` under `## bakeoff validate` |
| change | one short paragraph listing the four advisory-warning categories (prose-path, judge-family, metric-verifier hygiene, goal/background path-like-token mention) with one-line example wording each, plus the line "advisory warnings do not change exit status; validation still exits 0" |
| size | one short paragraph |
| risk | nil |

## Sequencing

| order | fix | rationale |
|---|---|---|
| 1 | Fix 2 (SKILL.md field-shape line) | one line; eliminates the upstream cause of Issue 1; ships immediately |
| 2 | Fix 1 (diagnostic message + test) | small, low-risk; reduces friction for any future drafter who hits a similar type mismatch; first test coverage for the type-error path |
| 3 | Fix 4 (cli-reference.md warning section) | doc-only; safe to ship alongside Fix 1 |
| 4 | Fix 3 (negation-aware warning + tests) | heuristic change, slightly larger surface; ship after the smaller fixes land |

Recommend a single commit for Fixes 1+2+4 (skill prose + tightened error message
+ doc paragraph) and a separate commit for Fix 3 so the heuristic change has a
clean blame and a focused review.

## Out of scope

- The 24 audit findings about README/commands docs vs the Go CLI. Those are
  tracked through the run's triage at `runs/2026-05-26-f96d/triage/triage.md`
  and require a separate prioritization pass (see triage's `fix_now`, `defer`,
  and `reproduce` buckets).
- Provider stderr handling changes for codex.
- Heartbeat or quiet-tick behavior changes.
- Judge-family advisory scope changes (already narrowed by `afc0c7c`).
