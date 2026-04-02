# Formats Reference

## Shared Frontmatter Schema

Both decisions and notes use this frontmatter:

    ---
    title: "Clear, specific statement"
    type: decision | note
    created: YYYY-MM-DD
    project: enovis-plugins
    tags: [tag1, tag2]
    ---

### Additional fields for decisions

    status: accepted | superseded | deprecated
    bead: beads-xxx
    superseded_by: [[filename]]

### Field definitions

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| title | Always | Quoted string | Specific statement, not a topic |
| type | Always | `decision` or `note` | Claude decides based on content |
| created | Always | `YYYY-MM-DD` | Date written |
| project | Always | String | Which project this relates to |
| tags | Always | Array | 2-5 specific, searchable tags |
| status | Decisions only | String | Start as `accepted` |
| bead | Optional | `beads-xxx` | Link to bead if one exists |
| superseded_by | Optional | `[[wikilink]]` | If this decision was replaced |

## Decision Record Body (4 sections, all required)

### Context
What problem or situation prompted this decision? What constraints
were you under? Do NOT describe the solution here. 2-3 sentences max.

### Decision
What did you choose and how does it work at a high level?
Plain language, no code.

### Ruled Out
Alternatives considered and why they were rejected. Bullet list:
- **Alternative A** — rejected because [reason]
- **Alternative B** — rejected because [reason]

### Consequences
What becomes easier or harder? Include both positive and negative.

## Note Body (freeform)

No prescribed sections. Structure based on what's being captured.
Examples of what notes look like:

**A gotcha:**
> The legacy_notes column on patient_agreements is varchar(255) but
> Rails has no length validation. DB silently truncates. Check column
> length on legacy tables before writing long-form content.

**A pattern:**
> When run-plan hits a login redirect, the three-step auth sequence
> is: detect (check URL) → refresh (POST /session) → verify (re-check).
> If detect fails, skip straight to fresh login — don't retry stale state.

**A link with context:**
> The CMS Coverage API at cms.gov/medicare-coverage-database has LCD
> and NCD search. Use search_local_coverage(document_type='lcd') for
> local policies. State-specific — must get contractor ID first via
> get_contractors.

## Decision Example

    ---
    title: "Use three-step auth startup instead of single-shot login"
    type: decision
    status: accepted
    created: 2026-04-01
    project: enovis-plugins
    bead: beads-abc
    tags: [auth, playwright, run-plan]
    ---

    # Use three-step auth startup instead of single-shot login

    ## Context

    Run-plan was failing silently when auth state expired mid-session.
    Single-step browser init couldn't detect stale cookies until after
    navigation, wasting a full page load cycle.

    ## Decision

    Split auth into detect, refresh, verify steps. Each step has its
    own timeout and failure mode. If detect fails, skip straight to
    fresh login instead of retrying with stale state.

    ## Ruled Out

    - **Refresh cookies before every run** — too slow, adds 3-5s
      even when auth is valid
    - **Catch login redirect after the fact** — wastes a page load,
      can't distinguish auth failure from navigation failure

    ## Consequences

    - Auth failures surface in <2s instead of 30s timeout
    - Added ~40 lines to run_plan.ts (acceptable complexity)
    - Login detection centralized in isLoginUrl() helper
    - Trade-off: three network round trips on first run of a session

## Note Example

    ---
    title: "MySQL silently truncates strings over 255 chars in legacy columns"
    type: note
    created: 2026-04-02
    project: enovis-plugins
    tags: [mysql, data-integrity, patient-agreements]
    ---

    # MySQL silently truncates strings over 255 chars in legacy columns

    The legacy_notes column on patient_agreements is varchar(255) but the
    Rails model has no length validation. Discovered while debugging
    import truncation — Rails won't warn you, the DB silently cuts off.

    Check column length on any legacy table before writing long-form
    content. Migration to text type tracked in beads-xyz.
