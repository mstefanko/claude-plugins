# Research Output Contract Plan

## Bottom Line

The remaining gap is real: `agent-analysis` now expects research claim IDs, but
`agent-research` and `agent-research-merge` still publish older prose-first
sections. Fix this as a prompt-contract and renderer drift problem first. Do
not build a parser until telemetry shows agents still violate the contract after
the role specs, generated role files, prompt lenses, and tests agree.

## Current Evidence

- `role-specs/agent-analysis.md` already tells analysis to cite research claim
  IDs and return `NEEDS_RESEARCH` when required evidence is missing.
- `role-specs/agent-research.md` still renders `Relevant Files`,
  `Existing Patterns`, `Raw Notes`, and `Sources` as the primary output shape.
- `role-specs/agent-research-merge.md` still emits synthesized prose sections
  and cites sub-research issues rather than stable source claim IDs.
- `py/swarm_do/pipeline/catalog.py` still defines the research lens contract
  around the old sections.
- `roles/agent-research/variants/*.md` still tell research lenses to emphasize
  old sections such as `Relevant Files`, `Raw Notes`, and `Sources`.

## Decision

Use lightweight Markdown claim records. The format stays readable in Beads
notes, gives analysis stable anchors, and remains easy for humans to repair.
Every code claim must carry a stable ID, an `analysis_need` value, verification
state, and either evidence or a follow-up read.

Senior review update: all work items below remain valid after checking the
current role specs, generated agent files, prompt lens catalog, lens overlays,
and focused tests. Tighten the implementation in two places:

- Analysis must treat claim IDs as the only valid source for required
  research-derived code evidence. Legacy prose sections may provide orientation,
  but not required evidence.
- Drift tests should cover both generated role text and prompt-lens overlays,
  because the role renderer is pass-through and the catalog contract is the
  executable metadata used by the TUI/pipeline composer.

Example:

```markdown
### Research Claims

- R-001 [required] [VERIFIED] The pipeline catalog still defines the research
  output contract around old prose sections.
  analysis_need: required
  Evidence: py/swarm_do/pipeline/catalog.py:156
  Notes: Research lenses inherit a section contract that would conflict with
  claim-first role output.

- R-002 [helpful] [UNVERIFIED] The generated agent files may drift after the
  role spec changes.
  analysis_need: helpful
  Follow-up: run `PYTHONPATH=py python3 -m swarm_do.roles gen --check` and
  inspect any drift.
```

For synthesized research, use `RM-###` IDs and preserve source provenance:

```markdown
### Research Claims

- RM-001 [required] [VERIFIED] Research variants still reinforce the older
  section contract.
  analysis_need: required
  Sources: mstefanko-plugins-abc/R-003, mstefanko-plugins-def/R-002
  Evidence: roles/agent-research/variants/codebase-map.md:7
  Notes: Merge claims cite source issue IDs plus source claim IDs, not just
  prose summaries.
```

## Work Breakdown

### 1. Update `role-specs/agent-research.md`

Add an `Analysis-Ready Claim Contract` section.

Require every code claim to include:

- stable ID: `R-###`
- `analysis_need: required | helpful | not_needed`
- verification marker: `[VERIFIED] | [UNVERIFIED]`
- `Evidence:` with file:line anchors or `Follow-up:` with a specific read
- short `Notes:` instead of pasted source windows

Replace the current generic output template with:

- `Research Claims`
- `Gaps / Follow-up Reads`
- `Relevant Files`
- `Sources`
- `Status: COMPLETE | NEEDS_INPUT`

Keep `Relevant Files` as a compact index, not the main evidence carrier.

### 2. Update `role-specs/agent-research-merge.md`

Require merged claims with `RM-###` IDs.

For each merged claim:

- preserve source provenance as `<sub-issue-id>/R-###`
- use `analysis_need: required | helpful | not_needed`
- keep conflicts and gaps as explicit claim records
- cite file:line only when the merge agent directly reads source for an
  `[UNVERIFIED]` item

Avoid prose-only `Conflicting Findings` and `Gaps` sections; analysis should be
able to cite every important synthesis point by claim ID.

### 3. Tighten `role-specs/agent-analysis.md`

Make the current expectation explicit:

- cite `R-###` or `RM-###` claims for every research-derived code claim
- if required evidence lacks claim IDs, return `NEEDS_RESEARCH`
- do not silently mine old prose sections such as `Existing Patterns`,
  `Constraints`, `Prior Solutions`, `Raw Notes`, or prose-only merge sections
  for required evidence

This is a small clarification because analysis already has the notes-only
policy and `NEEDS_RESEARCH` behavior.

### 4. Update Prompt Lens Contracts

Update `py/swarm_do/pipeline/catalog.py` so `RESEARCH_CONTRACT` names the new
claim-first sections:

- `Research Claims`
- `Gaps / Follow-up Reads`
- `Relevant Files`
- `Sources`

Update `roles/agent-research/variants/*.md` so each lens biases claim content
instead of old section layout:

- `codebase-map`: produce more `[required]` and `[helpful]` file-map claims;
  keep `Relevant Files` as an index.
- `risk-discovery`: tag risk and constraint claims inside `Research Claims`;
  do not rely on `Raw Notes`.
- `prior-art-search`: record prior-art claims and memory/doc sources as claim
  evidence or source entries.

Add a catalog or variant test that fails if research lenses require removed
sections such as `Raw Notes` or `Existing Patterns`.

Also assert the research contract section tuple directly. The `OutputContract`
object is displayed in composer/TUI surfaces, so a contract regression can occur
without any role renderer drift.

### 5. Regenerate Role Files

Run:

```bash
PYTHONPATH=py python3 -m swarm_do.roles gen --write
```

Expected generated files:

- `agents/agent-research.md`
- `agents/agent-research-merge.md`
- `agents/agent-analysis.md`

Other generated role files should not change unless their specs changed.

### 6. Add Drift Tests

Extend `py/swarm_do/roles/tests/test_renderers.py` with assertions that rendered
research roles mention:

- `R-001`
- `analysis_need`
- `VERIFIED`
- `UNVERIFIED`
- `Gaps / Follow-up Reads`
- `Follow-up:`

Add a merge-role test for:

- `RM-001`
- source claim provenance such as `<sub-issue-id>/R-###`
- conflicts and gaps represented as claim records

Extend `py/swarm_do/pipeline/tests/test_catalog.py` or add a nearby catalog
test so the prompt-lens contract cannot drift back to removed section names.

### 7. Validate

Run the focused checks:

```bash
PYTHONPATH=py python3 -m swarm_do.roles gen --check
PYTHONPATH=py python3 -m unittest py.swarm_do.roles.tests.test_renderers
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_catalog
```

Optionally run the broader roles and permissions suites if the implementation
touches permissions or shared role-loading behavior.

## Acceptance Criteria

- `agent-research` outputs claim records that analysis can cite directly.
- `agent-research-merge` outputs `RM-###` records with source claim provenance.
- `agent-analysis` stops with `NEEDS_RESEARCH` when required research evidence
  lacks claim IDs.
- Generated `agents/*.md` files match `role-specs/*.md`.
- Research prompt lenses and catalog metadata no longer require the old generic
  prose sections.
- Focused renderer and catalog tests pass.

## Rejected Alternative

A schema or parser for research notes would be more enforceable, but it is too
heavy for this step. The immediate failure is contract drift: analysis already
expects stable claim IDs, while research still emits prose-first notes. Fix the
contract and drift tests first, then add parser enforcement later only if
telemetry shows agents continue to drift.
