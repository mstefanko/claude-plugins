# Extractions Table — Column Density Research

Researcher: agent-ux-researcher · 2026-05-26
Status: COMPLETE — findings only, no design or implementation
Scope: density patterns for the 7-column Extractions index. Source mockup described in conversation; plan context in `doc/plans/extractions-index-refresh.md`.

## 1. Survey of comparable apps

| App | Pattern observed | How it handles density |
|---|---|---|
| Linear (issues list) | Single primary cell + chip rail | Title is the dominant cell; status, priority, assignee, project, date sit as small chips/avatars to the right. Display-options menu lets users toggle column visibility. Dates render relative ("3d") with absolute on hover. |
| Stripe (Payments) | Amount-led row, single-line | One row per payment: amount, status pill, description (truncated), customer, date. Description and customer are separate, single-line columns — not stacked. Density toggle is global. |
| GitHub Actions (workflow runs) | Two-line primary cell, metadata as inline chips | Commit message above branch/actor/SHA chips in one cell; status icon at far left; relative time at far right. "Triggered by" is rendered as a small avatar+name chip inside the primary cell, not as its own column. |
| Sentry (issues) | Stacked title/subtitle + numeric trail | Event title above a one-line "location · last seen · assignee" metadata strip; count columns (events/users) right-aligned with tabular numerals. |
| Vercel (deployments) | Avatar+name+branch in primary, relative date trailing | Deployment id+branch stacked; author avatar+name inline; "Status" pill and "Duration" + relative timestamp as separate trailing columns. |
| Datadog (CI Visibility pipelines) | Status icon, pipeline name, single-line meta row | Author and date are co-located in a meta strip below the pipeline name, not split columns. |
| Retool / Airtable / Notion DB | User-controlled density + column hide | All three default to single-line cells with truncation and let the user expand row height or hide columns; none stack two distinct entities into one cell by default. |
| Hyperscience / Rossum (IDP queues) | Document-led row with status, model, reviewer, age | Reviewer and timestamp typically share a single right-aligned meta cell. |

Two consistent observations:
- Stacking is reserved for **a primary noun + its own metadata** (e.g. commit message + branch, deployment + author). Two unrelated nouns (e.g. payer + configuration) are kept in separate columns.
- "Who + when" frequently consolidates into one meta cell when neither is the primary sort target.

## 2. Verdict on each of the three options

