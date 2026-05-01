# Canonical-Path Leak Detector Fix Plan

Date: 2026-05-01
Owner: swarm-do runtime / launcher hardening
Reference incident: phase-sessions run `01KQJF1R90B5AYZCCYX7TYYB3B`
attempt 1, phase 0 — `canonical_path_leaked_in_tool_result` →
`permission_contract_failure`, blocked by `retry_policy_human_gate`.
Reviewed: 2026-05-01 (architect review rolled in below).

## Background

The post-launch transcript detector at
`py/swarm_do/pipeline/claude_transcript_diagnostics.py` parses Claude Code
session JSONL to surface tool errors and "canonical path" leaks — cases where
an agent appears to have referenced a path under the canonical source checkout
or the user's `~/.claude/` tree.

`_diagnostic_sensitive_patterns` builds a single pattern set from
`source_project_root`, `source_git_top_level`, `real_repo_root`, plus a hard
literal `/.claude/`. `_canonical_patterns` then expands each pattern into
project-dir-encoded variants (`-Users-mstefanko--claude-...`) and
JSON-slash-escaped variants (`\/.claude\/`). The expanded set is used for two
structurally different checks inside `parse_transcript`:

1. **Tool-input side** (`assistant.tool_use[*].input.file_path`/`path`) — flags
   when an agent calls Read/Edit/Write against a sensitive `file_path`.
2. **Tool-output side** (`user.tool_result[*].content`) — flags when any
   string inside a tool result body matches a sensitive pattern.

The bare `/.claude/` literal is acceptable on **path-bearing inputs** (any
agent passing a `file_path` containing `/.claude/` is almost certainly trying
to access foreign plugin or session state) and on **command-bearing inputs**
(Bash `command` strings). It is **misclassified everywhere else** — any
fixture, README, ADR, or schema example that documents the SwarmDaddy install
location (`~/.claude/plugins/...`) trips the detector when the agent reads or
edits it, because `~/.claude/` contains the substring `/.claude/`. The Phase 0
fixture `docs/examples/selftest.ok.json` does this on lines 71 and 81 to
document the `plugin_root` and `data_dir` example values for `bin/swarm
selftest --json`.

A naive split (drop bare `/.claude/` from output-side, keep on input-side) has
two structural problems surfaced in architect review:

- Recursive string-leaf scanning of any tool input would still hit
  `Write.content`, `Edit.old_string`, `Edit.new_string`, `MultiEdit.edits[]`,
  and `Grep.pattern`. A writer editing a doc or fixture that mentions
  `~/.claude/` would trip on input rather than content.
- Filtering only the raw `/.claude/` literal is not enough: `_canonical_patterns`
  has already materialized encoded variants like `--claude-` and
  `\/.claude\/`. Without provenance the variants survive even after the bare
  literal is removed.

It also opens an exfiltration gap: the input side currently only scans
`file_path`/`path` via `_tool_file_path`; Bash `command` is unscanned, so
today the only thing that catches `cat ~/.claude/projects/<sid>.jsonl` is the
output-side `/.claude/` content match. A surgical fix must close that gap by
broadening input-side scanning at the same time it relaxes content scanning.

The existing test `test_canonical_tripwire_matches_generic_encoded_claude_segment`
in `py/swarm_do/pipeline/tests/test_claude_transcript_diagnostics.py` (around
line 164) explicitly asserts the encoded variant `-CLAUDE-` matches content
when `sensitive_path_patterns=["/.claude/"]`. That test codifies the behavior
this plan removes; it must be inverted, not preserved.

The repo also contains hard-coded actual local roots in three test/fixture
files that are themselves read by the writer when reasoning about the
detector. They will trip the **precise** content-side patterns
(`source_git_top_level`) once the bare-literal noise is removed and only
precise leaks remain visible. Sanitizing those files is part of this fix.

## Goals

1. Eliminate the systemic false-positive that flags any tool result whose body
   contains the literal substring `/.claude/` or its encoded variants.
2. Preserve the existing protection against agents accessing sensitive
   `~/.claude/` paths via Read/Edit/Write — and extend it to Bash commands
   that today bypass `_tool_file_path`.
3. Stop bare-`/.claude/` matching from leaking into content fields of tool
   inputs (`Write.content`, `Edit.old_string`/`new_string`, `MultiEdit.edits[]`,
   `Grep.pattern`).
