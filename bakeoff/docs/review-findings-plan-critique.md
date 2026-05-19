# README Rewrite Plan — Critique

Plan reviewed: `docs/user-friendly-readme-rewrite-plan-2026-05-18.md`
Existing README compared: `README.md` (root of `bakeoff/`).

## Strengths

- **Strong section-by-section outline.** The plan specifies 11 numbered sections
  (Header through Troubleshooting) with sub-bullets, not just headings.
  Each workflow section (Research / Review / Build) follows a consistent
  spine: when to use, type/facet, prompt example, what Bakeoff drafts,
  flow diagram, output, evidence. That's a real template a writer can fill in.
- **Concrete acceptance criteria and a separate Definition of Done.** Both
  exist, and the DoD is testable (new user can run quickstart without reading
  schema details, build's non-mutation boundary is impossible to miss, etc.).
- **Plain-text flow diagrams are pre-drafted** for Research, Build, and the
  overall mental model — writers will not have to invent them.
- **Request-routing matrix is pre-drafted** with four rows mapping natural
  language to work-order shape. This is the highest-leverage piece of the
  document and the plan correctly elevates it.
- **Citations are concrete and pre-assigned to sections.** Each workflow has a
  short bibliography with arXiv URLs and a one-line rationale. A writer does
  not need to do literature research.
- **Boundary statements are explicit.** Build "does not apply, merge, commit,
  push, publish, or synthesize provider patches" is repeated in DoD and section
  outline so it cannot be dropped.
- **Progressive-disclosure principle is stated**, with Diataxis and NN/g
  references, and a clear "one click deep" rule for technical material.
- **Follow-up doc inventory exists** (`cli-reference.md`, `work-orders.md`,
  `research-basis.md`, `artifacts-and-ledger.md`) with scope for each.
- **Implementation plan lists verification checks** against the live
  implementation (`commands/run.md`, `skills/bakeoff/SKILL.md`,
  `examples/*.work-order.json`, exit code 3, `--keep-worktrees`).

## Gaps

Each gap below includes a concrete recommendation.

1. **No target audience definition.** The plan says "first-time user" and
   "new user" but never specifies the persona's prior knowledge: do they know
   what a work order is, what gates/verifiers are, what a judge is, whether
   they've used Claude Code plugins before, whether they write Go?
   **Recommendation:** Add an "Audience" subsection at the top of the plan
   with 2-3 sentences naming the primary reader (e.g., "Claude Code user
   evaluating Bakeoff for the first time; has used at least one plugin; does
   not know Bakeoff's schema; may or may not have Go installed") and a
   non-audience ("not for Bakeoff contributors — they read CLAUDE.md and the
   architecture docs").

2. **No tone or voice specification with examples.** The plan says "friendly
   and concrete" once but never models good vs. bad sentences.
   **Recommendation:** Add a "Voice" subsection with 2-3 before/after pairs.
   Example bad: "Bakeoff orchestrates parallel provider invocations with
   evidence-mediated selection." Example good: "Bakeoff runs the same task
   through Claude and Codex, then picks a winner with evidence."

3. **Header section is underspecified.** The outline allocates only 0.5 KB to
   the header and does not specify: tagline length, whether to include
   badges, plugin marketplace `/plugin` install hint, version, or one-sentence
   pitch wording.
   **Recommendation:** Pre-draft the one-sentence pitch and the tagline so the
   writer is not authoring the most-read line in the doc by judgment call.

4. **"What You Use It For" table loses a column the rest of the plan implies.**
   The Section 2 table has 3 columns (Workflow / Use it when / Result) but the
   workflow sections later promise "example prompt" and "expected output
   paths." The top table should foreshadow those without duplicating them.
   **Recommendation:** Either add a "Example request" column to Section 2 or
   explicitly say it is intentionally omitted and why.

5. **"Prerequisites" section is dropped without justification.** The existing
   README has a Prerequisites section (Go, provider CLIs, `git`, cwd writable).
   The plan's outline skips straight from "What You Use It For" to "Quick
   Start," which assumes the reader has those.
   **Recommendation:** Either restore a one-block Prerequisites callout above
   Quick Start, or specify exactly where prereqs live (e.g., a single line in
   Quick Start: "Requires Go 1.21+, `git`, and at least one of: Claude CLI,
   Codex CLI"). Don't leave it implicit.

6. **Install instructions are inconsistent with the existing README.** Plan's
   Quick Start uses `/plugin marketplace add ... <local path>` with the
   reviewer's machine path baked in. The existing README is path-neutral.
   **Recommendation:** Decide and specify: marketplace install command for
   external users, local-dev install command for contributors, or both with
   labels. Don't ship a hard-coded `/Users/mstefanko/...` path.

7. **No "Uninstall" section in the new outline.** Existing README has one.
   The plan's Section 10 ("Commands") lists `/bakeoff:uninstall` but does not
   call out the manual `/plugin uninstall` follow-up that the current README
   documents.
   **Recommendation:** Either keep an Uninstall section or fold the manual
   step into the Commands row for `/bakeoff:uninstall`.

8. **No "Development" / contributing pointer.** Existing README has a
   Development section. The plan does not say whether to keep, move, or drop
   it. Likely "move to one click deep," but the plan is silent.
   **Recommendation:** State explicitly: move Development content to
   `CONTRIBUTING.md` or `docs/development.md`, and link from the README footer.

9. **State and artifacts paths are not consolidated.** The plan has "Outputs
   and Artifacts" (Section 8) and a separate `docs/artifacts-and-ledger.md`,
   but does not specify which paths (e.g., `runs/<run-id>/providers/<winner>/
   build/diff.patch`, `review-context.md`, `dist/bakeoff`) live in the README
   vs. the one-click-deep doc.
   **Recommendation:** Provide a short whitelist in the plan: README shows
   3-4 most-inspected paths; everything else moves to
   `docs/artifacts-and-ledger.md`.

10. **No length budget per section or for the README as a whole.** The plan
    promises progressive disclosure and "compact" sections, but the existing
    README is ~8.4 KB and the new outline is clearly larger (matrices, tables,
    flow diagrams, evidence blocks). Without a budget the writer cannot tell
    when to stop.
    **Recommendation:** Set explicit budgets, e.g., "README ≤ 10 KB total;
    each workflow section ≤ 1.5 KB; flow diagrams ≤ 12 lines; matrices ≤ 6
    rows."

11. **Diagrams say "plain text first, Mermaid later" but never says when
    Mermaid is acceptable.** Half-decision.
    **Recommendation:** Pick one for this rewrite. Recommend plain text only
    in this pass, with a note that Mermaid is deferred to a follow-up issue.

12. **Evidence-placement strategy is ambiguous.** Plan alternately says
    "collapsible `<details>` blocks at the end of each section" and "link to
    `docs/research-basis.md`" and lists this as Open Question #1.
    **Recommendation:** Resolve the Open Question before drafting. Recommend:
    one-sentence rationale inline per section + collapsible `<details>` with
    arXiv links + cross-link to `docs/research-basis.md`. Pick once and write
    it into the plan.

13. **No copy-edit / review pass specified after draft.** Implementation plan
    step 7 mentions "docs-only review pass" but does not say who runs it or
    against what checklist.
    **Recommendation:** Specify: run `/bakeoff:run review` (eat your own
    dogfood) on the README diff with `code-review` facet, and check the
    rewritten README against the DoD bullets as a literal checklist.

14. **No screenshots, terminal recordings, or example output shown.** The
    existing README is text-only; the plan continues that. For "user-friendly"
    that is a missed opportunity, especially for the approval-prompt flow.
    **Recommendation:** Add an "example session" code block to Quick Start —
    a pasted transcript of `/bakeoff:run` showing the JSON draft + approval
    prompt. This is the moment where new users get confused.

15. **No "what Bakeoff is not" section.** The plan has "Why Bakeoff Is A Thin
    Launcher" (Section 9), which is good, but does not enumerate negative
    space (not an orchestrator, not a multi-agent framework, not a CI runner,
    not a benchmark suite, not a code-review service like Greptile, not a
    patch applier).
    **Recommendation:** Add an explicit "Bakeoff is not" bullet list to
    Section 9. The DoD already requires the README not imply Bakeoff is a
    multi-agent orchestrator — make that requirement visible to readers.

16. **No accessibility / readability notes.** Tables with 5+ columns can
    render badly in `/plugin` marketplace UIs and on narrow terminals.
    **Recommendation:** Cap tables at 4 columns in the README. Move wider
    matrices to one-click-deep docs.

17. **No success metrics beyond DoD bullets.** "A new user can install and
    run `/bakeoff:quickstart` without reading schema details" is good but not
    measured.
    **Recommendation:** Add a lightweight validation plan: e.g., walk a
    teammate through the README cold and time-to-first-run; record questions
    that required reading past the README.

## Ambiguities (decisions needed before execution)

The plan lists 5 Open Questions. All five are blockers for drafting and the
plan should resolve them, not pose them:

A. **Collapsible `<details>` vs. link-only to `research-basis.md`** — pick one
   placement strategy and write it into the plan (see Gap 12).

B. **Full JSON in the Build section vs. prompt-only with link** — drafting
   needs the answer. Recommend: prompt + 4-line JSON shape stub with link to
   `examples/build.work-order.json` for the full schema.

C. **`--base` and `--diff` flags in Quick Start or Review only** — recommend
   Review only; Quick Start should be three lines max.

D. **`bin/bakeoff` in README or `docs/cli-reference.md`** — recommend a single
   pointer line in the README ("CLI: see `docs/cli-reference.md`") and move
   all flag-level detail out.

E. **Whether `docs/cli-reference.md` ships in the same pass** — recommend yes.
   Without it, every README link to "one click deep" is broken on day one.

Additional ambiguities not flagged in the plan:

F. **What happens to the existing README's "Work-Order UX" section?** It is
   replaced by Section 4 (Mental Model) + workflow sections, but the plan
   never says "delete the Work-Order UX section." Make the deletion explicit.

G. **Is the README also the npm/marketplace listing description?** If yes,
   the header has additional constraints (no broken images, no path-relative
   links above the fold).

H. **Citations are dated 2024-2025 arXiv preprints.** Some are not peer
   reviewed. The plan does not specify a citation freshness or quality bar.

## Suggested Additions

1. **Audience and Voice subsections** at the top of the plan (see Gaps 1, 2).

2. **Header micro-spec**: one-sentence pitch, tagline, what badges (if any),
   install command(s), table of contents (if README ≥ 8 KB).

3. **Prerequisites callout** between header and Quick Start.

4. **Example-session transcript** in Quick Start showing the natural-language
   request → JSON draft → approval prompt flow.

5. **"Bakeoff is not" list** in Section 9.

6. **Length budgets per section** and overall README size cap.

7. **Mapping table** in the plan: each existing-README section → "kept",
   "rewritten", "moved to `docs/<file>`", or "deleted." This forces explicit
   decisions about Prerequisites, Work-Order UX, Competitive Build Handoff,
   State and Artifacts, Uninstall, Development. Without it, the writer will
   either silently drop sections or duplicate them.

8. **A "Resolved Decisions" subsection** that replaces the current "Open
   Questions" list with answers, written into the plan before drafting.

9. **Validation plan** (Gap 17): how the team will verify the new README
   meets the DoD after it ships.

10. **Verbatim test cases for the natural-language router**: e.g., "When a
    user types `/bakeoff:run check the auth retry behavior`, the README
    should make it obvious this is `gather` (not `review`). When they type
    `/bakeoff:run review main`, it should be obvious that is `gather` with
    `code-review` facet." Writers should be able to test their copy against
    these scenarios.

## Bottom Line

The plan is structurally above average for a README rewrite spec — it has a
real outline, concrete acceptance criteria, pre-assigned citations, and
pre-drafted matrices/diagrams. It is **not yet execution-ready** for these
reasons: (a) target audience and voice are unspecified; (b) five Open
Questions are blockers, not questions; (c) no length budgets, no
keep/move/delete mapping for the existing README's sections, and no
install-command/path decision; (d) no example-session transcript, no
"Bakeoff is not" list. Resolving the items in **Ambiguities A-H** and adding
the items in **Suggested Additions 1-7** would close the gap.
