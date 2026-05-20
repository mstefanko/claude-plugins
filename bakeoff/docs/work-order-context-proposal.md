# Work-Order Context Injection — Decision Proposal

**Status:** Proposal — needs decision before implementation.
**Scope:** What context Bakeoff hands to provider agents at run start.
**Origin:** Postmortem of run `2026-05-19-4770` surfaced evidence that providers spent meaningful wall-clock time spelunking to find the right files. Question raised: should we hand them a head start?

---

## The two paths under consideration

(Option C — "author writes it into `background`" — is the status quo and is off the table. The work order that triggered this proposal demonstrated its failure mode: I authored wrong paths and both providers had to silently correct.)

### Option A — Auto-derived repo layout block

At run start, walk the repo and inject a small `<repo_layout>` block into the provider prompt, alongside the author's `<context>`. Mechanically derived from the filesystem — no human curation.

```
<repo_layout>
internal/workorder/         — work-order schema, validation, templates
internal/commands/buildcmd/ — build-mode runner
internal/commands/researchcmd/ — gather/compare/analyze runner
internal/buildverify/       — gate and metric evaluation
internal/decision/          — judge decisions, decision_kind logic
internal/report/            — report.md rendering
internal/runner/            — provider process lifecycle
docs/                       — work-orders.md, cli-reference.md
examples/                   — example work orders by type
</repo_layout>
```

Source for the one-line summaries: package doc comments (`package x // …`), `doc.go`, or — when absent — directory name. Cap at ~30 entries, one level deep.

### Option B — Opt-in `repo_context` field on the work order

Add a structured field the author can populate:

```jsonc
"repo_context": {
  "key_paths": [
    "internal/workorder/workorder.go",
    "internal/commands/buildcmd/run.go",
    "internal/buildverify/buildverify.go"
  ],
  "background_docs": ["docs/work-orders.md", "docs/cli-reference.md"]
}
```

Validated at `bakeoff validate` time: every path must exist under the invocation context root. Rendered into the prompt as a `<key_paths>` block separate from `<context>`.

---

## Senior-engineer reflection

### These solve different problems

This is the easiest way to think about A and B clearly: they look similar but aren't substitutes.

| | Option A | Option B |
|---|---|---|
| Answers | "Where are the rooms?" | "Which rooms should I look in first?" |
| Author burden | Zero | Author must know the codebase |
| Failure mode | Generic but never wrong | Anchoring bias when overstuffed |
| Cost | One filesystem walk at run start | Schema surface + validation |
| When it pays off | Every run | Runs with a specific hot path |
| Failure when wrong | Provider ignores a generic block | Provider chases a stale citation |

Treating them as competitors leads to a bad answer. Treating them as layers leads to a good one.

### What this run actually tells us

The run we just inspected gave us three concrete data points worth taking seriously:

1. **Both providers spelunked to the same files.** That's not noise — it's signal that "find the relevant files" is genuine work, costing wall-clock minutes per provider. Option A reduces it.

2. **The author (me) put wrong paths into `background` and the providers silently corrected.** This is the failure mode that disqualifies Option C. It's also a warning about Option B: a sloppily-authored `key_paths` list is *worse* than no list, because providers might trust it.

3. **Both providers independently reached the same hot-line citations (`run.go:159-168`, `buildverify.go:159`, `decision.go:122-130`).** The judge's consensus rested on this independent agreement. Anything that biases providers toward specific lines weakens this signal. **Option A is safe here** (rooms, not answers). **Option B is dangerous if `key_paths` is too narrow.**

### The case for Option A as default

- **Mechanically derived = no drift.** Move a package, the layout block updates automatically. Move it without updating Option-B paths, you ship a misleading prompt.
- **Already has a precedent.** `internal/reviewcontext/reviewcontext.go` already auto-injects a `<generated_review_context>` block for `gather` mode. Option A follows the same pattern, generalized to all modes.
- **Cheap to ship.** A walker that lists top-level packages with their `doc.go` or first comment, capped at 30 entries, is ~100 lines of Go. The injection point exists.
- **No author burden.** Authors who know the codebase deeply still benefit. Authors who don't (the majority — me, on every cross-repo run) benefit more.
- **Bounded downside.** The worst case is a layout block that lists `vendor/` next to `internal/`. Easy to filter; impossible to mislead the way wrong paths can.