4. Keep the precise patterns (`source_project_root`, `source_git_top_level`,
   `real_repo_root`) checked on both input and output sides; their
   false-positive risk is low and the signal value is high.
5. Sanitize the two test/fixture files that hard-code the developer machine's
   `source_git_top_level` so reading them after the fix does not trip the
   precise content-side patterns.

## Non-Goals

- Do not change the policy mapping at
  `phase_autopilot_policy.py:191`. Once the detector is precise the existing
  `human_gate` escalation is correct.
- Do not change the launcher's dirty-checkout guard or the prepared-artifact
  staleness gate (`git_base_sha` strict-equality). Both are working as
  intended.
- Do not touch the `sensitive_path_blocked` content classifier at
  `claude_transcript_diagnostics.py:265`; it is already gated by
  `is_error=True` and has a small false-positive surface.
- Do not add a bypass flag for the human-gate. Treat the false-positive as a
  detector defect and fix the detector.
- Do not change the Phase 0 example fixtures
  (`docs/examples/selftest.ok.json`, etc.). They intentionally document the
  real install path shape; the detector must read them without flagging.

## Phase 1: Tighten Canonical-Path Detector With Field-Aware Scanning (complexity: hard, kind: bug)

### Objective

Replace the single-pattern, single-scan detector with a field-aware design:
scan tool inputs by field role (path vs command vs content vs other), preserve
pattern provenance so encoded variants of dropped patterns also drop, and
introduce broader Bash command scanning so the protection surface around
`~/.claude/` does not depend on tool-result content matching.

### Current Status

- `_diagnostic_sensitive_patterns(command_metadata)` returns a single
  `tuple[str, ...]` including the bare `/.claude/` literal.
- `_canonical_patterns(patterns)` materializes one tuple of patterns with
  encoded and JSON-escaped variants. Provenance is lost during expansion.
- `parse_transcript` uses the same `canonical_patterns` for tool_use input
  scans (around line 200) and tool_result content scans (around line 220).
- `_tool_file_path(value)` extracts only `input.file_path` and `input.path`.
  Bash `command`, Grep `pattern`, and any other free-form input fields are
  not scanned.
- `load_transcript_diagnostics(sensitive_path_patterns: Iterable[str])` has
  no `command_metadata`; it cannot call `_diagnostic_sensitive_patterns`
  directly.
- `diagnose_launch(launcher_result, command_metadata)` calls
  `_diagnostic_sensitive_patterns(command_metadata)` to build the patterns it
  passes through.

### Implementation

1. **Provenance-tracked pattern sets** in
   `claude_transcript_diagnostics.py`.
   Introduce a small frozen dataclass or named tuple `_PatternSets` with three
   tuples:
   - `path_patterns`: matches in path-bearing input fields. Includes precise
     source roots and the bare `/.claude/` literal (plus encoded/escaped
     variants of each).
   - `command_patterns`: matches in command-bearing input fields. Same
     contents as `path_patterns`.
   - `content_patterns`: matches in tool_result content **and** in
     content-bearing input fields. Includes only precise source roots (plus
     their encoded/escaped variants). The bare `/.claude/` literal and any
     variant generated *from* the bare literal are excluded.

   Add a private `_PatternSource` tag (e.g. `"bare_claude"` vs
   `"source_root"`) at materialization time. `_canonical_patterns` returns a
   list of `(pattern, source)` pairs internally; the public flat tuple
   contracts are derived by filtering on source for each set.

2. **Field-aware tool-input walker.**
   Replace `_tool_file_path` with `_tool_input_fields(value: Any) ->
   Iterator[tuple[str, str]]` that yields `(field_path, string_value)` pairs
   for every string leaf in a tool_use input payload. `field_path` uses dotted
   notation for nesting (`edits[0].old_string`). Keep a thin
   `_tool_file_path(value)` wrapper that returns the first
   `file_path`/`path` value so the existing `ToolErrorDiagnostic.file_path`
   field can still be populated.

   Define a deterministic field-role map:
   - **path**: `file_path`, `path`, `notebook_path`.
   - **command**: `command`, `command[<n>]` (when the input is a list).
   - **content**: `content`, `old_string`, `new_string`, `edits[*].old_string`,
     `edits[*].new_string`, `pattern` (Grep), `prompt` (sub-agent task input
     where applicable).
   - **other**: everything else (booleans, numbers, lists of non-string
     items, `description`, `timeout`, etc.).

