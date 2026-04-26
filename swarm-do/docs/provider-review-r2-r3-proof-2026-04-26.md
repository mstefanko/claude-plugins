# Provider Review R2/R3 Local Proof - 2026-04-26

This note records the redacted local proof evidence used to close Codex R2,
Claude R3, and the Phase C deferred-runtime-polish decision gate.

Raw operator session logs are not committed because they contain full local
session/model output. This file preserves only the command-level outcomes and
the code-relevant findings needed for future audit.

## Scope

- Machine/context: local operator machine, repository workspace.
- Date captured: 2026-04-26.
- Providers covered: Codex R2 and Claude R3 real CLI fixtures.
- Gate evaluated afterward: Phase C from
  `docs/provider-review-mco-pattern-adoption-plan.md`.

## Commands And Outcomes

Codex R2 local fixture:

```bash
SWARM_RUN_CODEX_R2_FIXTURE=1 PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_provider_review.ProviderReviewTests.test_local_codex_r2_fixtures_pass_when_explicitly_enabled
```

Outcome: passed after the schema issue below was fixed.

Claude R3 local fixture:

```bash
SWARM_RUN_CLAUDE_R3_FIXTURE=1 PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_provider_review.ProviderReviewTests.test_local_claude_r3_fixture_passes_when_explicitly_enabled
```

Outcome: passed after the read-only enforcement issue below was fixed.

Combined live R2/R3 provider-review suite:

```bash
SWARM_RUN_CODEX_R2_FIXTURE=1 SWARM_RUN_CLAUDE_R3_FIXTURE=1 PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_provider_review
```

Recorded result:

```text
Ran 59 tests in 92.444s
OK
```

Full discovery suite:

```bash
PYTHONPATH=py python3 -m unittest discover -s py
```

Recorded result:

```text
Ran 384 tests in 6.024s
OK (skipped=3)
```

## Findings Fixed Before Final Pass

R2 exposed a Codex structured-output schema problem: the schema rejected the
fixture because required object properties did not exactly match the emitted
`findings.items` shape. The schema and fixture expectations were corrected,
then the R2 fixture passed.

R3 exposed two Claude proof issues:

- The first run separated schema-smoke validation from write-denial validation
  so a read-only failure could not be hidden by non-schema diagnostic output.
- The second run proved `--permission-mode plan` alone was insufficient in this
  local harness: write, edit, and shell mutation attempts were not blocked. The
  Claude command builder and resolver gate now require
  `--disallowedTools Write,Edit,NotebookEdit,Bash`.

After those fixes, the R3 schema-smoke and write-denial fixtures both passed.

## Gate Result

Codex R2 is closed for this proof set: command flags, native schema output,
read-only write denial, and readiness probing were green in the local fixture
run.

Claude R3 is closed for this proof set: native schema output and read-only
write denial were green only after explicit `--disallowedTools` enforcement was
added to the real Claude command path and resolver requirements.

The proof does not add any new evidence for Phase C runtime polish. It shows
successful bounded real provider fixtures, but it does not show repeated
no-output hangs, hard-deadline cancellation that discards parsed successful
work, stdout/stderr liveness growth thresholds, or a named SARIF/Markdown
consumer.

Therefore Phase C is closed with no deferred runtime-polish adoption:

- Do not add a progress-aware stall timeout.
- Do not add SARIF or Markdown-PR renderers.
- Keep per-provider perspectives, divide-by-files, chain/debate/memory, and
  reliability scoring rejected unless a future ADR reopens ownership.
