# Review Kit Provenance

Review Kit implements the direction from:

- `/Users/mstefanko/myorthomd-web/docs/code-review-research/00-synthesis.md`
- `/Users/mstefanko/myorthomd-web/docs/code-review-research/01-llm-nondeterminism.md`
- `/Users/mstefanko/myorthomd-web/docs/code-review-research/02-intent-in-code-review.md`
- `/Users/mstefanko/myorthomd-web/docs/code-review-research/03-context-amount.md`
- `/Users/mstefanko/myorthomd-web/docs/code-review-research/04-prompts-and-swarms.md`
- `/Users/mstefanko/myorthomd-web/docs/code-review-research/05-chunking-vs-large-diff.md`
- `/Users/mstefanko/myorthomd-web/docs/code-review-research/06-web-prompt-scan.md`
- `/Users/mstefanko/myorthomd-web/docs/code-review-research/07-plugin-implementation-plan.md`
- `/Users/mstefanko/myorthomd-web/docs/code-review-research/prompts/01-single-agent-routine.md`
- `/Users/mstefanko/myorthomd-web/docs/code-review-research/prompts/02-swarm-multi-lens.md`
- `/Users/mstefanko/myorthomd-web/docs/code-review-research/prompts/03-bakeoff-gap-analysis.md`

Implementation choices carried into v1:

- Build a new plugin as a context assembly, routing, and intent-fencing layer.
- Keep execution in bakeoff for ledgered multi-provider swarm runs.
- Use curated context: changed files, immediate dependencies, and only relevant conventions.
- Make route reasons, repeat policy, confidence gate, chunks, lenses, and exclusions explicit in a review plan.
- Keep review commands read-only/output-only.