3. **Field-aware scan in `parse_transcript`.**
   For each tool_use block, iterate `_tool_input_fields(input)` and look up
   the role for each `field_path`. Match against the pattern set for that
   role:
   - **path** → `path_patterns`
   - **command** → `command_patterns`
   - **content** → `content_patterns`
   - **other** → no scan
   Record canonical hits with `tool_name`, `tool_use_id`, the matched
   `field_path`, the offending excerpt (capped via `_excerpt`), and
   `file_path` populated only when the match came from a path-role field.

   For tool_result blocks, scan `content` against `content_patterns`. No
   change to error-classification logic.

4. **Public API compatibility.**
   Introduce a private normalizer
   `_coerce_pattern_sets(patterns: Iterable[str]) -> _PatternSets` that:
   - Treats every pattern as a precise source-root unless the pattern equals
     the bare `/.claude/` literal exactly, in which case it is tagged
     `bare_claude`.
   - Materializes encoded and JSON-escaped variants per pattern, carrying
     provenance forward.
   - Builds the three role-tuples by filtering on provenance.
   `load_transcript_diagnostics` and `parse_transcript` call this normalizer
   when given a flat `Iterable[str]`. `diagnose_launch` calls
   `_diagnostic_sensitive_patterns(command_metadata)` directly, which now
   returns a `_PatternSets`. External signatures of
   `load_transcript_diagnostics`, `parse_transcript`, and `diagnose_launch`
   remain `Iterable[str]` for `sensitive_path_patterns` so plugin consumers
   are unaffected.

5. **`ToolErrorDiagnostic` shape.**
   Add an optional `field_path: str | None = None` to record where the match
   came from for canonical hits. Keep `file_path` semantics: populated only
   when the matched value came from a path-role field (so existing readers
   that interpret `file_path` as a real fs path do not break).

6. **Failure-classifier propagation.**
   Verify `phase_failure_classifier.py` still receives
   `tool_error_kind="canonical_path_leaked"` for both input and content
   matches. The structural change is additive; no classifier change should
   be required, but confirm with the targeted test below.

### Files

| File | Change |
| --- | --- |
| `py/swarm_do/pipeline/claude_transcript_diagnostics.py` | Add `_PatternSets`, `_coerce_pattern_sets`, `_tool_input_fields`, role map; rework `_canonical_patterns` to track provenance; rework `_diagnostic_sensitive_patterns` to return `_PatternSets`; rework `parse_transcript` to be field-aware. Keep `_tool_file_path` and public signatures stable. Add optional `field_path` to `ToolErrorDiagnostic`. |
| `py/swarm_do/pipeline/tests/test_claude_transcript_diagnostics.py` | Add new test cases (matrix below). Invert the existing `test_canonical_tripwire_matches_generic_encoded_claude_segment` near line 164 so encoded variants of bare `/.claude/` no longer match content. Update `to_dict()` test if any covers the diagnostic record shape. |
| `py/swarm_do/pipeline/tests/test_phase_failure_classifier.py` | Verify `tool_error_kind="canonical_path_leaked"` still propagates through classification for both input and content hits, including a Bash-command input case. Add cases mirroring the new behavior if not already covered. |

### Verification / Validation Commands

```bash
cd swarm-do
PYTHONPATH=py python3 -m unittest swarm_do.pipeline.tests.test_claude_transcript_diagnostics
PYTHONPATH=py python3 -m unittest swarm_do.pipeline.tests.test_phase_failure_classifier
PYTHONPATH=py python3 -m unittest swarm_do.pipeline.tests.test_failure_taxonomy
PYTHONPATH=py python3 -m unittest discover swarm_do.pipeline.tests
```

Required test cases (add to
`tests/test_claude_transcript_diagnostics.py` unless noted):