### The case for Option B as an escape hatch

- **Author-curated is the highest-quality signal when the author knows the territory.** A maintainer doing a deep code review on `decision.go` should be able to say "look at these five files first."
- **Explicit beats magical.** The author *sees* what providers will see. No surprises at run time.
- **Validates at `bakeoff validate`.** If `repo_context.key_paths` includes a path that doesn't exist, the author finds out before burning 6 provider-minutes. This is the highest-leverage single piece of the proposal.
- **Doesn't fire when not present.** Authors who don't need it don't write it. Cost is zero for runs that don't use it.

### Where the value is highest

If I had to pick the single most valuable change here, it's **none of the above** — it's **path validation at `bakeoff validate` time**. Both A and B benefit from it. The status quo (Option C) is *also* fixed by it, because the wrong paths I wrote in `background` would have surfaced as a validation warning before the run started.

Concretely: at validate time, scan `background` and `goal` for tokens matching `[\w/.-]+(\.\w+)(:\d+)?` patterns. For each, if it looks like a file path (has an extension, has slashes, or matches a known shape), check if it exists under the invocation context root. Warning-level, not error — because legitimate references to renamed or removed code shouldn't block validation. Output:

```
warning: background references 'pkg/workorder' which does not exist under <context-root>.
warning: background references 'pkg/runner' which does not exist under <context-root>.
warning: background references 'pkg/report' which does not exist under <context-root>.
hint: did you mean 'internal/workorder', 'internal/runner', 'internal/report'?
```

That single feature would have saved this run from author error. Cheaper than either A or B, complements both.

### The objections I considered and discarded

- **"Auto-context biases providers toward specific files, undermining independent discovery."** Holds against Option B if `key_paths` names hot lines. Doesn't hold against Option A: a top-level layout block points at the *territory*, not the *answers*. Independent discovery happens at the `path:line` level, and Option A leaves that level untouched.

- **"CLAUDE.md should be auto-loaded; it has repo orientation."** No. CLAUDE.md is tuned for interactive sessions — task tracking conventions, commit message rules, memory-system protocols. None of that is useful to a one-shot research provider. Loading it pollutes the prompt with workflow rules the provider has no way to follow and no need to know.

- **"Just write better backgrounds."** This is Option C, and it lost on the evidence. The author who knows the codebase well enough to write perfect path citations is also the author who doesn't need the help. Everyone else writes prose with wrong paths.

- **"Two context blocks (`<context>` + `<repo_layout>` or `<key_paths>`) confuses providers."** Solvable with prompt structure. The existing `<generated_review_context>` pattern already shows this works.

---

## Recommendation (revised after team review)

Three substantive findings from review changed the shape of the recommendation:

- **F1 — Validator regex is too narrow.** Confirmed by validation: `pkg/workorder` and `pkg/runner` (the exact paths I authored wrong) both MISS the originally proposed pattern, which required a file extension. The validator that exists to catch *the actual failure mode* would not have caught it. Must be reworked.
- **F2 — "Default-on for all modes" is too broad for Option A.** A `scope: web` provider has no business seeing a local repo map. A fixed deny-list misses generated folders, monorepo noise, and run output. Must be both scope-gated and `git ls-files`-derived (with fallback).
- **F3 — Option B is where bloat and bias live, and shipping it in wave 1 is premature.** Defer until validator + Option A dogfood shows authors still struggle.

Plus one technical reality from validation: **this repo has zero `doc.go` files and zero package comments.** The originally proposed "summary source: doc.go → package comment → directory name" cascade would, in practice, emit pure directory names on day one. That's fine — *only* if the layout block stays explicitly framed as orientation, not authority.

The revised plan is below.

### Wave 1 — Ship together

**1. Path-and-directory validator.** Highest leverage; fixes the demonstrated failure mode (author error in `background`); enables everything downstream by giving us a vocabulary for "this path looks like a file/dir reference."

