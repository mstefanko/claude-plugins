# Subagent Efficiency Tightening Plan

## Bottom Line

The diagnosis is directionally correct and current enough to act on, but the
main problem is not missing prompt text. The repo already tells several roles to
trust upstream notes. The gap is enforcement: permissions, runtime context
contracts, telemetry, and deterministic decomposition still allow or incentivize
agents to re-open source, over-expand outputs, and serialize work that could be
split safely.

Default strategy: keep `agent-analysis` as the single analysis dialect and make
`trust research` an enforced context policy. Do not create `agent-analysis-fast`
first. Add explicit escalation for source access when research marks gaps as
`[UNVERIFIED]` or a preset opts into `context_policy: source_allowed`.

## Validation Notes

- `agent-analysis` already says to trust research and only open files marked
  `[UNVERIFIED]`, but the same spec allows `Read`, `Grep`, `Glob`, and read-only
  Bash, and also says to read every cited file. That is an internal conflict:
  `role-specs/agent-analysis.md:25`, `role-specs/agent-analysis.md:28`,
  `role-specs/agent-analysis.md:40-43`.
- `agent-clarify` is prompt-strict but permission-loose. The role says no source
  reads or grep, while `permissions/clarify.json` allows `Read` and `Bash(rg:*)`:
  `role-specs/agent-clarify.md:25-28`, `permissions/clarify.json:6-10`.
- Permission coverage is incomplete. `ROLE_NAMES` does not register
  `analysis`, `debug`, `research-merge`, `analysis-judge`, or `docs`, and the
  schema enum is even smaller: `py/swarm_do/pipeline/permissions.py:16-27`,
  `schemas/permissions.schema.json:10-13`.
- Persona size is not the primary issue. `agents/agent-analysis.md` is about
  5 KB / 726 words, but every role load still injects the full role file via
  `bin/load-role.sh:26`.
- `agent-decompose` now owns schema-strict `work_units.v2`, and
  `decompose_phase` has a deterministic artifact path, so analysis should not
  be the canonical work-unit JSON producer when prepare/decompose is active:
  `role-specs/agent-decompose.md:8-30`, `py/swarm_do/pipeline/decompose.py:27-49`.
- Deterministic splitting is still shallow. Complexity uses bullets, file count,
  directory coherence, and keywords, but unit synthesis groups by top-level path
  and chains every split unit behind the previous one:
  `py/swarm_do/pipeline/plan.py:290-308`,
  `py/swarm_do/pipeline/decompose.py:101-110`,
  `py/swarm_do/pipeline/decompose.py:186-201`.
- Writer re-reading is role-induced. The writer must read source before each
  edit, verify APIs before use, and self-reread every changed file:
  `role-specs/agent-writer.md:30-33`, `role-specs/agent-writer.md:91-96`,
  `role-specs/agent-writer.md:104-110`.
- Telemetry is too coarse for the current question. Runs track nullable token
  and tool-call totals, v2 adds unit totals, and observations can record tools
  and file paths, but there is no per-tool category, repeated-read count, or
  first-test position:
  `schemas/telemetry/runs.schema.json:153-181`,
  `schemas/telemetry/runs.v2.schema.json:44-80`,
  `schemas/telemetry/observations.schema.json:26-47`.
- Phase 2 of the prepare-gate plan is structurally large: lint rules, grammar,
  canonical writer, prepare orchestration, CLI, and tests across five files:
  `docs/swarmdaddy-prepare-gate-execution-plan.md:230-313`.

## Target Contracts

### Analysis Context Policy

Default:

```yaml
agents:
  - role: agent-analysis
    context_policy: notes_plus_unverified
    output_budget:
      max_words: 800
```

Semantics:

- Inputs are phase text, research notes, clarify notes, accepted decompose
  summary, and any explicit `[UNVERIFIED]` items.
- No source search by default: no `Grep`, no `Glob`, no `rg`, no broad read-only
  Bash.
