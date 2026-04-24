# MCO Spike Prompts for Section 1.12

These prompts chunk `plans/swarm-do-1.12-orchestration-friction-fixes.md` for
manual `bin/swarm-stage-mco` runs. They are designed to test the MCO adapter
spike before adding provider stages to the pipeline DSL.

Recommended order:

1. `prompts/00-whole-plan-coherence.md`
2. `prompts/01-context-resilience.md`
3. `prompts/02-preflight-permissions.md`
4. `prompts/03-dag-retry-commit.md`
5. `prompts/04-knowledge-adversarial-validation.md`

Run from `swarm-do/`:

```sh
ROOT="$(git rev-parse --show-toplevel)"
PROVIDERS="${PROVIDERS:-claude,codex}"

bin/swarm providers doctor --mco

bin/swarm-stage-mco \
  --repo "$ROOT" \
  --prompt-file "$PWD/data/mco-spike/1.12/prompts/00-whole-plan-coherence.md" \
  --providers "$PROVIDERS" \
  --output-dir "$PWD/data/mco-spike/1.12/results/00-whole-plan-coherence" \
  --run-id MCO_112_00 \
  --issue-id mco-1.12-00 \
  --stage-id mco-review-spike
```

Repeat with the other prompt filenames and matching output directories/run IDs.
Use at least two providers when possible so the normalized output exercises
`detected_by`, `provider_count`, `consensus_score`, and `consensus_level`.

Do not treat these runs as implementation approval. The intended output is a
set of provider findings that helps decide whether the MCO adapter is stable
enough to justify the experimental provider stage work.
