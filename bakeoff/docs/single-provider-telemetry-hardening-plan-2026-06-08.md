# Single-Provider / Telemetry Hardening Plan

Date: 2026-06-08

Status: proposed — findings from live-test inspection, unverified by a second agent

Scope: fix and harden rough edges found while live-testing the recently added
bakeoff-core telemetry / validation surface. These are **investigation
candidates**, not confirmed root causes. A new agent should reproduce each
claim against the run artifacts and current source before changing code.

---

## How this plan was produced

A live `/bakeoff:run` was executed as a functional test of the new telemetry
surface. It was an `analyze` run (a plan review of the single-provider plan),
so the providers/judge mechanics exercised the schema-v2 telemetry, the
position-swap judge, and scope-enforcement recording. The run completed
cleanly (exit 0, both providers `ok`, judge converged) — these findings are
about the *observability/validation surface*, not run failure.

### Run under inspection

- **Run id:** `live-single-provider-plan-review`
- **Artifacts root:** `runs/live-single-provider-plan-review/`
- **Mode:** `analyze`; providers `claude/sonnet` + `codex/gpt-5.5`; judge `claude/opus` (xhigh)
- **Outcome:** `pick_winner` → `claude`, via `spine_tiebreak: swap_agreement`
- **Inspect:** `bakeoff show live-single-provider-plan-review`
- **Key files:**
  - `runs/live-single-provider-plan-review/manifest.json` (telemetry block, `schema_version`)
  - `runs/live-single-provider-plan-review/decision.json` (`spine_tiebreak`)
  - `runs/live-single-provider-plan-review/meta.json` (`resolved_models.*.scope_enforcement`)
  - `runs/live-single-provider-plan-review/providers/{claude,codex}/status.json`
  - `runs/live-single-provider-plan-review/providers/codex/stderr.txt` (truncated, 60049 B)
  - `runs/live-single-provider-plan-review/report.md` (Provider Status table)
  - `runs/live-single-provider-plan-review/work-order.json`

### Reproduce the raw evidence

```bash
cd <bakeoff-repo-root>
R=runs/live-single-provider-plan-review
python3 -c "import json;m=json.load(open('$R/manifest.json'));print(json.dumps(m['telemetry'],indent=1))"
python3 -c "import json;print(json.load(open('$R/decision.json'))['spine_tiebreak'])"
python3 -c "import json;print(json.dumps(json.load(open('$R/meta.json'))['resolved_models'],indent=1))"
python3 -c "import json;print(json.load(open('$R/providers/codex/status.json'))['stderr_truncated'])"
wc -c $R/providers/codex/stderr.txt
```

---

## Finding 1 — `telemetry.judge.selection_basis` is null (data not wired)

**Severity:** medium · **Source files:** `internal/decision/decision.go`,
`internal/manifest/manifest.go`

**Claim:** The winner was selected via `swap_agreement`
(`decision.json.spine_tiebreak == "swap_agreement"`,
`telemetry.judge.position_swap_used == true`), but
`manifest.json.telemetry.judge.selection_basis == null`. The schema-v2 field
intended to record *why* the winner was chosen is never populated, so anything
consuming telemetry to explain selection gets nothing.

**Evidence (observed):**
- `manifest.json` → `telemetry.judge.selection_basis: null`, `position_swap_used: true`
- `decision.json` → `spine_tiebreak: "swap_agreement"`, `canonical_winner: "claude"`

**Investigate:** Where is `selection_basis` meant to be set? Is it dead/new
schema scaffolding, or set only on a code path this run didn't hit (e.g.
non-swap selection)? Confirm whether it should mirror `spine_tiebreak` or carry
a distinct vocabulary.

**Required change (proposed):** Populate `telemetry.judge.selection_basis`
from the resolved selection path (e.g. `swap_agreement`, `positional`,
`single_provider`) wherever the judge decision is finalized.

**Definition of done:** A re-run (or unit test over a synthetic decision)
yields a non-null `selection_basis` consistent with `decision.spine_tiebreak`.

---

## Finding 2 — `bakeoff validate` false-positive on prose "paths"

**Severity:** medium · **Source files:** `internal/workorder/workorder.go`
(and/or the validation/reference-check path it calls)

**Claim:** Validating the work order emitted:
`warning: background references "decision/manifest/verify" which does not exist
under <context-root>; did you mean one of: internal/verify/?`
That token is plain English in `background`
("decision/manifest/verify behavior the plan assumes"), not a filepath. The
reference-existence checker treats any slash-joined token as a path, so prose
trips it. Noisy false positives can bury a genuine missing-path warning.

**Evidence (observed):** Re-run validation to reproduce:
```bash
bakeoff validate runs/live-single-provider-plan-review/work-order.json
```
The `background` field contains the offending prose; the warning fires while
the work order is otherwise valid.

