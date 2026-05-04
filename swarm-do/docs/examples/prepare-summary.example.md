# Prepare Summary — Example Output

Example human-readable summary produced by the proposed `bin/swarm prepare report <run-id>` subcommand, also rendered automatically at the end of `bin/swarm prepare <plan-path>` (unless `--quiet` is passed). All fields below are derived from artifacts that already exist after a successful prepare:

- `swarm-do/data/runs/<run-id>/prepared.md`
- `~/.local/share/swarmdaddy/runs/<run-id>/prepared_plan.v1.json`
- `swarm-do/data/runs/<run-id>/work_units/*.work_units.v2.json`

The renderer adds no new state — it only formats existing data into a single human-scannable view.

---

## Pre-acceptance review

**Run**: `01KQSDTRN4HFRRXAVARE8X0QNZ`
**Status**: `ready_for_acceptance`
**Git base**: `45f6a25` (current main HEAD — fanout regressions fix is in base)
**Source plan SHA**: `510806a3...488b66` (locked to `docs/ecc-pattern-adoption-plan.md`)

### Phase map (6 phases, sequential)

| Phase | Title                            | Complexity | Decomp? | Depends |
| ----- | -------------------------------- | ---------- | ------- | ------- |
| 0     | Baseline Inventory And Contracts | hard       | yes     | —       |
| 1     | `bin/swarm selftest`             | hard       | yes     | 0       |
| 2     | Hook Runtime Profiles            | hard       | yes     | 1       |
| 3     | Security And Config Audit        | hard       | yes     | 2       |
| 4     | Sanitized Activity Telemetry     | hard       | yes     | 3       |
| 5     | Work-Unit Operator Snapshots     | hard       | yes     | 4       |

All 6 phases set `requires_decomposition=true`, so the dispatcher's decomposer will further split each into work units before fanning out. Six work-unit sidecars are written under `swarm-do/data/runs/01KQSDTRN4HFRRXAVARE8X0QNZ/work_units/`.

### Findings — all 23 are advisory (none blocking)

Same 4 patterns repeated across phases:

1. **(×6)** "Phase has no Verification/Validation Commands section; using plan-level Test Strategy / Definition Of Done as fallback." — fine; the plan's Test Strategy + DoD sections cover it.
2. **(×6)** "Phase is too broad for one writer unit; split it or rely on prepare decomposition." — already handled (`requires_decomposition=true` on every phase).
3. **(×6)** "Phase inferred as hard but has no explicit complexity tag." — informational; correctly inferred.
4. **(×5)** "Phase relies on plan-level validation while a later phase introduces validation infrastructure." — chicken-and-egg ordering note (e.g., Phase 4 telemetry references Phase 3's redaction module). The plan already pins this in §"Resolved Decisions".

### Other notes worth surfacing

- **Phase 0 and Phase 1 are mostly no-ops.** The plan itself says: "Phase 0 is effectively complete," "Phase 1 has shipped." Writers in those phases will likely just verify fixtures/ADR alignment and produce docs-only changes. That's expected — don't be surprised when those phases close fast.
- **Plan's Test Strategy** still names the legacy `PYTHONPATH=py python3 -m unittest discover -s py -p 'test_*.py'` form. Per the project memory, that's still supported alongside `bin/swarm test unit`, so not a blocker — but writers might emit either form.
- **No `bd_epic_id` yet** — that gets minted on `do --prepared` dispatch.

### Verdict

Nothing in the prepare output blocks acceptance. The advisories are all about plan style, not plan correctness, and the dispatcher handles decomposition automatically. Safe to accept.

**To accept:**

```
/swarmdaddy:prepare --accept 01KQSDTRN4HFRRXAVARE8X0QNZ
```

**Then dispatch (fanout is the default):**

```
/swarmdaddy:do --prepared 01KQSDTRN4HFRRXAVARE8X0QNZ
```

---

## Required fields in the rendered summary

The renderer must produce **at minimum** the following sections in this order. Every section is derivable from artifacts; if a field is missing, render it as `—` rather than omitting the row.

1. **Header** — run-id, status (`ready_for_acceptance` / `accepted` / `rejected` / `needs_input`), git base SHA + ref, source plan path, source plan SHA (truncated to 8/8), prepared plan SHA (truncated to 8/8), preset name (when present in artifact).
2. **Phase map table** — one row per `phase_map` entry: phase id, title, complexity, requires_decomposition, depends_on_phase_ids. Sorted by phase id.
3. **Work-unit summary** — total work-unit sidecar count, count per phase (joined with phase title), location of sidecars.
4. **Findings table** — bucketed by severity (`critical | high | medium | low | advisory`), then by kind. For each bucket: count + one-line representative message. Group repeated patterns into `(×N)` rows like the example.
5. **Blocking verdict** — single line: either "Nothing in the prepare output blocks acceptance." or "Blocking findings: <comma-separated kinds>. Not safe to accept until resolved."
6. **Next-step commands** — a code block with the literal `/swarmdaddy:prepare --accept <run-id>` and `/swarmdaddy:do --prepared <run-id>` lines (substitute the actual run-id).

## Optional sections (render only when applicable)

- **Notes worth surfacing** — only emitted when the renderer detects one of:
  - phases marked "shipped" / "complete" in plan text (so writers in those phases will be near-no-ops),
  - presence of legacy test-strategy command forms (regex on plan text — keep the list small and deterministic),
  - mismatched preset between active-run.json (if present) and the prepared artifact.

## Output formats

- Default: Markdown (the format above), printed to stdout after the existing terse status block.
- `--json`: emit the same structured data as a JSON object so the TUI / dogfood loops can consume it without parsing text.
- `--quiet`: suppress the summary entirely and keep only the existing terse output (current behavior, for scripts).

## Re-rendering after the fact

`bin/swarm prepare report <run-id>` re-renders the summary from artifacts on disk for any prepared run, including already-accepted runs. It must not mutate any state.