- **Detection:** match tokens that look like path references — slash-containing identifiers, optional `:line` or `:line-line` suffix, optional extension. Specifically must cover:
  - `pkg/workorder` (no extension, no line) — the demonstrated miss
  - `internal/workorder/workorder.go` (extension, no line)
  - `internal/runner/runner.go:111` (extension + line)
  - `internal/runner/runner.go:111-120` (extension + range)
- **Preprocess:** strip markdown formatting (backticks, brackets, link targets), strip trailing punctuation, ignore tokens that look like URLs (`scheme://`) or bare domains (`example.com`).
- **Resolve:** for each candidate token, check both file existence and directory existence under the invocation context root. Conservative: a token resolves if *either* matches.
- **Suggest:** on miss, search for paths sharing the same basename or path suffix (`workorder` → `internal/workorder/`, `internal/workorder/workorder.go`).
- **Throttle:** dedupe by token; cap at ~10 distinct misses per work order to keep validate output readable.
- **Severity:**
  - `background`, `goal` (prose fields): **warning** — legitimate references to renamed or removed code shouldn't block validation.
  - `repo_context.key_paths` (when shipped): **error** — structured fields are an explicit author contract.

### Wave 1 — Ship together (cont.)

**2. Tiny scoped `<repo_layout>` block (revised Option A).** A boring, mechanical orientation block — not a summary, not a guide, not a CLAUDE.md surrogate.

- **Scope gating:** only render for providers with `scope: "codebase"` or `scope: "mixed"`. Never render for `scope: "web"`. This is a hard rule, not a default.
- **Source:** `git ls-files`-derived top-level directories when the invocation context root is inside a git repo. Fallback to a one-level walk filtered by a small fixed deny-list (`.git`, `.bakeoff`, dotfile dirs) only when not in a git repo.
- **Budget:** 10–20 entries, hard cap 1.5 KB. Stable-sorted alphabetically.
- **Entry shape:** `path/   — description` where `description` is the first non-build-tag comment above `package x` in the package's first `.go` file when present; otherwise just the directory name. **Empty descriptions are fine.** On the current repo, every entry will be directory-only.
- **Prompt safety:** escape `<`, `>` in entries so a path like `<weird>` can't break out of the `<repo_layout>` block. Reject entries that contain `</repo_layout>` or `</context>` literally.
- **Framing line in the block:** "Orientation only — directory map at run start. Verify before citing; do not assume file:line locations." This is non-optional; it goes in every block.
- **Suppressible** via `--no-repo-layout` and via work-order `scope_policy.repo_layout: "off"`.

**3. `bakeoff validate context` (new).** Render and print the exact prompt context blocks that would be injected, without running providers. Output is human-readable: the validator's warnings, then `<repo_layout>` if it would render for any provider, then a note for each provider listing which blocks they will and won't receive (per their `scope`).

- Cost: ~50 lines of Go, reuses the renderers from items 1 and 2.
- Value: trust + bloat control. Authors see what providers will see before they spend provider-minutes.

### Wave 2 — Conditional on dogfood evidence

**4. `repo_context` field (deferred Option B).** Do not ship in wave 1. Revisit only if dogfooding wave 1 shows authors still spending meaningful provider-minutes on file discovery, or routinely stuffing paths into `background`.

Definition of dogfooding evidence we'd need:
- Multiple runs where provider `recommended_next_checks` show file discovery as the bulk of effort, **and**
- The validator + `<repo_layout>` did not close the gap.

If we then do ship it, with these constraints from review:

- **Block name:** `<author_repo_hints>`, never `<key_paths>`. The name carries the framing.
- **In-prompt framing:** explicit "Author-suggested starting points, not exhaustive. Use your own judgment; do not skip files the author didn't list."
- **Cap:** 8–12 exact relative paths.
- **Accept:** exact relative files and directories.
- **Reject:** globs, absolute paths, `..` traversal, paths outside the invocation context root.
- **Validation:** error-level (not warning) — structured fields are a contract.
- **Mixed-version handling:** old binaries silently accept the unknown top-level field and ignore it. Per the postmortem's Action Item #7, the broader fix is strict unknown-field rejection or feature manifest. Until that lands, `repo_context` docs must specify minimum Bakeoff version explicitly.