**Investigate:** Find the heuristic that scans `background` (and other free-text
fields) for path-like tokens. Determine its match rule (any `a/b` substring?).

**Required change (proposed):** Only flag tokens that look like real paths —
require a file extension, or a known root prefix (`internal/`, `docs/`,
`examples/`, `cmd/`), or skip tokens embedded in multi-word prose. Keep the
"did you mean" helper for genuine path-shaped tokens.

**Definition of done:** A work order whose `background` contains
`decision/manifest/verify behavior` validates with no path warning, while a
real missing reference like `internal/nope/missing.go` still warns.

---

## Finding 3 — truncated provider stderr not surfaced in report.md; tail may be lost

**Severity:** low–medium · **Source files:** `internal/verify/verify.go` or the
report/status writer that owns truncation + the Provider Status table
(confirm owner), `internal/manifest/manifest.go`

**Claim:** `telemetry.artifacts.output_truncation_count == 1`, correctly
attributed to codex (`providers/codex/status.json.stderr_truncated == true`;
stderr capped at 60049 B). Attribution at the status level is good. But
`report.md`'s Provider Status table shows stderr *bytes* with no truncation
indicator — a reader can't tell codex's stderr was clipped. stderr is where
fatal provider errors land: this run's codex stderr tail held a real
`ERROR codex_core::session: failed to record rollout items: thread … not found`
(benign here, exit 0, handled correctly). If a future fatal error sits
mid-stream, capping could drop it silently.

**Evidence (observed):**
- `providers/codex/status.json` → `stderr_truncated: true`
- `wc -c providers/codex/stderr.txt` → `60049`
- `report.md` Provider Status row for codex shows bytes, no truncation flag

**Investigate:** Confirm truncation strategy (head-keep vs tail-keep vs
head+tail). Determine why codex emits ~60 KB stderr (reasoning/log noise)
while claude emits 0 B — is the cap reasonable?

**Required change (proposed):** (a) Mark truncation in the report's Provider
Status table (e.g. `12.5 KB (stderr truncated)`). (b) Prefer keeping the
stderr **tail** when capping, since errors cluster at the end.

**Definition of done:** A run with truncated stderr shows a truncation marker
in `report.md`; the retained stderr includes the final lines.

---

## Finding 4 — `scope_enforcement.enforcement_level: "partial"` with null reason

**Severity:** low · **Source files:** scope-enforcement recorder (confirm
owner; check `internal/` scope/exec path), surfaced via `meta.json` and
`manifest.json`

**Claim:** Both providers report `enforcement_level: "partial"` with
`fallback_reason: null`, even though the applied mechanisms
(`claude:disallowedTools=WebFetch,WebSearch`; `codex:sandbox=read-only`,
`codex:disable=web_search`) *are* the full best_effort codebase enforcement for
those backends. "partial" + null reason reads like something failed when
nothing did.

**Evidence (observed):** `meta.json` →
`resolved_models.providers.{claude,codex}.scope_enforcement` shows
`enforcement_level: "partial"`, `fallback_reason: null`, populated
`mechanisms[]`.

**Investigate:** What distinguishes `partial` from `full`? Is any provider
ever `full`, or is `partial` always emitted under best_effort?

**Required change (proposed):** When `partial`, record which stronger mechanism
was unavailable in `fallback_reason`; or relabel to convey "best_effort fully
applied" when all available mechanisms succeeded.

**Definition of done:** Enforcement level is either accompanied by a non-null
reason or accurately reflects that all available mechanisms were applied.

---

## Not a bug (context for the investigator)

- `manifest.schema_version: 1` vs `telemetry.schema_version: 2` is intentional
  dual-versioning, not corruption. It is, however, **undocumented** — this is
  plan finding **F-008** in
  `docs/single-provider-run-mode-option-4-implementation-plan-2026-06-08.md`.
  Document the manifest-vs-telemetry schema distinction in
  `docs/cli-reference.md` and/or `docs/work-orders.md`.
- The codex `ERROR codex_core::session: failed to record rollout items` is a
  codex-CLI-internal error, not a bakeoff defect; bakeoff correctly kept the
  provider `ok` (exit 0, valid `final_json` from stdout).

---

## Suggested execution order

1. Finding 2 (validate false-positive) — self-contained, easy verifier.
2. Finding 1 (`selection_basis`) — small, high-value telemetry fix.
3. Finding 3 (stderr truncation surfacing + tail-keep).
4. Finding 4 (scope enforcement labeling).
5. Documentation (F-008 schema-versioning note).

Findings 1 and 2 are the cleanest candidates for a verifier-gated `build`
work order; 3–5 benefit from a human/agent decision on intended behavior first.
