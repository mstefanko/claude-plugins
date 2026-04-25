# Lens Catalog v1 Research

Date: 2026-04-25
Status: Research note (not production prose). Drives Phase 1 catalog metadata,
Phase 3 lens controls, and the Phase 5 single-agent lens schema decision.

This document answers the questions posed in the lens-catalog research brief
against the implementation plan at
`swarm-do/docs/pipeline-composer-implementation-plan.md`. It does **not** edit
runtime code, schemas, or variant files.

---

## A. Existing Repo Conventions

### A1. How are existing variants structured?

The only fan-out variants that exist today live in
`swarm-do/roles/agent-analysis/variants/`:

- `explorer-a.md` (Architectural Risk) — `swarm-do/roles/agent-analysis/variants/explorer-a.md:1-6`
- `explorer-b.md` (API Contract Stability) — `swarm-do/roles/agent-analysis/variants/explorer-b.md:1-6`
- `explorer-c.md` (Data And State Implications) — `swarm-do/roles/agent-analysis/variants/explorer-c.md:1-6`

Each is **2–4 lines long** with a fixed shape:

1. H1 title naming the lens (`# Explorer A — Architectural Risk`).
2. One sentence: "Apply the normal `agent-analysis` contract, but bias the
   investigation toward <topic axes>."
3. Closing assertion: "Do not change the output schema, required sections, or
   downstream handoff format."

These are **rubric overlays**, not role rewrites. They explicitly preserve the
role's output contract (Assumptions / Recommended Approach / Why Not / Work
Breakdown / Risks / Out of Scope / Test Coverage Needed / Bounded Work Units —
see `swarm-do/role-specs/agent-analysis.md:60-103`). The novelty is only the
investigation bias.

**Implication for v1 lens specs:** every prompt overlay sketch must (a) cite the
host role's existing output contract by section name, (b) modify *what to look
for*, not *what to emit*, and (c) close with the explicit "do not change the
output schema" guardrail. Anything that adds new sections or removes existing
ones is a role redefinition, not a lens, and belongs in a v2 design discussion.

### A2. Role-vs-variant boundary: compose, override, or replace?

Variants **compose** with the role contract. Two pieces of evidence:

- `swarm-do/skills/swarm-do/SKILL.md:132` — "For `variant: prompt_variants`,
  load the corresponding file from `roles/<role>/variants/<name>.md` and
  include it as an additive overlay."
- `swarm-do/docs/plan.md:2367` — "additive overlays on `shared.md` differing in
  prompt framing... without changing contract."

The fan-out branch issue gets the role's `agents/<role>.md` body **plus** the
variant body appended. The variant cannot remove sections from the role; it can
only add bias text. Validation only checks file existence
(`variant_existence_errors`, `validation.py:703-716`) — there is no schema
check that the variant preserves the role contract. That guardrail lives in
the variant prose itself. v1 lenses must keep the same discipline.

### A3. What stage kinds and roles can load a variant today?

[VERIFIED] **Only `fan_out` stages with `variant: prompt_variants`** can load
variants today. Evidence:

- `swarm-do/py/swarm_do/pipeline/validation.py:316-321` — `variant` must be one
  of `same`, `prompt_variants`, `models`. Only `prompt_variants` consumes
  the `variants:` array.
- `swarm-do/py/swarm_do/pipeline/validation.py:703-716` —
  `variant_existence_errors` only walks `fan_out` stages with
  `variant == "prompt_variants"`.
- `swarm-do/schemas/pipeline.schema.json:37-50` — the `agents[*]` agent object
  has only `role`, `backend`, `model`, `effort`, `route`. No `lens` or
  `variant` field. `additionalProperties: false` rejects anything else.

Normal `agents` stages **cannot** carry a lens until the Phase 5 schema
extension lands. Provider stages cannot carry a prompt variant at all (they
shell out to MCO subprocesses; see `mco_stage.py`). Merge agents
(`merge.agent`) currently take only an agent role string, no variant. This
matches the implementation plan's Phase 3 scope. Any v1 lens that wants
single-agent application is gated on Phase 5 and must be marked
`fan_out_only` for v1.

The fan-out role can be any role whose file exists at
`swarm-do/agents/<role>.md` (`role_existence_errors`,
`validation.py:699-700`). Variants are looked up at
`roles/<role>/variants/<name>.md` (`validation.py:713`). Today only
`agent-analysis` has a `variants/` directory, but nothing in the runtime
forbids creating `roles/agent-research/variants/...`,
`roles/agent-review/variants/...`, etc. — Phase 1 catalog work just needs to
register them.

### A4. Output contracts the lenses must respect

Each role's contract anchors the lens design. Quoting load-bearing structure
from each spec:

- **`agent-research`** (`swarm-do/agents/agent-research.md:136-159`):
  Relevant Files / Existing Patterns / Constraints / Prior Solutions / Raw
  Notes / Sources. Status: `COMPLETE | NEEDS_INPUT`. No verdict, no severity.
- **`agent-analysis`** (`swarm-do/role-specs/agent-analysis.md:60-103`):
  Assumptions (each VERIFIED/UNVERIFIED) / Recommended Approach / Why Not
  <alt> / Work Breakdown / Risks / Out of Scope / Test Coverage Needed /
  optional Bounded Work Units (`work_units.v2`).
- **`agent-review`** (`swarm-do/agents/agent-review.md:54-69`):
  Verdict (`APPROVED | NEEDS_CHANGES`) / Checks Run / Issues Found
  (file:line) / Production Risk.
- **`agent-spec-review`** (`swarm-do/role-specs/agent-spec-review.md:56-89`):
  Verdict (`APPROVED | SPEC_MISMATCH | SPEC_AMBIGUOUS`) / Work Breakdown
  Compliance / Mismatches / Rejection Evidence (JSON array, required) /
  Forwarded to Quality Review.