| ID | Setup | Field role | Expected |
| --- | --- | --- | --- |
| 1 | Tool result content body contains `"plugin_root": "/Users/operator/.claude/plugins/..."` | content (output) | NOT flagged |
| 2 | Tool result content body contains the actual `source_git_top_level` value passed in | content (output) | flagged, `error_kind="canonical_path_leaked"` |
| 3 | `Read` tool_use, `input.file_path = "/Users/x/.claude/projects/<sid>.jsonl"` | path | flagged |
| 4 | `Bash` tool_use, `input.command = "cat ~/.claude/projects/<sid>.jsonl"` | command | flagged, `tool_name="Bash"`, `file_path=None`, excerpt contains the command |
| 5 | `Bash` tool_use, `input.command = "ls /tmp"` | command | NOT flagged |
| 6 | `Read` whose `file_path` is inside the safe-worktree project subdir, tool result body contains the synthetic `/Users/operator/.claude/...` example (case 1 plus path) | path + content | NOT flagged on either side |
| 7 | `Write` tool_use, `input.content` contains synthetic `/Users/operator/.claude/...` example | content (input) | NOT flagged |
| 8 | `Edit` tool_use, `input.old_string` contains synthetic `/Users/operator/.claude/...`, `input.new_string` contains synthetic `/Users/operator/.claude/...` | content (input) | NOT flagged |
| 9 | `MultiEdit` tool_use, `input.edits[0].old_string`/`.new_string` contain synthetic `/Users/operator/.claude/...` | content (input) | NOT flagged |
| 10 | `Grep` tool_use, `input.pattern = "/.claude/"` | content (input) | NOT flagged |
| 11 | `Write` tool_use, `input.content` contains the actual `source_git_top_level` | content (input) | flagged on input side |
| 12 | `Edit` tool_use, `input.old_string` contains the actual `source_git_top_level` | content (input) | flagged on input side |
| 13 | Existing `test_canonical_tripwire_matches_generic_encoded_claude_segment` near line 164 with content `"project=-USERS-OPERATOR--CLAUDE-PLUGINS-SWARM-DO"` and `sensitive_path_patterns=["/.claude/"]` | content (output) | invert: NOT flagged. Replace assertion accordingly. |
| 14 | `_tool_input_fields` directed unit test on a synthetic nested payload covering string, number, list, dict, and `None` leaves | n/a | yields exactly the expected `(field_path, value)` pairs in order |

### Acceptance

- All existing diagnostics tests pass after inversion of the existing generic
  encoded test.
- All 14 new or revised test cases above pass.
- `_tool_input_fields` is covered by the directed unit test (case 14).
- `parse_transcript`, `load_transcript_diagnostics`, and `diagnose_launch`
  retain their public signatures (`sensitive_path_patterns: Iterable[str]`).
- Manual verification: re-prepare and re-launch the ECC adoption run on top
  of this fix; phase 0 reaches `succeeded` instead of
  `canonical_path_leaked_in_tool_result`.

## Phase 2: Sanitize Hard-Coded Local Roots In Tests And Fixtures (complexity: simple, kind: task)

### Objective

After Phase 1 the precise content-side patterns
(`source_project_root`/`source_git_top_level`/`real_repo_root`) still match
on real canonical paths inside tool results — by design. Three committed
files hard-code the developer machine's `source_git_top_level`
(`/Users/example/.dev-marketplaces/example-plugins/swarm-do`),
which means a writer reading them in the safe-worktree would still trip the
detector. Sanitize them so reading them post-fix is benign.

### Current Status

`grep -rn "/Users/<developer>" --include="*.py"` returned three locations
before this fix:

1. `py/swarm_do/pipeline/tests/test_claude_transcript_diagnostics.py:22` — the
   `test_encode_project_path_preserves_leading_dash_and_dot_as_dash` test
   asserts `encode_project_path` of the literal string maps to a specific
   encoded form.
2. `py/swarm_do/pipeline/tests/test_claude_transcript_diagnostics.py:137` — a
   later test uses the same literal as a `source` value passed into
   `parse_transcript`.
3. `py/swarm_do/pipeline/tests/fixtures/refresh_base_legacy_output/refresh-git-base.py:8`
   — a captured legacy helper hard-codes `Path("/Users/<developer>/...")` as
   the repo root example.

### Implementation

1. Replace each literal with a synthetic placeholder that preserves the
   character classes the test exercises but does not match any plausible
   real `source_git_top_level`. Suggested replacement:
   `/Users/example/.dev-marketplaces/example-plugins/swarm-do`. The
   `encode_project_path` test continues to validate that
   `.` → `-`, `/` → `-`, `-` is preserved, and consecutive separators
   collapse properly.
2. Update the asserted expected encoded form in the
   `test_encode_project_path_preserves_leading_dash_and_dot_as_dash` test to
   match the new placeholder.