### a. Group "Run By" and "Date" into one column — YES (conditional)
Strong precedent: GitHub Actions, Vercel, Sentry, Datadog all co-locate actor + timestamp in a single meta cell. Trade-off: independent sort on "Date" is desirable; "Run By" is rarely a sort key (it's a filter). Conditional: keep the column header semantically "Date" with sorting on date; render the user as secondary text under it. Filter on "Run By" stays in the toolbar (already present per the plan).

### b. Combine "Payer" and "Configuration" — NO
Payer is the business entity; Configuration is the run parameter set. They are conceptually different scopes, independently filtered (the toolbar already exposes "All Payers" and "All Prompt Sets" as separate filters), and users compare extractions across them. Stacking them implies a parent-child relationship that does not exist — the same payer is run under many configs, and the same config is run across many payers. None of the surveyed apps stack two cross-cutting filter dimensions into one cell.

### c. Tighten the ID column even with 3–4 digits — YES
At 4 digits the column needs roughly 5ch of content width. With tabular numerals and `#` prefix, this fits in ~64–72px including padding. Linear, GitHub, Sentry, and Stripe all give the ID column the narrowest possible width and right-align or use `font-variant-numeric: tabular-nums`. The ID is a lookup/recognition target, not a scan target.

## 3. Recommended approaches

### Primary recommendation — "1 + 5" layout (six cells, status moves to its own cell)
Columns, left to right:

1. **Status** (~36–44px) — icon-only or short pill, sortable. Pulling the status out of the EXTRACTION cell removes the line wrap and makes the status filterable by clicking the cell. Precedent: GitHub Actions, Sentry, Datadog all lead with a status indicator.
2. **ID** (~64–72px, tabular-nums, right-aligned) — `#1234`.
3. **Extraction** (flex, primary column) — filename single-line with `text-overflow: ellipsis`; full filename in tooltip/title attribute. No status pill here anymore.
4. **Payer** (~140–180px) — single line, link.
5. **Configuration** (~200–260px) — two lines: prompt-set name above model name. This is the one place stacking is legitimate because prompt-set and model together form one composite noun ("the configuration").
6. **Run / Date** (~140–160px, right-aligned) — date on top (sortable), user on bottom in muted text. Date uses absolute format for >24h, relative for <24h (GitHub pattern).
7. **Action** — keep as visible button on the row. Hiding it behind hover/menu is a documented anti-pattern for low-frequency power users who scan and click; per the plan this is the primary CTA per row.

Filename truncation: middle-truncate is unnecessary here because the discriminating tokens (payer name, date) live at the start of the filename. Left-aligned ellipsis at the end is sufficient; tooltip restores full string. Reference: Stripe description column.

### Alternative A — keep current 7 columns, apply density only
Change nothing structurally. Apply `table-sm`, tabular-nums on ID and Date, single-line filename with ellipsis, and let the status pill stay inside the EXTRACTION cell but move it to a small inline chip beside the filename rather than stacked above it. Cheapest path; preserves the plan in `extractions-index-refresh.md` exactly.

### Alternative B — Linear-style chip rail
One primary cell (filename + payer chip + config chip + user avatar inline) and only Status, ID, Date, Action as discrete columns. Highest density, but loses the ability to scan a column for "what model ran this" — the very comparison this product exists to support. Not recommended for this use case.

## 4. Trade-offs / risks

- **Consolidating Run By + Date** costs the ability to sort by user (rarely needed) and slightly weakens at-a-glance "who ran this" scanning. Mitigated because Run By is already a toolbar filter.
- **Pulling Status into its own column** costs ~40px of horizontal space but recovers vertical space (no more two-line EXTRACTION cell) and enables click-to-filter. Net win on a wide admin viewport; may pinch on <1280px.
- **Keeping Configuration stacked** preserves the comparison workflow (same document, different model) but means that column cannot be made narrower without truncating model names like "Claude 3 Opus" or "Llama 3.1 70B Instruct" — these need ~22ch.
- **Tightening ID** is safe up to 5 digits with tabular numerals; risk only appears if IDs grow past 99,999 or if the team wants to show external/UUID identifiers later.
- **Action button in-row vs. hover** — keeping it in-row costs ~80px but matches every surveyed app except Linear (which uses keyboard-first interaction the PayerIQ user base does not have).

## 5. Content findings (audit lens)

- **Labeling consistency**: "Run By" vs. "Performer" — the plan file (`doc/plans/extractions-index-refresh.md`) uses both. Pick one in user-facing copy; "Run by" is more natural for an activity log. Flag for product/content decision.
- **Nomenclature**: "Configuration" is acceptable but generic. If users say "prompt set" and "model" colloquially, consider whether the column header should be "Prompt set / Model" — flag, do not decide.
- **Hierarchy**: today's EXTRACTION cell has status (highest signal) below the filename visually because of stacking direction; moving status to its own leading column fixes this without requiring a copy change.
- **Progressive disclosure**: full filename, exact timestamp, and full configuration metadata belong in row detail / tooltip, not the row itself. The row should answer "which run was this and what state is it in"; the detail view answers "what exactly happened".

## 6. Bootstrap 5 components available

- `.table-sm` — halves cell padding for compact density.
- `.table-responsive` wrapper — horizontal scroll fallback below desktop widths.
- `.badge` (with status color utility classes) — for the standalone Status cell.
- `.text-truncate` utility + `title=` attribute — for single-line filename with tooltip.
- `.text-body-secondary` — for the muted secondary line (user under date, model under prompt-set).
- No component needs to be invented; everything maps to existing Bootstrap 5 utilities already in the theme per memory id #13692 / #13723.

## 7. Confidence notes

- High confidence on the cross-app patterns (GitHub, Stripe, Linear, Sentry, Vercel) — directly observed in product UIs and confirmed by prior indexed research (#12676, #12677, #13494).
- Medium confidence on the exact pixel widths — these depend on the host page's font stack and gutter, which were not measured. Treat the px values as starting points, not specifications.
- Lower confidence on whether users actually sort by date vs. just filter by date range. Worth a 2-question check with the design partner before locking sort affordances. Flagged for human.
- Tone of "Run by" vs "Performer" requires a product/content decision, not a research finding.

## 8. Sources

- `doc/plans/extractions-index-refresh.md` — current 7-column structure, status tabs, filters, scoping. (memory id #13692)
- `doc/plans/dashboard-wireframe-refresh.md` — Bootstrap 5 token usage and theme tokens already available. (memory id #13723)
- Prior UX research memory ids #12675, #12676, #12677 — Linear grouping, Stripe density control, Vercel typography, GitHub Projects grouping limits, Bootstrap `.table-sm` and stacked-cell mobile patterns.
- Prior IDP research memory ids #13489, #13490, #13492, #13493, #13494 — Rossum, Hyperscience, Ocrolus, Kira, Luminance patterns confirming field-level review and meta-cell consolidation.
- GitHub Community Discussion #58663 — GitHub Actions relative/absolute timestamp behavior in workflow runs list.
- Stripe docs `dashboard/basics` and `stripe-apps/components/table` — column composition for transactions list.
- Linear docs `display-options`, `board-layout` — column toggling and grouping behavior.

## Handoff

Recommended next step: this is design work, not architecture or data. Route to **agent-ui-designer** with this document as the brief. Two product/content decisions need a human before design locks:
1. "Run by" vs. "Performer" terminology.
2. Whether "Configuration" should be renamed "Prompt set / Model" in the column header.

## Status: COMPLETE
