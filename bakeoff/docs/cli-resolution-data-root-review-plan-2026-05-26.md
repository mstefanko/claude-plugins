# Plan: CLI resolution / data-root review followups

**Date:** 2026-05-26
**Source run:** `bakeoff` code-review research, run id `2026-05-26-bad8`
**Run dir:** `runs/2026-05-26-bad8/`
**Mode:** `gather` / facet `code-review`
**Providers:** `claude-sonnet` (sonnet, codebase, high), `codex-gpt55` (gpt-5.5, codebase, high)
**Judge:** `claude opus` (xhigh)
**Triage:** `claude opus` (xhigh), enabled by default for code-review
**Inspect:** `bakeoff show 2026-05-26-bad8 --triage`
**Artifacts:** `runs/2026-05-26-bad8/{report.md,decision.json,triage/triage.md,triage/final.json}`

## What we investigated

Audit of the bakeoff plugin's CLI resolution and setup data-root changes
introduced by commits `68e9e46` (binary cache resolution) and `7f5416c`
(binary). Scope was scripts that share the data-root resolution helper:

- `scripts/bakeoff-setup`
- `scripts/bakeoff-ensure-cli`
- `scripts/bakeoff-uninstall`
- `scripts/bakeoff-lib`
- `scripts/bakeoff-setup-tests`
- `commands/setup.md`
- `docs/binary-cache-resolution-patch-plan-2026-05-22.md` (design intent)

Six acceptance criteria framed the review:

1. Precedence order is documented and identical across setup, ensure-cli,
   and uninstall.
2. ensure-cli never returns a non-executable path.
3. Uninstall only removes paths the plugin owns; never touches operator-set
   roots or conventional Claude data roots.
4. source-build and release-binary install kinds produce equivalent layouts.
5. `scripts/bakeoff-setup-tests` covers env precedence and ownership invariants.
6. `commands/setup.md` user-facing wording matches script behavior.

## Run result