3. For `refresh-git-base.py`, change the example `repo` line to use
   `Path("<repo-root>")` or `Path.home() / "src" / "swarm-do"` (whichever the
   surrounding fixture intends). This file is captured legacy output; if it
   is checked in solely as a snapshot, ensure the snapshot does not need to
   be re-captured against the literal — verify by running the surrounding
   regen helper if any.
4. Run a final developer-home-path grep over the repo to confirm no
   committed file under `py/`, `docs/`, `schemas/`, or `bin/` retains the
   developer machine path.

### Files

| File | Change |
| --- | --- |
| `py/swarm_do/pipeline/tests/test_claude_transcript_diagnostics.py` | Replace the two literal occurrences (lines 22 and 137) with the synthetic placeholder; update encoded-form assertion accordingly. |
| `py/swarm_do/pipeline/tests/fixtures/refresh_base_legacy_output/refresh-git-base.py` | Replace the hard-coded developer-home repo root with a placeholder that does not match any real `source_git_top_level`. |

### Verification / Validation Commands

```bash
cd swarm-do
grep -rn "/Users/<developer>" --include="*.py" --include="*.md" --include="*.json" --include="*.jsonl" .
# expected output: no committed files outside data/runs/.
PYTHONPATH=py python3 -m unittest swarm_do.pipeline.tests.test_claude_transcript_diagnostics
PYTHONPATH=py python3 -m unittest discover swarm_do.pipeline.tests
```

### Acceptance

- The grep above returns no committed file outside generated `data/runs/`
  trees.
- All tests in `test_claude_transcript_diagnostics.py` pass with the new
  placeholder, including the two affected directly and the
  `parse_transcript`-driven test on line 137.
- The `refresh-git-base.py` legacy fixture continues to round-trip through
  whatever helper produced it, or its snapshot remains valid.

## Phase 3: Reconcile Documentation With New Detector Contract (complexity: simple, kind: docs)

### Objective

Two existing planning documents codify the pre-fix output-side bare-`/.claude/`
matching as part of the launcher hardening contract. Update them so a future
operator reading the docs does not assume the dropped behavior is still
guaranteed.

### Current Status

- `docs/sensitive-path-launcher-hardening-plan.md` line ~824 references the
  "source-tree `/.claude/` spelling" in a way that implies output-side bare
  matching is part of the contract.
- `docs/auditable-worktree-launcher-hardening-plan.md` line ~183 says the
  diagnostic "reports `canonical_path_leaked_in_tool_result` when tool
  results contain the canonical source root or `/.claude/`."
- `docs/auditable-worktree-launcher-hardening-plan.md` line ~378 says
  "adding a `/.claude/` tool-result excerpt emits
  `canonical_path_leaked_in_tool_result`."

### Implementation

1. Re-read each cited section in full context. If the surrounding paragraphs
   make the pre-fix behavior load-bearing for an unrelated argument, leave
   the historical narrative intact and add a one-line clarification noting
   that as of 2026-05-01 the bare `/.claude/` literal is enforced on tool
   inputs (`file_path`, `path`, Bash `command`) only, not on tool result or
   content fields, and that precise canonical patterns
   (`source_project_root`, `source_git_top_level`, `real_repo_root`) remain
   on both sides.
2. If the cited line is a forward-looking acceptance criterion that would now
   fail, rewrite it to match the new contract.
3. Do not change the failure-kind name `canonical_path_leaked_in_tool_result`
   anywhere; the wire contract is preserved even though the trigger is
   tighter.

### Files

| File | Change |
| --- | --- |
| `docs/sensitive-path-launcher-hardening-plan.md` | One-line clarification at the cited section (around line 824) noting the new input-only scope of bare-literal matching. |
| `docs/auditable-worktree-launcher-hardening-plan.md` | Update line ~183 and line ~378 to describe the new contract: bare `/.claude/` is enforced on path/command inputs (including Bash `command`), not on tool result content; precise canonical patterns are enforced on both sides. |

### Verification / Validation Commands

```bash
cd swarm-do
grep -n "/.claude/" docs/sensitive-path-launcher-hardening-plan.md
grep -n "/.claude/" docs/auditable-worktree-launcher-hardening-plan.md
# Spot-check that any remaining mentions are either historical narrative or
# explicitly correct under the new contract.
```

### Acceptance

- The two docs no longer assert output-side bare-literal matching as a
  contract.
- The new contract (bare literal enforced on path/command inputs only,
  precise canonical patterns enforced on both sides) is stated at least once
  in each affected doc.