### Why this order, not the previous one

- **Validator first** is unchanged — it fixes the demonstrated failure mode at the lowest cost and feeds every downstream feature.
- **Repo layout second**, but now scope-gated and `git ls-files`-derived. The previous "default-on for all modes" was correctly criticized as too broad.
- **`bakeoff validate context` preview** is new and small. Shipping it with wave 1 buys us the dogfood signal needed to decide wave 2.
- **`repo_context` deferred** because the original "ship all three" recommendation didn't have a stop condition. The review correctly identified that B carries the highest variance and the lowest urgency. Validator + scoped layout might be enough.

### Why I no longer resist "skip B"

The previous draft argued that targeted reviews benefit from B. That's still true — but it's not urgent. The cost of *not* shipping B is that targeted-review authors fall back to prose, where the validator now catches their typos. The cost of shipping B prematurely is bloat, bias, and a junk-drawer prompt. Validator + layout closes most of the gap; ship B only when evidence shows it's still open.

---

## Resolved questions

- **Q1 — gitignore vs. fixed deny-list.** Decided: `git ls-files`-derived when in a git repo; small fixed deny-list (`.git`, `.bakeoff`, dotfile dirs) as the not-in-git fallback. Fixed deny-list alone is rejected — it misses run output, env-ish names, generated folders, and monorepo noise.
- **Q2 — monorepo scope.** Decided: walk is scoped to the invocation context root, not automatically to the git root. The context root is the CLI process CWD used for `bakeoff validate`, `bakeoff research`, `bakeoff build`, and `bakeoff rerun`; it is never the Bakeoff plugin install/source directory just because the binary lives there. In a git repo, run `git -C <context-root> ls-files -- .` so launching from a package/subdirectory intentionally narrows the layout to that subtree. If the operator wants full-monorepo context, they should launch from the monorepo root. Work-order file location does not define the context root; `bakeoff research /path/to/work-order.json` still resolves repo paths relative to the shell CWD.
- **Q3 — globs in `repo_context`.** Decided: exact relative files and directories only. Reject globs, absolute paths, parent-traversal. (Moot until wave 2.)
- **Q4 — scope-gating.** Decided: hard rule. `<repo_layout>` renders only for `scope: codebase | mixed`. Never for `scope: web`.
- **Q5 — provider-specific `validate context` output.** Decided: yes. Default output should show every provider's effective context view, because scope-gating means providers may receive different blocks. Add `--provider <id>` as a convenience filter for one provider's view; reject unknown ids with a validation error. Do not add a separate context root flag to `validate context` unless the same root flag is added to `research`, `build`, and `rerun`; preview and run must share the same root model. Always print the resolved context root at the top so cross-repo use is auditable.
- **Q6 — empty package-comment descriptions.** Decided: do not synthesize richer descriptions in wave 1. Directory-only entries are acceptable and intentionally low-authority. Avoid file counts, primary-language guesses, README extraction, or generated summaries for now; across Python, JS/TS, Rails, Go, and mixed monorepos those signals are often noisy and can make the block feel more authoritative than it is. If dogfood shows directory names are too thin, revisit with a purely mechanical metadata field under the same 1.5 KB cap, but do not block wave 1 on it.
- **Q7 — ambiguous "did you mean" suggestions.** Decided: show ambiguity instead of going silent. For each missing prose path, show up to a small cap of candidate matches, sorted by deterministic score: exact relative suffix match first, then directory basename match, then file basename match; within a score, prefer shorter paths under the context root. Example: `warning: background references 'pkg/run.go' which does not exist under <context-root>; did you mean one of: internal/commands/researchcmd/run.go, internal/commands/buildcmd/run.go?` Cap suggestions per token and cap total misses per work order. Never search outside the context root, and never suggest paths from the Bakeoff plugin repo unless the plugin repo is the actual invocation context root.

## Remaining open questions

None for wave 1. The next decision point is dogfood evidence after validator,
scoped `<repo_layout>`, and `bakeoff validate context` are available.