- **Decision kind:** `structured_union` (judge ran, no contested winner — both
  providers' findings unioned).
- **Triage:** complete. 31 items: 11 real_issue, 13 false_positive, 6
  evidence_gap, 1 plan_doc_drift.
- **Recommended actions:** 8 fix_now, 4 reproduce, 4 document, 2 defer, 13 ignore.

## Issues identified (triage-verified fix_now items)

### Code bugs

#### T-020 — Uninstall ownership violation (medium severity)

`scripts/bakeoff-uninstall:247-249` calls `remove_dir "$cache_root"` on the
conventional Claude cache root with no ownership check. Wipes every cached
bakeoff plugin install including ones managed by Claude's plugin manager.
Directly violates acceptance criterion 3.

Evidence: `scripts/bakeoff-lib:109-113`, `scripts/bakeoff-uninstall:247-249`.

#### T-021 — ensure-cli fallback chain halts on probe failure (medium severity)

`scripts/bakeoff-ensure-cli:68-75` runs `report_probe "$path" "$label" ||
exit 1`, which halts iteration on the first failed candidate. A corrupt
`$BAKEOFF_PLUGIN_DATA/bin/bakeoff` blocks all lower-priority fallbacks
(`CLAUDE_PLUGIN_DATA`, conventional roots, dist) instead of falling through.
Violates the fallback intent of acceptance criterion 2.

Evidence: `scripts/bakeoff-ensure-cli:68-75`.

#### T-006 — Setup/uninstall path-normalization asymmetry (low severity)

`bakeoff-setup` converts relative `BAKEOFF_PLUGIN_DATA` to absolute via
`$(pwd)`; `bakeoff-uninstall` does not. Operator-set relative env at uninstall
time can target the wrong root.

Evidence: `scripts/bakeoff-setup:367-370`, `scripts/bakeoff-uninstall:251-253`.

Fix: hoist absolute-path normalization into `bakeoff_data_root()` in
`bakeoff-lib` so all three callers share one normalization path.

#### T-002 — Cleanup leak for `.version.XXXXXX` (low severity)

`cleanup()` removes `$install_tmp` and `$tmp_dir` but not the
`$data/.version.XXXXXX` file. `cleanup_plugin_data_dir` removes specific paths
and skips hidden `.version.*` siblings. Small race window between `mktemp` and
`mv`.

Evidence: `scripts/bakeoff-setup:433-491`, `scripts/bakeoff-setup:618-645`,
`scripts/bakeoff-uninstall:126-135`.

#### T-001 — Misleading setup error (low severity)

`scripts/bakeoff-setup:365` says "CLAUDE_PLUGIN_DATA is not set" but the same
die path fires when `bakeoff_conventional_data_root()` fails and
`BAKEOFF_PLUGIN_DATA` is unset. Error should mention all three resolution
sources.

Evidence: `scripts/bakeoff-setup:364-366`, `scripts/bakeoff-lib:55-70`.

#### T-003 — Path normalization drift (low severity, cosmetic)

`bakeoff_data_root()` does not strip trailing slashes; `bakeoff_candidate_binaries()`
does. Produces user-visible `/data//bin/bakeoff` in JSON output and dry-run
messages. Bash treats `//` and `/` equivalently for execution, so functional
impact is nil.

Evidence: `scripts/bakeoff-lib:55-70`, `scripts/bakeoff-lib:173-181`,
`scripts/bakeoff-setup:367-373`.

### Doc / test drift

#### T-018 — `commands/setup.md` install-path example does not reflect precedence (medium severity)

User-facing prose at `commands/setup.md:31-32` hardcodes an install-path
example that does not vary with `BAKEOFF_PLUGIN_DATA` /
`CLAUDE_PLUGIN_DATA`. Operators with either env set will see the doc
mis-describe their install location. Violates acceptance criterion 6.

Evidence: `commands/setup.md:31-32`, `scripts/bakeoff-lib:55-70`,
`scripts/bakeoff-setup:363-373`.

#### T-019 — Missing test for distinct-path `CLAUDE_PLUGIN_DATA` precedence (medium severity)

`scripts/bakeoff-setup-tests` covers duplicate-data dedup (sets
`CLAUDE_PLUGIN_DATA=$data/` against `BAKEOFF_PLUGIN_DATA=$data/`) but never
verifies that `CLAUDE_PLUGIN_DATA` at a path **distinct** from the others
takes precedence over its lower-priority alternatives. Violates acceptance
criterion 5.

Evidence: `scripts/bakeoff-setup-tests:269-360`, `scripts/bakeoff-setup-tests:291-312`.

### Plugin skill drift (surfaced by this session, not in triage)

The drafting of this very work order needed three validation retries
(`facet.focus` 729 → 590 → 508 chars over the 500 cap) plus one shape miss
(`facet.include` / `facet.exclude` written as single strings instead of arrays).
The skill prompt at `skills/bakeoff-run/SKILL.md:237-241` has the rules but:

- "500 or fewer" is a limit, not a target. When optimizing for everything
  else, drafts regress toward the limit.
- "Descriptive criteria, not path globs" does not name the JSON shape; the
  natural reading is "a single descriptive paragraph", while the schema
  requires an array of strings.
- "Use examples/review.work-order.json as the example" reads aspirational, not
  load-bearing. The example was not opened during drafting.

The canonical `examples/review.work-order.json` shows the target shape: a
~60-character `facet.focus` and 3-5 short array entries each for `include`
and `exclude`.

## Proposed fixes

### Skill prompt — `skills/bakeoff-run/SKILL.md:237-241`

```diff
-`schema_version: 1`. For code-review facets, use `facet.kind: "generic"` and
-write `facet.focus` as one string of 500 characters or fewer with no backticks,
-angle brackets, or `</facet>`; write `facet.include` / `facet.exclude` as
-descriptive criteria, not path globs. Use `examples/review.work-order.json` as
-the code-review facet example.
+`schema_version: 1`. For code-review facets, use `facet.kind: "generic"` and
+write `facet.focus` as one string targeted at 200-300 characters and hard
+capped at 500, with no backticks, angle brackets, or `</facet>`; write
+`facet.include` and `facet.exclude` as JSON arrays of short descriptive
+criterion strings (not single paragraphs, not path globs). Copy field shapes
+from `examples/review.work-order.json` before drafting any code-review work
+order; if facet.focus exceeds ~300 characters before trimming, cut rather
+than expand.
```

Optional companion edit in the same skill, pinning all five research budget
defaults so drafts stop diverging from the canonical example:

```diff
-research providers come from the provider-pair rules above with catalog default models
-and high effort; build providers use `scope: "codebase"`; judge is Claude
-`opus` xhigh; research budget is 900 seconds/60000 bytes; build budget is 1200
-seconds/80000 bytes.
+research providers come from the provider-pair rules above with catalog default models
+and high effort; build providers use `scope: "codebase"`; judge is Claude
+`opus` xhigh; research budgets are 900s wall, 60000 bytes out, 60s heartbeat,
+10s output_cap_grace, 60000 bytes max overrun; build budget is 1200s wall,
+80000 bytes out (other budget keys default to research values).
```

### Code — `scripts/bakeoff-lib`

Add `bakeoff_data_root()` (or its callers') absolute-path normalization, with
trailing-slash stripping in one place. T-003 and T-006 collapse into a single
helper change shared by setup/ensure-cli/uninstall.

### Code — `scripts/bakeoff-ensure-cli:68-75`

Replace `report_probe "$path" "$label" || exit 1` with a continue-on-failure
loop so a corrupt high-priority candidate does not block lower-priority
fallbacks. Only exit with failure when every candidate has been tried.

### Code — `scripts/bakeoff-uninstall:247-249`

Before `remove_dir "$cache_root"`, check ownership. Concretely: refuse to
delete the conventional Claude cache root unless a bakeoff-owned marker file
(for example, `$cache_root/.bakeoff-owned`) is present, written by
bakeoff-setup at install time. Only remove the bakeoff-owned subtree under
the conventional root, never the root itself.

### Code — `scripts/bakeoff-setup:364-366`

Update the die message to name all three resolution sources, not just
`CLAUDE_PLUGIN_DATA`.

### Code — `scripts/bakeoff-setup` cleanup / `bakeoff-uninstall`

Extend `cleanup()` (or `cleanup_plugin_data_dir`) to remove
`$data/.version.*` siblings.

### Doc — `commands/setup.md:31-32`

Rewrite the install-path example to show the precedence rule rather than a
single literal path: surface that the path resolves via
`BAKEOFF_PLUGIN_DATA` → `CLAUDE_PLUGIN_DATA` → conventional Claude root, and
that the literal value depends on which is set.

### Tests — `scripts/bakeoff-setup-tests`

Add a test that sets `CLAUDE_PLUGIN_DATA` to a distinct path (not equal to
`BAKEOFF_PLUGIN_DATA` and not equal to the conventional root) and asserts the
install lands under `CLAUDE_PLUGIN_DATA` rather than the conventional root.
Add a test for relative `BAKEOFF_PLUGIN_DATA` and for the
`ensure-cli`-falls-through-on-corrupt-high-priority case.

## Verification

Single gate: `scripts/bakeoff-setup-tests` (the canonical setup test
harness) must pass after the changes. Add the new precedence,
fallback-after-corruption, and ownership-marker tests to the harness so the
gate exercises the fixes.

Manual smoke once the gate passes:

- `BAKEOFF_PLUGIN_DATA=/tmp/op /bakeoff:setup` → installs to `/tmp/op/bin/bakeoff`.
- `CLAUDE_PLUGIN_DATA=/tmp/harness /bakeoff:setup` (no BAKEOFF_PLUGIN_DATA) →
  installs to `/tmp/harness/bin/bakeoff`.
- Corrupt `/tmp/op/bin/bakeoff`, set both env vars; `bakeoff-ensure-cli
  --check --print-path` should fall through to `CLAUDE_PLUGIN_DATA`.
- `bakeoff-uninstall` with no `BAKEOFF_PLUGIN_DATA` should refuse to delete
  the conventional Claude cache root unless the ownership marker is present.

## Out of scope

- Bundled Go CLI internals.
- Provider auth probes.
- The bakeoff-run skill text beyond the two specific edits above.
- Historical implementation plans not tied to the binary-cache-resolution
  change.