## Test Strategy

- Unit tests in `tests/test_claude_transcript_diagnostics.py` cover the
  detector boundary cases enumerated in Phase 1's matrix, including the
  `_tool_input_fields` directed unit test and the inversion of the existing
  encoded-content test.
- Unit tests in `tests/test_phase_failure_classifier.py` cover the
  end-to-end propagation of the `canonical_path_leaked_in_tool_result`
  failure_kind from a synthetic transcript through the classifier, including
  a Bash-command input case.
- Full pipeline tests via `python3 -m unittest discover
  swarm_do.pipeline.tests` to catch any unrelated regression after the test
  fixture sanitization in Phase 2.
- Out-of-band verification: re-run the ECC adoption phase-sessions launch
  and observe phase 0 completing, with the Phase 0 example fixture
  (`docs/examples/selftest.ok.json`) unchanged.

## Definition Of Done

- All Phase 1 unit tests above pass; all phases pre-existing in the
  pipeline tests suite continue to pass.
- `swarm-do/bin/swarm permissions check` still reports `OK`.
- `grep -rn "/Users/<developer>" --include="*.py" --include="*.md"
  --include="*.json" --include="*.jsonl" .` returns no committed match
  outside `data/runs/`.
- A re-prepared ECC run gets through phase 0 without
  `canonical_path_leaked_in_tool_result`.
- The two hardening docs no longer codify the dropped output-side bare
  matching as a contract.

## Rollback

Phase 1 is contained in one detector module and its tests; a single-commit
revert restores prior detector behavior. Phase 2 is a self-contained fixture
hygiene change; revert restores the developer-machine-pinned literals.
Phase 3 is documentation only; revert restores the older wording. The
plugin-level effect of reverting Phase 1 is the return of the original false
positive; no data is migrated.

## Risks

- **Bash gap regression risk.** If `_tool_input_fields` misses a tool input
  branch (deeply nested object, non-string-leaf format, list of strings),
  Bash exfiltration could go unflagged. Mitigation: directed unit test
  (case 14) on a synthetic nested payload covering string, number, list,
  dict, and `None` leaves.
- **Field-role map drift.** If a future Claude Code tool adds a path or
  command field not enumerated in the role map, that field will fall through
  to `other` and be unscanned. Mitigation: comment the role map as the
  source of truth and call out additions in any tool-shape change. Add an
  explicit unit test for each role bucket so the mapping is observable.
- **Diagnostic shape change.** Adding optional `field_path` to
  `ToolErrorDiagnostic` is additive; consumers reading `to_dict()` will see
  a new key. Mitigation: keep the existing `file_path` semantics intact;
  mention the new field in any ADR that governs the diagnostic record shape.
- **Output-side relaxation risk.** A canonical leak reaching tool result
  content via a path other than the agent's own input could now go
  undetected. Mitigation: precise patterns (`source_*`, `real_repo_root`)
  remain on both sides, so any tool result containing the actual canonical
  source root still flags. The bare `/.claude/` literal and its variants are
  the only thing dropped from content-side matching, and Bash plus
  content-bearing input scanning replaces its protection surface.

## Open Questions

- Does any external (non-pipeline) caller of `load_transcript_diagnostics`
  or `diagnose_launch` exist outside the
  `swarm-do/py/swarm_do/pipeline/` package? An implementation-time grep
  will confirm; if found, the public signature must remain `Iterable[str]`
  via `_coerce_pattern_sets` as described.
- Should the Grep `pattern` field be classified as `command` instead of
  `content`? Today it is treated as content (because the pattern is
  literally a string the agent wants to find, not a path to access). If
  later a security review concludes Grep can be used to enumerate
  `/.claude/` paths, the role map can move it to `command` without
  changing the rest of the design.
- Should `description` and similar narrative input fields be considered
  `content` or `other`? The plan classifies them as `other` (no scan); a
  team review during implementation should confirm.

## Final Recommendation

Land Phase 1, Phase 2, and Phase 3 together. Phase 1 is the load-bearing
detector fix. Phase 2 removes the secondary trip-hazards that would surface
once Phase 1 makes the precise content-side patterns visible. Phase 3 keeps
the planning documents honest about the new contract. The fixture
`docs/examples/selftest.ok.json` and other Phase 0 examples are deliberately
left unchanged; they are the schema documentation, and the detector now
reads them without overreacting.
