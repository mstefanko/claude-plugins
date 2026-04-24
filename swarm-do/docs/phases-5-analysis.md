# Phase 5 — Role Spec Unification: Work Breakdown

## Overview

Collapse the dual `agents/` + `roles/*/shared.md` trees into a single canonical
`role-specs/` source with generated outputs. Rename the Phase-0 codex-review persona
so it no longer collides with the pipeline reviewer role.

Complexity: moderate-refactor. 15 role-specs total.

---

## Pinned Decisions

### D1 — Role-spec frontmatter shape

Every `role-specs/agent-<name>.md` starts with a YAML block:

```
---
name: agent-<name>
description: <one-line description matching Task tool dropdown>
consumers:
  - agents
  # optionally:
  - roles-shared
---
<role body>
```

- `consumers: ["agents"]` only — 10 agents-only roles + the 1 new phase0 spec = 11 specs
- `consumers: ["agents", "roles-shared"]` — 4 roles that also have `roles/<name>/shared.md` = 4 specs
- Total: 15 specs (14 existing + 1 new for the phase0 split)

### D2 — Generated file stamp

First line of every generated file, verbatim:

```
<!-- generated from role-specs/agent-<name>.md — do not edit; run `python3 -m swarm_do.roles gen --write` to update -->
```

Followed by a blank line, then the role body. Every rendered file ends with exactly one trailing newline.

### D3 — Codex-review split: content sources of truth

| Spec file | Source of body text | Generator targets |
|---|---|---|
| `role-specs/agent-codex-review.md` | CURRENT `roles/agent-codex-review/shared.md` body (pipeline reviewer) | `agents/agent-codex-review.md` AND `roles/agent-codex-review/shared.md` |
| `role-specs/agent-codex-review-phase0.md` | CURRENT `agents/agent-codex-review.md` body (Phase-0 blinded adjudication persona) | `agents/agent-codex-review-phase0.md` only |

Post-phase-5: `agents/agent-codex-review.md` contains the pipeline persona (generated).
`agents/agent-codex-review-phase0.md` is new (generated from phase0 spec).

`bin/codex-review-phase` lines 19 AND 108 reference the old path — writer greps for both
string instances and updates each to `agent-codex-review-phase0.md`. Do not rely on a
fixed line number; the actual count may drift.

### D3a — Preserved hand-authored overlays (generator must not emit)

Eight files stay hand-authored, generator does NOT touch them:
- `roles/agent-codex-review/{claude,codex}.md`
- `roles/agent-review/{claude,codex}.md`
- `roles/agent-spec-review/{claude,codex}.md`
- `roles/agent-writer/{claude,codex}.md`

### D4 — spec.py API

```python
@dataclass(frozen=True)
class RoleSpec:
    name: str           # e.g. "agent-writer"
    description: str    # one-liner
    consumers: list[str]  # subset of {"agents", "roles-shared"}
    body_text: str      # role body verbatim (no frontmatter)

def load(path: Path) -> RoleSpec: ...
def validate(spec: RoleSpec) -> None: ...   # raises ValueError on bad shape
def parse_markdown(text: str) -> RoleSpec: ...  # used for roundtrip tests
```

Frontmatter parser: hand-written (NO pyyaml — third-party deps are banned). Handles only
the minimal shape: `---\nkey: value\nkey: [a, b]\n---\n`. Regex or line-split is fine;
raise `ValueError` with a descriptive message on any unsupported shape.

### D5 — render.py API

```python
def to_agents_md(spec: RoleSpec) -> str: ...    # stamp + blank line + body + trailing \n
def to_shared_md(spec: RoleSpec) -> str: ...    # identical output contract
```

Body is copied verbatim across both consumers — the `codex.md` / `claude.md` overlays
carry backend-specific phrasing. Neither renderer strips nor adds anything to the body.

### D6 — cli.py subcommands

```
python3 -m swarm_do.roles gen --write         # regenerate all targets, write to disk
python3 -m swarm_do.roles gen --check         # diff; exit 1 on drift, print diff
python3 -m swarm_do.roles gen readme-section  # STUB only (Phase 6 scope)
python3 -m swarm_do.roles list                # enumerate role-specs
```

`gen --write` overwrites generated files only. Before overwriting, verify the existing
file either (a) carries the stamp or (b) is a new file that doesn't exist yet. Abort if
a file exists without the stamp (would be overwriting a hand-authored file — safety guard).

### D7 — variants.py

Placeholder only:

```python
"""Role variant support. Phase 10g scope — not implemented."""
```

### D8 — Test matrix

| File | What it tests |
|---|---|
| `tests/__init__.py` | empty |
| `tests/test_spec_parser.py` | parse valid spec; raise on malformed frontmatter; raise on name-filename mismatch |
| `tests/test_renderers.py` | stamp present in line 1; body preserved verbatim; trailing newline; blank line after stamp |
| `tests/test_roundtrip.py` | for every real role-spec: `parse_markdown(strip_stamp(to_agents_md(load(path))))` yields equivalent `RoleSpec`; contract-equivalent, not byte-equal |

`test_roundtrip.py` implementation note: `parse_markdown` receives the rendered output
with the stamp stripped (the stamp is not valid frontmatter — strip the first two lines
before passing to the parser in the roundtrip path).

---

## Work Steps (Commit Boundaries)