- If research is sparse, analysis returns `NEEDS_RESEARCH` with exact gaps and
  desired file/topic scopes.
- Source reads are allowed only for `[UNVERIFIED]` items with a small budget, or
  when the stage explicitly sets `context_policy: source_allowed`.
- Analysis output is approach, risks, assumptions, tests, and handoff notes.
  `agent-decompose` or deterministic helpers own `work_units.v2` when enabled.

### Research Output Contract

Research must become analysis-ready:

- Use stable claim IDs such as `R-12`.
- Each claim includes source file:line evidence or a clear `[UNVERIFIED]` gap.
- Evidence windows are summarized, not pasted wholesale.
- Mark whether analysis needs the claim: `analysis_need: required | helpful |
  not_needed`.
- Record unresolved gaps as specific follow-up reads, not vague uncertainty.

### Writer Context Contract

Writer should still verify before editing, but with bounded trust:

- Read upstream notes and each `allowed_files` entry once before editing.
- Trust upstream anchors for orientation.
- Re-read after editing that file, on unparseable anchors, after test failures,
  or when review feedback cites a line.
- Return `NEEDS_CONTEXT` if the allowed scope is wrong.
- Do not spend model time producing deterministic diff stats or blocked-file
  reports that a post-writer helper can compute.

## Work Plan

### 1. Add Transcript and Tool-Call Analyzer

Build a deterministic analyzer before changing behavior so the team can prove
which optimizations matter.

Report per role, stage, and work unit:

- tool calls by category: read, search, shell, edit, test, git status/diff
- source-read count and repeated reads by file
- read-before-edit ratio
- first-test position
- git status/diff churn
- input tokens, cached input tokens, output tokens, prompt bundle size
- output bytes and wall-clock time
- handoffs, `NEEDS_CONTEXT`, review failures, and spec mismatches

Implementation shape:

- Prefer a new transcript summary command or telemetry subcommand over adding
  another model observer.
- Extend `observations.jsonl` or add a sidecar summary with tool category,
  operation, file paths, and work-unit id.
- Update telemetry docs and fixtures so null token/tool values remain allowed
  where the backend cannot observe them.

Acceptance:

- Analyzer runs on existing transcripts or synthetic fixtures.
- It can produce a baseline table for at least 10 real or fixture-backed phases.
- It distinguishes repeated reads from first reads and `rg` source search from
  harmless `bd show` usage.

### 2. Align Permissions with Role Contracts

Add and register permission fragments for:

- `analysis`
- `debug`
- `analysis-judge`
- `research-merge`
- `docs`

Also fix `clarify` so it cannot read source or run `rg`.

Implementation details:

- Extend `ROLE_NAMES` and `schemas/permissions.schema.json`.
- Add permission fragments that match the prompt contract.
- Add drift tests that fail when a registered role lacks a fragment or a
  fragment allows a tool the role explicitly forbids.
- For analysis-like roles, deny source search by default and make source-read
  escalation an explicit context policy rather than a silent permission leak.

Acceptance:

- `swarm permissions check` covers all pipeline roles that have role specs.
- `agent-clarify` cannot receive `Read`, `Grep`, `Glob`, or `Bash(rg:*)`.
- `agent-analysis` and `agent-debug` default to notes plus bounded unverified
  source reads, not unrestricted search.

### 3. Make Analysis Notes-Only by Default

Revise `role-specs/agent-analysis.md` and generated role files so the grounding
rules no longer contradict trust-research behavior.

Changes:

- Replace "Read the actual files you cite" with "Cite research claim IDs and
  their file:line evidence; read source only for `[UNVERIFIED]` escalation."
- Add `NEEDS_RESEARCH` status for missing evidence.
- Cap output to 800 words unless `NEEDS_RESEARCH`.
- Cap assumptions, risks, and tests at five each.
- Remove schema-strict work-unit JSON from normal analysis output when
  prepare/decompose is active.