- **`agent-codex-review`** (`swarm-do/agents/agent-codex-review.md:54-69`):
  Verdict (`APPROVED | BLOCKING_ISSUES_FOUND`) / Findings (max 5, severity
  CRITICAL/WARNING, `duplicate_of_claude` flag).
- **`agent-debug`** (`swarm-do/agents/agent-debug.md:82-113`): root-cause
  format with Reproduction / Call Chain Trace / Root Cause Hypothesis /
  Rejected Alternatives / Work Breakdown (Fix location/Fix/Regression
  test/Defense-in-depth/Blast radius).
- **`agent-decompose`** (`swarm-do/agents/agent-decompose.md:42-54`): JSON-only
  `work_units.v2` artifact. No prose.
- **`agent-clarify`** (`swarm-do/agents/agent-clarify.md:48-65`): Pre-Flight
  Questions / Blockers / Resolved.
- **`agent-research-merge`** (`swarm-do/agents/agent-research-merge.md:50-82`):
  Cross-Cutting Concerns / Conflicting Findings / Gaps / Relevant Files /
  Existing Patterns / Constraints / Sources.

A lens must not change the verdict vocabulary, the JSON shape, or the section
names. It can specify an *evidence shape inside an existing section* (e.g.,
adding tags like `[ARCH-RISK]` inside `Risks`, or requiring threat-tag
annotations inside review `Issues Found`).

---

## B. State of the Art (2025–2026)

### B1. Recent benchmark evidence on persona vs rubric effects

- **Rubric Is All You Need** (ACM ICER 2025) makes the strongest 2025-era
  case that **question-specific (task-specific) rubrics outperform
  question-agnostic generic rubrics** in LLM-based code evaluation:
  https://dl.acm.org/doi/10.1145/3702652.3744220 . The result is on
  programming-feedback grading, not full code review, but the structural claim
  — narrow rubric beats broad rubric — is the most relevant new evidence.
- **PersonaGym** (EMNLP Findings 2025) measures persona-consistent behavior
  with task-specific dynamic rubrics scored by an expert-curated rubric, and
  shows persona behavior is most reliably evaluated when the rubric is
  per-task: https://aclanthology.org/2025.findings-emnlp.368.pdf . Confirms
  the cautious 2024 stance and pushes it further: generic role labels alone
  are unstable test subjects.
- **Persona Non Grata** (arXiv 2026 preprint, verified as
  `arXiv:2604.11120`, submitted 2026-04-13 and revised 2026-04-14) shows that
  prompt-based persona evals
  miss vulnerabilities that activation-steered persona evals catch — meaning
  prompt-only personas have *partial* effect on model behavior:
  https://arxiv.org/html/2604.11120v1 . Read as: prompt-only lens overlays do
  shift behavior, but the shift is shallower than a full persona swap. Treat as
  supporting context only; it is too new to carry v1 design decisions.

### B2. Fine-grained task lenses vs broad role personas

The 2025 evidence (Rubric Is All You Need, PersonaGym) and the older anchors
the user already cited (Hu and Collier 2024, Zheng et al. 2024) point in the
same direction: **narrow task/criterion rubrics > broad role labels**. There
is no 2025–2026 paper I found that directly contradicts this for code-review
or design tasks. The plan's bias toward task lenses (`architecture-risk`,
`api-contract`) over role personas ("senior architect") is supported.

### B3. Single-agent lens overlays vs fan-out + merge

- **Towards a science of scaling agent systems** (Google Research, 2026)
  reports that *independent* multi-agent systems amplify errors 17.2× without
  orchestration, but centralized fan-out + orchestrator setups contain
  amplification to 4.4×:
  https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/
  . The merge-stage architecture in swarm-do (`agent-analysis-judge`,
  `agent-research-merge`) is the relevant structure; it is exactly what the
  research recommends.
- The same study and the **Multi-Agent Trap** (Towards Data Science 2025)
  flag the token-economics cost: multi-agent systems use 4–220× more tokens
  than single-agent. This argues *against* defaulting fan-out: only use it
  when (a) tasks are independent, (b) parallel review domains genuinely don't
  need to coordinate, or (c) specialization improves outcomes.
- [UNVERIFIED] I did not find a 2025–2026 study that isolates **single-agent
  lens overlays on Claude 4.x / GPT-5.x** specifically vs fan-out + merge on
  the same backbone with a controlled rubric. The closest evidence is
  PersonaGym, which measures persona consistency, not implementation outcome
  quality.

**Implication:** v1 should keep `fan_out_only` for any lens whose value comes
from *contrast across siblings* (architecture vs API-contract vs
data/state). Single-agent application is acceptable in Phase 5 only for
lenses whose value is *focusing one agent's attention*, not contrast.

### B4. Stacked lenses