### Commit 1 — Scaffold + role-specs + package skeleton

**Files to create:**

```
swarm-do/role-specs/          (new directory)
  agent-analysis.md
  agent-clarify.md
  agent-codex-review.md         ← body from roles/agent-codex-review/shared.md
  agent-codex-review-phase0.md  ← body from agents/agent-codex-review.md (NEW)
  agent-deployment.md
  agent-devops.md
  agent-orchestrator.md
  agent-planner.md
  agent-qa.md
  agent-refactor.md
  agent-research.md
  agent-review.md
  agent-spec-review.md
  agent-writer.md
  agent-<15th>.md               ← confirm name from research bead's exact agent list
```

Each file: frontmatter block (name, description, consumers) + role body verbatim from
current canonical source (see source-of-truth table in D3 for the two codex-review
entries; remaining 12/13 use their existing `agents/agent-<name>.md` body).

```
swarm-do/py/swarm_do/roles/
  __init__.py
  spec.py        (skeleton — stubs only, classes defined, functions raise NotImplemented)
  render.py      (skeleton)
  cli.py         (skeleton)
  variants.py    (placeholder docstring)
  tests/
    __init__.py
    test_spec_parser.py   (stubs — all tests marked xfail or skipped)
    test_renderers.py     (stubs)
    test_roundtrip.py     (stubs)
```

Commit message: `feat(swarm-do): phase-5 role-specs scaffold and package skeleton`

---

### Commit 2 — Generator implementation + tests passing

Implement in order (each depends on the previous):

1. **spec.py**: hand-written frontmatter parser, `load`, `validate`, `parse_markdown`.
2. **render.py**: `to_agents_md`, `to_shared_md` — stamp + blank line + body + `\n`.
3. **cli.py**: `gen --write`, `gen --check` (full), `list` (full), `gen readme-section` (stub prints "not implemented").
4. **Tests**: fill in all three test files; all tests must pass.

Verification gate before committing:
```
cd swarm-do/py && python3 -m pytest tests/ -v   # must be green
python3 -m swarm_do.roles list                  # prints 15 entries
python3 -m swarm_do.roles gen --check           # EXPECTED to exit 1 (stamp missing on disk)
```

Commit message: `feat(swarm-do): phase-5 roles generator, spec parser, renderers, tests`

---

### Commit 3 — Run gen --write + commit regenerated outputs

```
cd swarm-do/py && python3 -m swarm_do.roles gen --write
python3 -m swarm_do.roles gen --check   # must exit 0
```

Verify:
- `agents/agent-codex-review-phase0.md` created (new file)
- `agents/agent-codex-review.md` now contains pipeline reviewer body with stamp
- All `roles/<role>/shared.md` files for the 4 dual-consumer roles carry the stamp
- `bin/load-role.sh agent-codex-review` returns non-empty (pipeline content)
- `bin/hash-bundle.sh agent-codex-review claude` runs without error

Stage all modified/created generated files and all role-specs.

Commit message: `feat(swarm-do): phase-5 run gen --write; stamp all generated outputs`

---

### Commit 4 — bin/codex-review-phase update

In `bin/codex-review-phase`, grep for every occurrence of `agent-codex-review` that
references the old phase0 persona (lines 19 and ~108; exact count may differ — grep both).
Replace each with `agent-codex-review-phase0`.

Dry-run verification (if Codex CLI absent):
```
grep -n "agent-codex-review" swarm-do/bin/codex-review-phase
# confirm only the non-phase0 reference (the pipeline reviewer) remains, if any
```

Functional verification (if CLI present):
```
bin/codex-review-phase agent-codex-review-phase0 <test-args>
```

Commit message: `fix(swarm-do): phase-5 update codex-review-phase to phase0 persona path`

---

## Out of Scope (explicit)

- `gen readme-section` full implementation → Phase 6
- `variants.py` population → Phase 10g
- `claude.md` / `codex.md` overlay generation → stays hand-authored, never generated
- Any changes to `roles/*/claude.md` or `roles/*/codex.md` content
- New roles beyond the 15 defined above

---

## Definition of Done

- [ ] `python3 -m swarm_do.roles gen --check` exits 0
- [ ] `python3 -m pytest swarm-do/py/tests/ -v` all green
- [ ] `agents/agent-codex-review-phase0.md` exists and carries stamp
- [ ] `agents/agent-codex-review.md` carries stamp and contains pipeline persona
- [ ] All 4 `roles/<role>/shared.md` generated files carry stamp
- [ ] 8 hand-authored overlays (claude.md / codex.md) unchanged
- [ ] `bin/codex-review-phase` references `agent-codex-review-phase0` at former phase0 call sites
- [ ] `bin/load-role.sh agent-codex-review` returns pipeline persona content
- [ ] No orphaned files under `agents/` or `roles/` without a corresponding role-spec
- [ ] `role-specs/` contains exactly 15 files

---

## Compatibility Boundaries

- Python stdlib only — no pyyaml, no third-party deps
- The package lives at `swarm-do/py/swarm_do/roles/` — no changes to existing package structure elsewhere in `py/`
- Generated files are overwritten only when the stamp is present OR the file is new — safety guard prevents clobbering hand-authored content
- `bin/codex-review-phase` is a shell script; grep-and-replace is safe; do not refactor surrounding logic
