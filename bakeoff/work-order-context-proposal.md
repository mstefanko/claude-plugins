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

Validated at `bakeoff validate` time: every path must exist in CWD. Rendered into the prompt as a `<key_paths>` block separate from `<context>`.

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

Concretely: at validate time, scan `background` and `goal` for tokens matching `[\w/.-]+(\.\w+)(:\d+)?` patterns. For each, if it looks like a file path (has an extension, has slashes, or matches a known shape), check if it exists in CWD. Warning-level, not error — because legitimate references to renamed or removed code shouldn't block validation. Output:

```
warning: background references 'pkg/workorder' which does not exist in CWD.
warning: background references 'pkg/runner' which does not exist in CWD.
warning: background references 'pkg/report' which does not exist in CWD.
hint: did you mean 'internal/workorder', 'internal/runner', 'internal/report'?
```

That single feature would have saved this run from author error. Cheaper than either A or B, complements both.

### The objections I considered and discarded

- **"Auto-context biases providers toward specific files, undermining independent discovery."** Holds against Option B if `key_paths` names hot lines. Doesn't hold against Option A: a top-level layout block points at the *territory*, not the *answers*. Independent discovery happens at the `path:line` level, and Option A leaves that level untouched.

- **"CLAUDE.md should be auto-loaded; it has repo orientation."** No. CLAUDE.md is tuned for interactive sessions — task tracking conventions, commit message rules, memory-system protocols. None of that is useful to a one-shot research provider. Loading it pollutes the prompt with workflow rules the provider has no way to follow and no need to know.

- **"Just write better backgrounds."** This is Option C, and it lost on the evidence. The author who knows the codebase well enough to write perfect path citations is also the author who doesn't need the help. Everyone else writes prose with wrong paths.

- **"Two context blocks (`<context>` + `<repo_layout>` or `<key_paths>`) confuses providers."** Solvable with prompt structure. The existing `<generated_review_context>` pattern already shows this works.

---

## Recommendation

Ship in this order, smallest-first:

1. **Path-pattern validator** for `background` and `goal` fields at `bakeoff validate` time. Warning-level. Scoped to the work order — no new schema, no prompt change. **Highest leverage. Ship first.**

2. **Option A — auto-derived `<repo_layout>` block.** Default-on for all modes. Suppressible with `--no-repo-layout`. Capped at 30 entries, one level deep, with `vendor/`, `node_modules/`, `.git/`, `dist/`, `node_modules/`, and dotfile directories filtered. Source one-line descriptions from `doc.go` / `package x // …` / directory name (in that order).

3. **Option B — opt-in `repo_context` field.** Additive to `schema_version: 1` (no bump needed — the validator only rejects unknown top-level fields if they collide with required names; this name is new). Validated paths must exist; otherwise validation errors. Rendered as a separate `<key_paths>` block in the prompt, kept distinct from `<context>` and `<repo_layout>` so providers can tell which is author intent vs. auto context.

### Why this order, not the reverse

- (1) ships independently of (2) and (3); fixes the demonstrated failure mode (author error) at the lowest cost.
- (2) is harder to undo than (3) because it's default behavior. Worth shipping after (1) so we have validation in place first, but before (3) so we have a default safety net before we offer the higher-variance escape hatch.
- (3) is easiest to misuse. Shipping it last means we land it when authors already have the validator catching mistakes and the layout block reducing the temptation to over-stuff `key_paths`.

### Why I'd resist a "skip A, ship B only" reading

Two reasons:
- B only helps authors who know the codebase. The most valuable bakeoffs are cross-repo runs by authors who don't. A helps everyone.
- B without A creates a pit of failure: authors copy each other's `key_paths`, paths go stale, providers chase ghosts. A is the safety net.

### Why I'd resist a "skip B, ship A only" reading

One reason: there are real runs where focused attention is the right call. A targeted security review of `internal/runner/` benefits from the author saying "these are the four files." Without B, that author falls back to stuffing paths into prose `background` — the failure mode we're trying to eliminate.

---

## Open questions for the team

- **Q1.** Should the `<repo_layout>` block respect `.gitignore` and `.bakeoffignore`, or just have a fixed deny-list (`vendor/`, `node_modules/`, etc.)? Leaning toward fixed deny-list for predictability.
- **Q2.** For monorepos, should the layout walk be scoped to the work order's `cwd` or the git root? Probably `cwd` to match scope policy.
- **Q3.** Should `repo_context.key_paths` accept globs, or only exact paths? Exact paths is safer for validation; globs invite drift.
- **Q4.** Should the layout block respect a `--scope` flag (e.g., suppress for `scope: "web"` providers)? Probably yes — web-scope providers shouldn't see local layout at all.