No 2025–2026 paper I located directly measures prompt-stack conflict for
multi-overlay rubrics on a single agent. The best signal is indirect:
*Rubric Is All You Need* shows that even one well-targeted rubric beats a
broad rubric — implying the marginal value of a second overlay is uncertain
and is at risk of diluting the first. The plan's "singular `lens` for v1" is
defensible. The 2025 LLM system-prompt observations
(https://gwern.net/system-prompts-2025) flag that long stacked instruction
text often produces ordering effects and instruction collisions on production
LLMs, which is consistent with the cautious stance.

### B5. Structured rubrics vs free-form persona prompts

Strong support: Rubric Is All You Need (2025), PersonaGym (2025), and the
older anchors all favor structured rubrics. v1 lenses should ship as
**rubric overlays first, persona flavor second**. The current
`explorer-a/b/c.md` precedent already does this — the variant gives an
investigation bias (rubric), not a persona description.

### B6. Cross-model review evidence

- **Secondary model-comparison context, not load-bearing design evidence**
  (https://atoms.dev/blog/2025-llm-review-gpt-5-2-gemini-3-pro-claude-4-5)
  reports that GPT-5.2 and Gemini 3 Pro lead on raw reasoning and long-horizon
  tasks while Claude 4.5 leads on agent stability/auditability. This is
  directionally consistent with the existing `agent-codex-review` lane, but it
  is not primary research and should not be used as a plan citation.
- This is **not** a "lens" in the same sense — it is a *route choice* the
  runtime already supports through `agent.backend/model/effort` overrides
  and `fan_out.variant: models` (see `hybrid-review.yaml:24-31`). v1 should
  *not* model cross-model review as a prompt lens. v1 should model
  `agent-codex-review` as a separate role with its own review-only mode and
  let route lenses do the cross-model wiring.

---

## C. v1 Catalog

Convention used below:

- "Mode" maps to runtime capability: `fan_out_only` (Phase 3 today),
  `single_agent` (gated on Phase 5), `review_only` (used as an extra review
  stage role, not a variant overlay), `provider_evidence` (provider stages).
- "Conflicts with" lists lenses that should not appear in the same fan-out
  `variants:` array (would produce overlapping coverage and a degenerate
  merge) or stack on a single agent (Phase 5).
- "Stack-safe with" is empty for v1 — singular lens stance per plan §136 and
  Phase 5. Listed only when there is a defensible reason to revisit later.
- "Output contract delta" cites the host role's existing section names.

### Decisions on the candidate list

| Candidate | v1 verdict | Rationale |
| --- | --- | --- |
| `architecture-risk` | KEEP | Maps directly to `explorer-a.md`. Already proven. |
| `api-contract` | KEEP | Maps directly to `explorer-b.md`. Already proven. |
| `state-data` | KEEP (rename from "data/state") | Maps to `explorer-c.md`. The plan called this `state/data`; canonical id `state-data`. |
| `ux-flow` | DEFER to v2 | UX rarely surfaces in repo-resident swarm-do tasks; the agent-analysis contract has no UX-output slot, and the runtime cannot reach Figma/screenshots. Re-examine when a frontend-design integration ships. |
| `security-threat-model` | KEEP | High-value separable rubric for analysis fan-out and review fan-out. Maps cleanly into Risks / Issues Found sections. |
| `performance-review` | KEEP | High-value separable rubric for review fan-out. Maps cleanly into Issues Found / Production Risk. |
| `edge-case-review` | KEEP | High-value review rubric. Already conceptually adjacent to agent-codex-review's narrow focus; lens version is for primary `agent-review`. |
| `prior-art-search` | KEEP | High-value research lens; maps to Existing Patterns + Prior Solutions. |
| `codebase-map` | KEEP | High-value research lens; maps to Relevant Files + Existing Patterns + Sources. |
| `risk-discovery` | KEEP | High-value research lens; maps to Constraints + Raw Notes; complements analysis's Risks. |

Additional lenses proposed below (D&E):
`correctness-rubric`, `migration-blast-radius`, `mco-evidence` (provider
lens), `adversarial-review` (deferred — see §C "additional lenses").

### Spec entries

#### lens id: `architecture-risk`

- **Label**: Architecture Risk
- **Category**: task-rubric
- **Compatible roles**: `agent-analysis`
- **Compatible stage kinds**: `fan_out`
- **Mode**: `fan_out_only` (single_agent eligible after Phase 5)
- **Conflicts with**: none (it pairs with `api-contract` and `state-data` in
  the canonical ultra-plan triad)
- **Stack-safe with**: none for v1
- **Output contract delta**: No new sections. Inside `### Risks`, every entry
  must carry `[ARCH-RISK]` tag plus reversibility note ("reversible / one-way
  door"). Inside `### Why Not <alternative>`, name the architectural
  alternative explicitly. Refers to host contract at
  `role-specs/agent-analysis.md:60-103`.
- **Merge expectation**: `agent-analysis-judge` should reconcile by selecting
  the recommendation whose architectural-risk inventory is most concrete and
  whose reversibility annotations are best supported. If two analysts
  disagree on reversibility, the merge must surface the disagreement, not
  hide it.
- **Safety notes**: none.
- **Evaluation tags**: `category=task-rubric`, `axis=architecture`,
  `host=agent-analysis`, `mode=fan_out`, `signal=reversibility-density`.
- **Prompt overlay sketch**:
  ```
  # Architecture Risk — analysis lens overlay

  Apply the normal agent-analysis contract from role-specs/agent-analysis.md.
  Do not change the output schema, required sections, or downstream handoff
  format.

  Bias your investigation toward architectural coupling, reversibility,
  migration risk, and failure modes that would make the writer's
  implementation expensive to unwind. Specifically:

  - In `### Assumptions`, surface every assumption that, if wrong, forces a
    schema migration, a rollout coordinator change, or a public-API rename.
  - In `### Recommended Approach`, lead with the *reversibility* of the
    proposed change and the cost of undoing it 6 months from now if the
    requirement shifts.
  - In `### Why Not <alternative>`, name a genuinely architectural rival
    (different module boundary, different layering, different integration
    point) — not a parameter tweak.
  - In `### Risks`, prefix every risk with `[ARCH-RISK]` and annotate each
    one as `reversible` or `one-way-door`.
  - In `### Out of Scope`, explicitly list architectural axes the change
    deliberately does NOT touch (so the writer cannot accidentally widen
    blast radius).

  Do not invent or rename sections. Do not relax the citation requirements
  in `### Assumptions`. The merge agent (`agent-analysis-judge`) will
  contrast your output against sibling analysts focused on API contract
  stability and state/data implications; your value is depth on the
  architectural axis only.
  ```
- **Why this lens**: The strongest evidence for swarm-do's existing fan-out
  pattern (ultra-plan). Without an architecture-biased analyst, plan reviews
  consistently undervalue reversibility — the most expensive class of
  mistakes to undo post-merge.

#### lens id: `api-contract`

- **Label**: API Contract Stability
- **Category**: task-rubric
- **Compatible roles**: `agent-analysis`, `agent-review`
- **Compatible stage kinds**: `fan_out`
- **Mode**: `fan_out_only`
- **Conflicts with**: none
- **Stack-safe with**: none for v1
- **Output contract delta**: No new sections. Inside `### Risks` (analysis)
  or `### Issues Found` (review), tag entries with `[API-BREAK]` or
  `[API-COMPAT]` and cite the affected interface (file:line of the
  function/CLI flag/schema field). For analysis, `### Test Coverage Needed`
  must explicitly call out compatibility tests.
- **Merge expectation**: judge prefers the analyst that names *more concrete
  break vectors with file:line citations*. Disagreements about whether a
  field rename counts as a break must be surfaced, not silenced.
- **Safety notes**: none.
- **Evaluation tags**: `axis=api-compat`, `signal=break-vector-density`.
- **Prompt overlay sketch** (analysis variant):
  ```
  # API Contract Stability — analysis lens overlay

  Apply the normal agent-analysis contract. Do not change the output schema
  or section names.

  Bias your investigation toward public interfaces, CLI flags, file
  formats, schemas, environment variables, and compatibility promises that
  could break existing operators or downstream consumers.

  - In `### Assumptions`, list every assumption about *who depends on* the
    interface you are changing. Mark each VERIFIED (with a grep-anchored
    `file:line`) or UNVERIFIED.
  - In `### Recommended Approach`, lead with the compatibility posture
    (additive / deprecation-with-window / breaking-with-migration) and
    justify the choice.
  - In `### Risks`, tag each entry `[API-BREAK]` (existing callers fail) or
    `[API-COMPAT]` (existing callers continue working but pay a cost) and
    cite the affected `file:line`.
  - In `### Test Coverage Needed`, name the specific compatibility tests
    the writer must add (round-trip, deserialization of old payloads,
    deprecation warning emission).

  Do not invent or rename sections. Do not relax citation requirements.
  ```
- **Why this lens**: API breakage is the second-most-expensive mistake class
  after architecture mistakes; without a dedicated lens, analysts treat
  compatibility as a checklist item rather than a primary axis.

#### lens id: `state-data`

- **Label**: State & Data Implications
- **Category**: task-rubric
- **Compatible roles**: `agent-analysis`
- **Compatible stage kinds**: `fan_out`
- **Mode**: `fan_out_only`
- **Conflicts with**: none
- **Output contract delta**: No new sections. `### Risks` entries tagged
  `[DATA-MIGRATION]` / `[STATE-CORRUPTION]` / `[INDEX]` /
  `[CROSS-RUN-COMPARABILITY]`. `### Test Coverage Needed` lists
  migration/backfill tests and a "reproducibility under prior runs" check.
- **Merge expectation**: judge prefers the analyst whose data-layer plan
  (migrations, backfill, indexes, hash stability) is concrete enough to
  implement.
- **Safety notes**: none.
- **Evaluation tags**: `axis=state-data`, `signal=migration-density`.
- **Prompt overlay sketch**: Same shape as `architecture-risk`. Bias toward
  persistent state, append-only ledgers, hashing, indexes, migration/backfill
  needs, and cross-run comparability. Replaces `explorer-c.md` as the
  canonical id; the existing file becomes the same content with the new
  filename `state-data.md`.
- **Why this lens**: Data and state mistakes are silent and unrecoverable
  past a few release cycles; a dedicated lens forces explicit migration and
  comparability planning.

#### lens id: `ux-flow` — DEFERRED

Defer to v2. Justifications:

- The active swarm-do roles (`agent-analysis`, `agent-review`,
  `agent-research`) operate on repo source files. None has a UX/screenshot
  affordance, and the runtime offers no Playwright/Figma fetch from inside
  these roles.
- The host output contracts have no UX-shaped section. Adding one would be
  a role redefinition, not a lens overlay (violates §A1 above).
- The user's global guidance routes UI work through the
  `frontend-design` skill, which is invoked by writers, not analysis
  fan-outs (`/Users/mstefanko/.claude/CLAUDE.md`).
- Re-examine if/when a UI-aware research role is added. Until then, "UX"
  considerations should live as a checklist line inside `risk-discovery` or
  `architecture-risk`, not as their own lens.

#### lens id: `security-threat-model`

- **Label**: Security Threat Model
- **Category**: task-rubric
- **Compatible roles**: `agent-analysis`, `agent-review`
- **Compatible stage kinds**: `fan_out`
- **Mode**: `fan_out_only`
- **Conflicts with**: none. Pairs naturally with `correctness-rubric` and
  `performance-review` in a review fan-out.
- **Output contract delta**:
  - For `agent-analysis`: every `### Risks` entry tagged with a STRIDE
    category (`[SPOOF]`, `[TAMPER]`, `[REPUDIATION]`, `[INFO-DISCLOSURE]`,
    `[DOS]`, `[ELEVATION]`). `### Recommended Approach` must explicitly
    declare the trust boundary that the change sits across. `### Test
    Coverage Needed` must include negative-input tests at trust boundaries.
  - For `agent-review`: `### Issues Found` entries tagged with the same
    STRIDE labels. `### Production Risk` distinguishes
    "exploitable-today" from "defense-in-depth gap". Keep the verdict
    vocabulary unchanged (`APPROVED | NEEDS_CHANGES`).
- **Merge expectation**: judge prefers concrete attacker-input examples over
  abstract policy claims. Disagreements on whether a path is reachable from
  untrusted input must be surfaced.
- **Safety notes**: **security-sensitive**. The lens MUST NOT instruct the
  agent to *exploit* anything live; it produces threat models and review
  notes only. Every output stays in beads notes; the lens does not unlock
  Edit/Write privileges.
- **Evaluation tags**: `axis=security`, `signal=stride-coverage`,
  `signal=trust-boundary-density`.
- **Prompt overlay sketch** (review variant):
  ```
  # Security Threat Model — review lens overlay

  Apply the normal agent-review contract from agents/agent-review.md. Do
  not change the verdict vocabulary, the section names, or the
  no-edit/no-write rule.

  Bias your review toward security-relevant defects: untrusted input paths,
  trust boundaries, secret handling, authn/authz, deserialization, command
  injection, path traversal, race conditions on security-critical state,
  and dependency CVEs.

  - For each issue in `### Issues Found`, prefix the file:line claim with
    one STRIDE tag: `[SPOOF]`, `[TAMPER]`, `[REPUDIATION]`,
    `[INFO-DISCLOSURE]`, `[DOS]`, or `[ELEVATION]`.
  - In `### Production Risk`, separate `exploitable-today` items from
    `defense-in-depth gaps`.
  - Do not write proof-of-concept exploits. Do not bypass the no-edit
    constraint.
  - Read the actual `file:line`. Pattern-matching against "code that looks
    like it has a CVE" is forbidden — every issue must be confirmed by
    reading source.

  Verdict and section names unchanged. The merge agent will reconcile your
  findings with sibling reviewers focused on correctness, performance, and
  edge cases.
  ```
- **Why this lens**: Generic `agent-review` reliably misses security
  defects because the rubric is breadth-first. A focused threat-model lens
  changes both the lookup direction and the evidence shape, and it is
  directly supported by the 2025 rubric-specificity findings.

#### lens id: `performance-review`

- **Label**: Performance Review
- **Category**: task-rubric
- **Compatible roles**: `agent-review`
- **Compatible stage kinds**: `fan_out`
- **Mode**: `fan_out_only`
- **Conflicts with**: none
- **Output contract delta**: `### Issues Found` tagged
  `[N+1]`/`[O-N2]`/`[ALLOC]`/`[BLOCKING-IO]`/`[CONTENTION]`. `### Production
  Risk` must distinguish "load-tested observable" from "asymptotic concern
  only". Verdict vocabulary unchanged.
- **Merge expectation**: judge prefers reviewers who name a *specific input
  size or call frequency* that triggers the issue, over reviewers who flag
  abstract complexity.
- **Safety notes**: none.
- **Evaluation tags**: `axis=performance`, `signal=trigger-density`.
- **Prompt overlay sketch**: Bias review toward N+1 query patterns,
  unbounded loops, hot paths in newly added code, allocation in tight loops,
  blocking IO inside async paths, lock contention, cache invalidation, and
  unbounded data growth. Tag every issue. Forbid speculative perf concerns
  with no `file:line` and no concrete trigger size.
- **Why this lens**: General reviewers under-flag performance because most
  perf issues only matter at scale and look fine in unit tests. A dedicated
  lens redirects attention to the trigger sizes that matter.

#### lens id: `edge-case-review`

- **Label**: Edge Case Review
- **Category**: task-rubric
- **Compatible roles**: `agent-review`
- **Compatible stage kinds**: `fan_out`
- **Mode**: `fan_out_only`
- **Conflicts with**: none. Conceptually adjacent to `agent-codex-review`,
  but applied to `agent-review` (single-pass primary lane), not the
  blocking-issues-only secondary lane. Both can run in the same pipeline.
- **Output contract delta**: `### Issues Found` tagged
  `[NULL]`/`[OFF-BY-ONE]`/`[BOUNDARY]`/`[EMPTY]`/`[OVERFLOW]`/`[TIME-ZONE]`/
  `[UNICODE]`. Every issue must name the specific input that triggers the
  failure.
- **Merge expectation**: judge prefers concrete failing inputs over abstract
  edge classes.
- **Safety notes**: none.
- **Evaluation tags**: `axis=edge-cases`, `signal=concrete-input-density`.
- **Prompt overlay sketch**: Bias toward null/empty/single-element inputs,
  off-by-one boundaries, integer overflow, time-zone ambiguity, unicode
  normalization, and concurrency edges. Drop any finding that cannot be
  expressed as a concrete failing input.
- **Why this lens**: Edge cases are where unit tests are weakest; a focused
  lens on the primary review lane catches them before they ship.

#### lens id: `prior-art-search`

- **Label**: Prior Art Search
- **Category**: scoping
- **Compatible roles**: `agent-research`
- **Compatible stage kinds**: `fan_out`
- **Mode**: `fan_out_only`
- **Conflicts with**: none. Pairs with `codebase-map` and `risk-discovery`.
- **Output contract delta**: `### Prior Solutions` becomes the dominant
  section. Each entry names a specific prior commit, ADR, claude-mem
  observation, or external reference (URL); duplicates are flagged. `###
  Sources` must include claude-mem search terms used.
- **Merge expectation**: `agent-research-merge` reconciles into Cross-Cutting
  Concerns + Existing Patterns. Where two prior-art searchers disagree on
  whether something has been done before, surface the disagreement under
  Conflicting Findings.
- **Safety notes**: none.
- **Evaluation tags**: `axis=prior-art`, `signal=duplicate-detection`,
  `host=agent-research`.
- **Prompt overlay sketch**:
  ```
  # Prior Art Search — research lens overlay

  Apply the normal agent-research contract from agents/agent-research.md.
  Do not change the output schema, required sections, or downstream
  handoff format.

  Bias your investigation toward prior solutions inside and outside this
  repo. Specifically:

  - Run claude-mem searches on at least three distinct phrasings of the
    task. Cite the search terms used in `### Sources`.
  - Walk `git log` for commits that touched the same modules; cite SHAs in
    `### Prior Solutions`.
  - Read existing ADRs and pipeline docs (`swarm-do/docs/`) for prior
    decisions about the same problem.
  - Where you find prior art, classify it: `[REUSE]` (already does what we
    need), `[ADAPT]` (close but needs change), `[REJECTED-EARLIER]` (was
    tried and abandoned — cite the rejection rationale), `[NONE]`.
  - Do not recommend; just report. The analysis agent will decide whether
    to reuse.

  Section names and Status vocabulary unchanged.
  ```
- **Why this lens**: Without an explicit prior-art lens, research reliably
  re-discovers solutions that already exist in claude-mem or in older
  commits, leading to duplicate-effort plans.

#### lens id: `codebase-map`

- **Label**: Codebase Map
- **Category**: scoping
- **Compatible roles**: `agent-research`
- **Compatible stage kinds**: `fan_out`
- **Mode**: `fan_out_only`
- **Conflicts with**: none
- **Output contract delta**: `### Relevant Files` becomes the dominant
  section. Each entry must name the *role* the file plays (entry point /
  config / hot path / test / fixture / generated). Existing Patterns lists
  the cross-module patterns the writer must follow.
- **Merge expectation**: research-merge consolidates duplicate file
  citations across siblings; surface any file that two siblings classified
  differently.
- **Safety notes**: none.
- **Evaluation tags**: `axis=scope`, `signal=file-role-coverage`.
- **Prompt overlay sketch**: Bias toward exhaustive enumeration of files in
  the affected subsystem and their roles. Use Grep + Glob to find entry
  points, config files, test files, generators, fixtures. Tag each file
  with its role. Don't evaluate code; just map it.
- **Why this lens**: For multi-module changes, downstream agents
  consistently miss files. A scoping lens shifts research from "what's
  relevant" to "what's *all* the surface area", explicitly.

#### lens id: `risk-discovery`

- **Label**: Risk Discovery
- **Category**: scoping
- **Compatible roles**: `agent-research`
- **Compatible stage kinds**: `fan_out`
- **Mode**: `fan_out_only`
- **Conflicts with**: none
- **Output contract delta**: `### Constraints` and `### Raw Notes` carry the
  bulk. Each constraint or risk-flag tagged
  `[REGRESSION-RISK]`/`[CONTRACT-CONSTRAINT]`/`[ENVIRONMENTAL]`/
  `[CULTURAL]` (e.g., "the team has tried this twice and abandoned it").
- **Merge expectation**: research-merge reconciles into Cross-Cutting
  Concerns; conflicting risk assessments go under Conflicting Findings.
- **Safety notes**: none.
- **Evaluation tags**: `axis=risk-surface`, `signal=constraint-density`.
- **Prompt overlay sketch**: Bias toward enumerating things that could go
  wrong: regressions in adjacent modules, undocumented contracts, fragile
  tests, environmental coupling (timezone, locale, OS), and prior-attempt
  abandonment. Do not propose mitigations; just enumerate. Analysis decides
  what to do.
- **Why this lens**: Without a risk-focused researcher, the analysis agent
  sees only the happy-path constraints; this lens surfaces the unhappy-path
  surface that analysis must consider.

### Additional lenses proposed

#### lens id: `correctness-rubric`

- **Label**: Correctness Rubric
- **Category**: task-rubric
- **Compatible roles**: `agent-review`
- **Compatible stage kinds**: `fan_out`
- **Mode**: `fan_out_only`
- **Output contract delta**: `### Issues Found` tagged `[LOGIC]`/
  `[CONTRACT]`/`[INVARIANT]`/`[STATE-MACHINE]`. Verdict vocabulary
  unchanged.
- **Why this lens**: A reviewer fan-out triad of `correctness-rubric` +
  `security-threat-model` + `performance-review` mirrors the analysis triad
  (`architecture-risk` + `api-contract` + `state-data`) and gives the
  judge three orthogonal review streams to merge. Without it, "primary
  review" is the unstated default and stacks awkwardly with the more
  focused lenses.

#### lens id: `migration-blast-radius`

- **Label**: Migration Blast Radius
- **Category**: task-rubric
- **Compatible roles**: `agent-debug`, `agent-analysis`
- **Compatible stage kinds**: `fan_out`
- **Mode**: `fan_out_only`
- **Output contract delta**: For `agent-analysis`, `### Risks` carries
  `[BLAST-RADIUS]` tags with affected systems enumerated. For `agent-debug`,
  the existing `Blast radius` section becomes mandatory rather than
  optional, with explicit checklists for cache, persistent state,
  background workers, and downstream consumers.
- **Why this lens**: Bug fixes and migrations are the two cases where blast
  radius is most expensive to under-estimate. agent-debug already has the
  section; the lens makes it the dominant evidence shape.

#### lens id: `mco-evidence`

- **Label**: MCO Evidence Posture
- **Category**: cross-model / provider
- **Compatible roles**: provider stage (no agent role)
- **Compatible stage kinds**: `provider`
- **Mode**: `provider_evidence`
- **Output contract delta**: provider stage emits the existing `findings`
  output (`provider.output: findings`,
  `validation.py:46-48`). The lens does not change provider output; it
  documents the *expected evidence posture* for downstream Claude review:
  treat findings as evidence-only, never as a verdict, and require the
  downstream `agent-review` to cite provider findings inline by index.
- **Why this lens**: There is no prompt overlay slot inside an MCO subprocess
  (it shells out via `bin/swarm-stage-mco`, see `SKILL.md:135-146`). The
  "lens" here is purely catalog metadata that describes how MCO findings
  thread into the next Claude stage's prompt. v1 should expose this so the
  TUI can show MCO-bearing pipelines as `experimental` and the downstream
  reviewer's prompt can reference the evidence file deterministically.

#### lens id: `adversarial-review` — DEFERRED

Defer to v2. Justifications:

- The plan calls out adversarial reviewers
  (metaswarm-style "trust nothing, verify everything"), but a true
  adversarial lens needs (a) a different verdict vocabulary
  (`REJECT-WITH-ATTACK`) or (b) elevated tool affordances (run sandboxed
  exploit code), neither of which the v1 review contract supports.
- Without those, the lens degenerates into "be more skeptical", which is
  exactly the kind of generic persona the 2025 evidence (PersonaGym;
  Rubric Is All You Need) shows is unreliable.
- v2 should design adversarial-review as a *new role*
  (`agent-adversarial-review`) with its own verdict vocabulary, not as a
  lens on `agent-review`.

---

## D. Compatibility Matrix

Cell legend: empty = incompatible, `F` = `fan_out_only` (Phase 3 today),
`S` = `single_agent` allowed once Phase 5 schema lands, `R` = `review_only`
(used as an extra review stage role), `P` = `provider_evidence`. Where two
modes are listed (`F/S`), `F` is v1-runnable and `S` becomes available in
Phase 5.

| Lens | research | analysis | review | writer | spec-review | codex-review | decompose | clarify | docs | debug |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `architecture-risk` |  | F/S |  |  |  |  |  |  |  |  |
| `api-contract` |  | F/S | F/S |  |  |  |  |  |  |  |
| `state-data` |  | F/S |  |  |  |  |  |  |  |  |
| `ux-flow` (DEFER) |  |  |  |  |  |  |  |  |  |  |
| `security-threat-model` |  | F/S | F/S |  |  |  |  |  |  |  |
| `performance-review` |  |  | F/S |  |  |  |  |  |  |  |
| `edge-case-review` |  |  | F/S |  |  |  |  |  |  |  |
| `prior-art-search` | F/S |  |  |  |  |  |  |  |  |  |
| `codebase-map` | F/S |  |  |  |  |  |  |  |  |  |
| `risk-discovery` | F/S |  |  |  |  |  |  |  |  |  |
| `correctness-rubric` |  |  | F/S |  |  |  |  |  |  |  |
| `migration-blast-radius` |  | F/S |  |  |  |  |  |  |  |  | F/S |
| `mco-evidence` |  |  |  |  |  |  |  |  |  |  |
| `adversarial-review` (DEFER) |  |  |  |  |  |  |  |  |  |  |

Notes on cells deliberately left empty:

- `agent-writer`, `agent-spec-review`, `agent-codex-review`,
  `agent-decompose`, `agent-clarify`, `agent-docs` — the writer holds the
  merge slot and operates from a fully specified work-unit contract; lenses
  on the writer would re-open design decisions the analysis already
  settled (`agent-writer.md:24-27`). spec-review is a fast-reject layer
  that exists explicitly to *avoid* deepening review (`agent-spec-review.md`
  preamble). codex-review's contract is already a tight single-purpose
  rubric (max 5 findings, blocking-only — `agent-codex-review.md:18-26`);
  adding a lens contradicts its design. decompose emits JSON to a
  schema-strict contract (`agent-decompose.md:42-54`); a lens that changes
  output is invalid. clarify is questions-only with `bd show` access only
  (`agent-clarify.md:26-28`); a lens that requires source-file reading is
  invalid. docs is .md-only (`agent-docs.md:26-30`); the lensing value is
  low.
- `mco-evidence` does not apply to any of the listed Claude-backed agent
  roles; it lives on the `provider` stage column (not shown — provider
  stages have no role). Marked separately rather than crammed into the
  matrix.

`mco-evidence` provider compatibility: type=mco only, command=review only,
providers in `{claude, codex, gemini, opencode, qwen}`
(`validation.py:49`). UNVERIFIED whether the catalog should also expose
provider lenses for `command=run` — the plan §86-90 keeps MCO opt-in and
review-only, so I did not include `command=run` in v1.

---

## E. Open Questions and Research Gaps

### High-confidence v1 inclusions

- `architecture-risk`, `api-contract`, `state-data`: already deployed as
  `explorer-a/b/c.md` in production fan-outs (`ultra-plan.yaml:11-19`).
  Catalog work just registers metadata and maps stable public lens ids to the
  existing variant filenames; no prompt content rewrite is required.
- `prior-art-search`, `codebase-map`, `risk-discovery`: directly map onto
  existing `agent-research` output sections; the lens overlays add tagging
  rules that the runtime already supports (no schema change). Confidence
  is high but **untested in production fan-outs** — no `agent-research`
  fan-out exists today.

### Provisional v1 inclusions (would change with new evidence)

- `security-threat-model`, `performance-review`, `edge-case-review`,
  `correctness-rubric`: the 2025 rubric-specificity finding supports
  inclusion, but I did not find a 2025–2026 SWE-bench-class result
  isolating *review-rubric specialization on Claude 4.x / GPT-5.x*. Ship
  these in v1 with an explicit "evaluate effect on telemetry comparison
  signals" tag, and remove any lens whose telemetry shows no measurable
  lift after one quarter of use.
- `migration-blast-radius`: provisional because `agent-debug` already
  contains the section; the lens may be redundant. Keep in v1 and remove
  if telemetry shows no incremental value over the un-lensed debug
  contract.

### Where 2026 evidence is thin

- **Single-agent lens overlays on Claude 4.x / GPT-5.x specifically** — no
  benchmark I located (B3) isolates this. The plan's stance of
  `fan_out_only` until Phase 5 + measurement is the safe call.
- **Stacked lens conflict** — no direct measurement found. The cautious
  singular-`lens` stance (plan §463) survives this research.
- **Cross-model review as a lens** — extant evidence (B6) supports cross-
  model review as a *route choice*, not a prompt overlay. Modeling it as
  a route lens (existing `agent.backend/model/effort` overrides and
  `fan_out.variant: models`) is correct; do **not** add a `cross-model`
  prompt lens to the catalog.
- **`ux-flow`** — deferred specifically because the runtime can't reach
  UX surfaces from inside `agent-analysis`. If a UI-aware research role
  ships in 2026Q3+, revisit.

### Runtime-support items verified after analysis

1. [VERIFIED] Dispatcher prompt assembly is skill-owned today, not Python-owned.
   `skills/swarm-do/SKILL.md:132` instructs the Claude dispatcher to load
   `roles/<role>/variants/<name>.md` as an additive overlay for
   `fan_out.variant: prompt_variants`. A repo search found no Python module
   that reads and concatenates variant bodies; Python validation only checks
   file existence (`validation.py:703-716`). Phase 1 can add catalog metadata
   without wiring a new Python runtime path, but tests may still want a small
   deterministic prompt-bundle helper to verify paths.
2. [VERIFIED] `merge.agent` cannot accept a role variant in v1. The pipeline
   schema permits only `merge.strategy` and `merge.agent`, and
   `MERGE_KEYS = {"strategy", "agent"}` causes `schema_lint_pipeline` to reject
   unknown merge keys. Do not specify merge-bias lenses until a future schema
   explicitly extends `merge`.
3. [VERIFIED] Route-resolution invariants do not constrain backends by
   prompt-variant role. `invariant_errors` only checks the orchestrator,
   `agent-code-synthesizer`, and synthesize merge agents. Prompt-variant
   fan-out branches resolve through the stage role's effective route; there is
   no per-lens backend constraint unless the Phase 1 catalog adds one
   explicitly. Also, current fan-out schema has one `variant` mode, so
   prompt-variant lenses and per-branch model routes cannot be mixed in the
   same fan-out stage.

### Does the plan's "singular `lens` for v1, stacking deferred" stance survive?

Yes. The 2025 evidence (B4–B5) gives no positive case for stacking, and the
indirect evidence (rubric specificity wins; long stacked instruction text
collides) supports the singular stance. Phase 5's schema should ship
`lens: <id>` (singular) and explicitly defer `lenses: [...]` to a separate
measurement phase, exactly as proposed at plan §445-463.

---

## Sources

### Repo files cited

- `swarm-do/docs/pipeline-composer-implementation-plan.md` (the plan)
- `swarm-do/roles/agent-analysis/variants/explorer-a.md:1-6`
- `swarm-do/roles/agent-analysis/variants/explorer-b.md:1-6`
- `swarm-do/roles/agent-analysis/variants/explorer-c.md:1-6`
- `swarm-do/role-specs/agent-analysis.md:60-103`
- `swarm-do/role-specs/agent-writer.md`
- `swarm-do/role-specs/agent-spec-review.md:56-89`
- `swarm-do/agents/agent-research.md:136-159`
- `swarm-do/agents/agent-review.md:54-69`
- `swarm-do/agents/agent-codex-review.md:54-69`
- `swarm-do/agents/agent-debug.md:82-113`
- `swarm-do/agents/agent-decompose.md:42-54`
- `swarm-do/agents/agent-clarify.md:48-65`
- `swarm-do/agents/agent-docs.md:26-30`
- `swarm-do/agents/agent-research-merge.md:50-82`
- `swarm-do/py/swarm_do/pipeline/validation.py:316-321,703-716,761-788`
- `swarm-do/schemas/pipeline.schema.json:37-50,101-108`
- `swarm-do/skills/swarm-do/SKILL.md:132,135-146`
- `swarm-do/docs/plan.md:1151,2367`
- `swarm-do/pipelines/ultra-plan.yaml:11-19`
- `swarm-do/pipelines/hybrid-review.yaml:24-31`
- `swarm-do/pipelines/mco-review-lab.yaml:24-37`
- `swarm-do/pipelines/default.yaml`
- `/Users/mstefanko/.claude/CLAUDE.md` (frontend-design routing)

### External evidence

- Rubric Is All You Need (ACM ICER 2025) —
  https://dl.acm.org/doi/10.1145/3702652.3744220
- PersonaGym: Evaluating Persona Agents and LLMs (EMNLP Findings 2025) —
  https://aclanthology.org/2025.findings-emnlp.368.pdf
- Persona Non Grata (arXiv 2026 preprint) — https://arxiv.org/abs/2604.11120
- Towards a science of scaling agent systems (Google Research, 2026) —
  https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/
- The Multi-Agent Trap (Towards Data Science, 2025; secondary context, not
  load-bearing) —
  https://towardsdatascience.com/the-multi-agent-trap/
- 2025 LLM Review (atoms.dev; secondary context, not load-bearing) —
  https://atoms.dev/blog/2025-llm-review-gpt-5-2-gemini-3-pro-claude-4-5
- Some 2025 LLM System Prompts (Gwern; secondary context, not load-bearing) —
  https://gwern.net/system-prompts-2025

### Anchors carried forward from the plan

- Hu and Collier 2024; Zheng et al. 2024; Lutz et al. 2025; Kim et al. 2025;
  Solo Performance Prompting (Wang et al. 2023). All cited at plan §111-129.

## Status: COMPLETE