- Keep one evidence anchor per major claim instead of duplicating file:line
  anchors in every section.

Acceptance:

- Generated `agents/agent-analysis.md` matches the role spec.
- Existing lenses and analysis fan-out still preserve one output dialect.
- Downstream roles still receive enough handoff context to execute.

### 4. Improve Decomposition Heuristics and Parallelism

Teach deterministic decomposition about semantic work clusters, not just
directory prefixes.

Cluster signals:

- phase sections: lint rules, parser/grammar, canonical writer, orchestration,
  CLI, tests, docs
- file target actions: `CREATE`, `EXTEND`, `MODIFY`, `TEST`
- acceptance criteria count and type
- validation commands and expected result scope
- estimated writer budget from `estimate_unit_budget`

Splitting rules:

- Force a split when estimated writer tool calls exceed 40 or acceptance
  criteria exceed 5.
- Parallelize units only when `allowed_files` are disjoint and there is no API
  dependency.
- Emit `depends_on` for semantic dependencies, such as CLI work depending on
  stable parser/writer APIs.
- Stop chaining every split unit by default.

Example for prepare-gate Phase 2:

- `unit-2b`: `plan.py` grammar/lint/canonical writer,
  `prepare.py` orchestration, and direct unit tests.
- `unit-2c`: `cli.py` subparser and CLI tests, depending on `unit-2b` unless
  `unit-2b` first lands a stable stub/API.

Acceptance:

- Phase 2 decomposes into semantic units rather than one broad unit.
- Independent units appear in the same topological layer.
- Dependent units still serialize when they share files or API contracts.
- Budget lint fails oversized units before they reach a writer.

### 5. Move Deterministic Reporting out of Writer

Add a post-writer helper that computes what models currently narrate manually:

- changed files
- diff stat
- blocked-file violations
- validation command results
- test summary
- work-unit budget status

Acceptance:

- Writer output can shrink without losing auditability.
- `spec-review` receives the unit contract, acceptance matrix, changed files,
  and validation summary.
- Blocked-file violations are detected deterministically.

### 6. Gate Downstream Work

Reduce automatic downstream churn:

- Writer receives only the unit contract plus needed context, not the whole
  parent phase when a work unit is active.
- Spec-review checks the unit acceptance matrix and changed files, not unrelated
  parent-phase text.
- Docs runs only when analysis, writer, or diff classification marks
  `doc_impact: true`.
- Review stages receive deterministic post-writer summaries before reading
  source.

Acceptance:

- Default pipeline can skip docs for code-only changes with no doc impact.
- Spec-review no longer re-litigates requirements outside the active unit.
- Review failures can still request source reads when the deterministic summary
  is insufficient.

### 7. Run Controlled Experiments

Run these comparisons after instrumentation lands:

- current decomposition vs semantic decomposition on 10 phases
- prompt-only tightening vs decompose-only tightening
- test-first vs implement-then-test for parser/CLI tasks
- notes-only analysis vs source-allowed analysis on hard phases

Metrics:

- mean and p95 unit tool calls
- wall-clock time
- input/output tokens and cache hit ratio
- repeated source reads
- handoffs and `NEEDS_CONTEXT`
- spec mismatches and review failures
- doc-stage skip rate

Decision rule:

- Promote changes that lower tool calls or wall time without increasing
  `NEEDS_CONTEXT`, spec mismatch, or review failure rates.
- If source-allowed analysis materially reduces downstream failures on hard
  phases, keep it as an explicit escalation preset rather than the default.

## Priority Order

1. Transcript/tool-call analyzer.
2. Permission alignment and clarify fix.
3. Analysis context policy and output cap.
4. Semantic decomposition and dependency rules.
5. Post-writer deterministic report.
6. Downstream docs/spec-review gating.
7. Controlled experiments and preset tuning.

This order keeps the first changes measurable, then closes the largest prompt
and permission mismatch, then addresses the biggest structural lever: unit
boundaries.
