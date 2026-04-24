# Extracted phases — swarm-do run scope (refactor + 9g close)

**Source:** `/Users/mstefanko/.claude/plans/we-ended-up-reviewing-linear-emerson.md` (approved plan). **Phases:** `1` → `2` → `3` → `4` → `5` → `6`. Multi-phase extract.

**Runnable scope for this swarm-do invocation:** the six `### Phase N:` sections below, in strict sequence. Orchestrator: iterate each phase once in order. Do not start the next phase until the current phase's review is APPROVED, the writer's branch is merged, and all phase issues are closed. Open exactly one consolidated PR at the end — do not stack PRs.

**Dependency structure:** strict linear. Phase 2 (9g) requires Phase 1's `registry.py` + `jsonl.py`. Phase 3 migrates against the Phase 1 foundation. Phase 4 uses the extractor package layout Phase 1 seeded. Phase 5 builds its own `py/swarm_do/roles/` package but uses Phase 1's bootstrap shim pattern. Phase 6 uses generators landed in Phases 3–5.

**Prerequisites (all shipped):** Phase 9a–9f telemetry stack on `main` at `ff14fc8`+ (schemas, swarm-run append path, bin/swarm-telemetry bash+python-heredoc monolith, bin/extract-phase.sh codex-only extractor, adjudication sampler, rubrics/v1.md, findings/outcomes/adjudications ledgers).

**What we are NOT doing here:** Phase 10a–10g. That is a separate swarm-do run after this merges (`swarm-do/docs/phases-10a-10g.md` already exists; its preamble will need one light edit to replace "bash validator" framing with "Python validator shim").

**Known open follow-ups that this refactor closes automatically** (do not double-ship):
- `mstefanko-plugins-utu` — real ULID. Closes in Phase 1 (`py/swarm_do/telemetry/ids.py`) and Phase 3 (swarm-run adopts the generator when its telemetry path routes through the registry).
- `mstefanko-plugins-1zv` — wire `_diff_bytes` into jq row. Closes in Phase 3 (runs.jsonl write path migrates to Python).
- `mstefanko-plugins-rgb` — widen `timestamp_end.type` to `[string, null]`. Closes in Phase 3 (schema regeneration through the registry).

**Cost signal for analysis-phase model selection:**
- Phase 1 (`moderate`, refactor): analysis + writer on sonnet.
- Phase 2 (`simple`, feature): analysis sonnet, writer haiku.
- Phase 3 (`hard`, refactor): analysis + writer on **opus**. Most expensive phase.
- Phase 4 (`moderate`, feature): sonnet.
- Phase 5 (`moderate`, refactor): sonnet.
- Phase 6 (`simple`, refactor): analysis sonnet, writer haiku.

**Risk flags (first-class inputs for analysis):**
- **Phase 3 is the big one.** Six subcommands, each behind a parity test against a pinned pre-refactor bash implementation. The cheapest → heaviest migration order is required (dump, validate, query, report, sample-for-adjudication, join-outcomes). Don't let the writer start with `join-outcomes` to "get the hard one out of the way" — that skips the easier shape-setters that validate the package pattern.
- **Phase 5's codex-review rename is structural.** `bin/codex-review-phase:19` must resolve to `agent-codex-review-phase0` post-rename, not the original `agent-codex-review` name. Leaving either half of the rename incomplete leaves the drift vector that motivated this whole refactor.
- **Python bootstrap is load-bearing.** The shim PYTHONPATH prepend pattern in Phase 1 is verified by a fresh-checkout test. Skipping this verification and landing subcommand migrations first means the very first user run after merge fails with `ModuleNotFoundError`.

**Context references.** The approved plan at `/Users/mstefanko/.claude/plans/we-ended-up-reviewing-linear-emerson.md` contains the full rationale, package layouts, and verification gates. When research / analysis needs that detail, read it directly.

**Lifecycle.** This file is ephemeral. Delete it after all six phase reviews close; the approved plan and `swarm-do/docs/plan.md` remain canonical.

---

### Phase 1: Refactor foundation (complexity: moderate, kind: refactor)

**Objective:** Ship the Python package skeleton, the bootstrap shim pattern, and the four foundation modules (`registry.py`, `jsonl.py`, `ids.py`, `schemas.py`). No subcommand migration in this phase — just the scaffolding every subsequent phase will consume.

**What to implement:**
- `swarm-do/docs/adr/0002-telemetry-sources-of-truth.md` naming three sources of truth: Python telemetry package, role-specs, ledger registry. Explicit statement that `agents/` and `roles/*/shared.md` become generated outputs starting in Phase 5.
- `swarm-do/bin/_lib/python-bootstrap.sh` — sourced by every shim. Resolves `_PY_ROOT` relative to `${BASH_SOURCE[0]}`, exports `PYTHONPATH="${_PY_ROOT}:${PYTHONPATH:-}"`, checks `python3 --version` is ≥ 3.10 and exits 1 with clear upgrade message otherwise.
- `swarm-do/bin/swarm-telemetry` becomes a thin shim: sources `bin/_lib/python-bootstrap.sh`, `exec python3 -m swarm_do.telemetry.cli "$@"`. Prior bash body is retained under `bin/swarm-telemetry.legacy` so Phase 3's parity tests have something to compare against. At end of Phase 3, `.legacy` is deleted.
- `swarm-do/py/swarm_do/__init__.py` (empty).
- `swarm-do/py/swarm_do/telemetry/__init__.py` (empty).
- `swarm-do/py/swarm_do/telemetry/cli.py` — argparse entrypoint. Subcommand list equals `swarm-do/bin/swarm-telemetry.legacy`'s subcommand list; every subcommand dispatches to the legacy bash implementation via `subprocess.run(["bash", LEGACY_PATH, ...])` for now. Real Python implementations land per-subcommand in Phase 3.
- `swarm-do/py/swarm_do/telemetry/registry.py` — frozen `Ledger` dataclass + `LEDGERS` dict for the 5 current ledgers (runs, findings, outcomes, adjudications, finding_outcomes). Fields: `name`, `filename`, `schema_path` (relative to plugin root), `fallback_order` (tuple of historical schema paths).
- `swarm-do/py/swarm_do/telemetry/jsonl.py` — `stream_read(path) -> Iterator[dict]`, `atomic_write(path, rows: Iterable[dict])` using tempfile + fsync + `os.replace`. No non-atomic append yet (Phase 2's purge needs atomic; runs-append via swarm-run stays bash in Phase 3 scope).
- `swarm-do/py/swarm_do/telemetry/ids.py` — `new_ulid()` returning Crockford-base32 26-char ULID. Uses `secrets.token_bytes` + `time.time_ns()`. Matches `^[0-9A-HJKMNP-TV-Z]{26}$`.
- `swarm-do/py/swarm_do/telemetry/schemas.py` — `load_schema(ledger_name)` reads from the path in `registry.LEDGERS[ledger_name].schema_path`; `validate_row(row, schema)` = port of the existing draft-07 stdlib validator in `bin/swarm-telemetry.legacy:194-349`.
- `swarm-do/py/swarm_do/telemetry/tests/` — empty `__init__.py`, `fixtures/` directory placeholder, `test_registry.py` + `test_ids.py` + `test_jsonl.py` + `test_schemas.py` each with at least one smoke test.

**Verify:**
- Fresh-checkout simulation: `PYTHONPATH='' bin/swarm-telemetry --help` exits 0 and prints the subcommand list (passthrough to legacy).
- Python version gate: `PATH=/tmp/py39-only-fake:$PATH bin/swarm-telemetry --help` where the fake path has a python3 symlink to python3.9; shim exits 1 with upgrade message. (If the runner's host doesn't have Python 3.9, skip the runtime test and document that the gate logic is in `bin/_lib/python-bootstrap.sh` with the version parse matching common outputs.)
- `python3 -c "from swarm_do.telemetry import registry, jsonl, ids, schemas, cli"` imports clean.
- `python3 -c "from swarm_do.telemetry.ids import new_ulid; import re; assert re.fullmatch(r'^[0-9A-HJKMNP-TV-Z]{26}$', new_ulid())"` exits 0 in 100 invocations.
- `python3 -m unittest discover -s swarm-do/py/swarm_do/telemetry/tests -v` passes.
- `bin/swarm-telemetry.legacy --test` still runs the existing bash self-tests (legacy preserved).

**Anti-pattern guards:**
- Do NOT migrate any subcommand implementation in Phase 1. `cli.py` dispatches every subcommand to the legacy script via subprocess. Subcommand migration is Phase 3.
- Do NOT delete the legacy bash implementation — Phase 3 needs it for byte-parity tests. Rename to `.legacy` so nobody invokes it directly except the parity harness.
- Do NOT add third-party deps. `jsonschema`, `pydantic`, `click` are all forbidden.
- Do NOT hardcode the plugin root path in any Python module. Resolve via `pathlib.Path(__file__).parents[N]` with a `PLUGIN_ROOT` constant in one place (likely `registry.py`).
- Do NOT omit the `bin/_lib/python-bootstrap.sh` helper and copy the PYTHONPATH prepend into multiple shims — single source of truth.

---

### Phase 2: 9g close-out (complexity: simple, kind: feature)

**Objective:** Close Phase 9 by landing the retention ADR, shipping a full atomic-rewrite `purge` subcommand in Python (using Phase 1's foundation), and tracking the 9b-claude deferral as a first-class bead.

**What to implement:**
- `swarm-do/docs/adr/0001-telemetry-retention.md` per plan.md §Phase 9g. Name specific retention windows per ledger (not "TBD"), identify ≥3 PII/secret classes (candidates: repo paths in findings.summary; diff snippets in review.notes; CLI argv captured in runs.argv — but decide concretely in the ADR), document cross-repo sensitivity tiers.
- `swarm-do/py/swarm_do/telemetry/subcommands/__init__.py`.
- `swarm-do/py/swarm_do/telemetry/subcommands/purge.py` — reads retention default from the ADR via a dict literal in this module (document the dict as "source-of-truth pointer to ADR 0001"; updating requires a matching ADR revision). Subcommand signature: `swarm telemetry purge --older-than Nd [--ledger <name>]`. Scan each ledger via `jsonl.stream_read`, filter rows by `timestamp_start` (or ledger-specific timestamp field — registry carries it), write remainder via `jsonl.atomic_write`. Report rows removed per ledger to stdout.
- Wire `purge` into `py/swarm_do/telemetry/cli.py` — a real Python dispatch, not a passthrough to legacy (legacy has no `purge` subcommand).
- File beads issue titled "9b-claude: Claude-reviewer findings extractor" type=task, with description citing `swarm-do/bin/extract-phase.sh:19-20` and the Phase 4 handoff plan.

**Verify:**
- `swarm-do/docs/adr/0001-telemetry-retention.md` exists; `grep -i "tbd\|todo" swarm-do/docs/adr/0001-telemetry-retention.md` returns zero hits.
- On a synthetic fixture with rows dated `NOW - 30d`, `NOW - 60d`, `NOW - 120d`: `swarm telemetry purge --older-than 90d --ledger runs` removes only the 120-day row; `wc -l` before/after matches expected delta; original file's content pre-rename is untouched (check inode mtime before and after — the atomic rename creates a new inode).
- Fault injection: wrap `atomic_write` with a `os.kill(pid, SIGKILL)` midway through the tempfile write; assert the original ledger is intact and the tempfile is either absent or unreferenced.
- `bd list --state open` shows the 9b-claude bead.
- `swarm telemetry purge --older-than 0d` (all rows expire) on an empty ledger: exit 0, no error.

**Anti-pattern guards:**
- Do NOT use in-place edit (read→filter→write to same path) — atomicity requires tempfile + rename.
- Do NOT hardcode retention values in the Python outside the module-level dict that points to the ADR.
- Do NOT invoke `purge` from the swarm-run invocation path (not a per-run operation; operator-invoked only).
- Do NOT skip creating the 9b-claude bead — without it, the deferral in `extract-phase.sh:19-20` remains invisible.

---

### Phase 3: Telemetry subcommand migration (complexity: hard, kind: refactor)

**Objective:** Move all six legacy bash+Python-heredoc subcommands into the Python package, behind per-subcommand byte-parity tests, and delete the legacy bash implementation when every subcommand has proven parity.

**What to implement (in strict order — each step writes fixture + parity test BEFORE the migration):**
1. `dump` → `py/swarm_do/telemetry/subcommands/dump.py` (streaming read; simplest — port first to establish the package pattern).
2. `validate` → `subcommands/validate.py` (uses `schemas.py` from Phase 1; the existing legacy Python heredoc at legacy:194-349 is the reference).
3. `query` → `subcommands/query.py` (SQL-ish queries; port legacy:408-497).
4. `report` → `subcommands/report.py` (heaviest aggregation; port legacy:531-702).
5. `sample-for-adjudication` → `subcommands/sample_for_adjudication.py` (port legacy:796-1026; stratified random sampling).
6. `join-outcomes` → `subcommands/join_outcomes.py` (port legacy:1092-1578; `gh api` + `git log` correlation; heaviest).

For each subcommand, the migration commit contains: (a) a checked-in synthetic fixture in `py/swarm_do/telemetry/tests/fixtures/<subcommand>/`, (b) a parity test in `test_<subcommand>_parity.py` that runs BOTH legacy bash and the new Python subcommand against the fixture and asserts byte-equal stdout, (c) the Python implementation, (d) the `cli.py` dispatch swap from legacy-passthrough to native Python.

After all six are migrated and parity tests pass: delete `bin/swarm-telemetry.legacy`; `bin/swarm-telemetry` becomes the ~10-line shim defined in Phase 1 only.

**Verify:**
- For each of the 6 subcommands: parity test exits 0 on the fixture (legacy output byte-equal to Python output).
- `bin/swarm-telemetry --test` still runs; discovers tests under `py/swarm_do/telemetry/tests/` and under any preserved bash self-test path until legacy is removed.
- After legacy removal: `wc -l bin/swarm-telemetry` is < 15 (pure shim).
- `runs.schema.json` pattern for `run_id` can now be tightened back to `^[0-9A-HJKMNP-TV-Z]{26}$` because `ids.new_ulid()` is the canonical generator — verify swarm-run's append path picks up the new generator (if still in bash, schedule as a follow-up; if migrated in this phase, assert the new rows validate against the tight pattern).
- `diff_size_bytes` in runs.jsonl rows is no longer null for commits with a diff (closes `mstefanko-plugins-1zv`); verify against a synthetic run.
- `timestamp_end.type` is `["string", "null"]` in the regenerated schema (closes `mstefanko-plugins-rgb`).

**Anti-pattern guards:**
- Do NOT skip the parity test for any subcommand ("output looks close enough" is how drift gets committed).
- Do NOT migrate multiple subcommands in a single commit — one commit per subcommand so revert granularity is per-subcommand.
- Do NOT delete the legacy bash until all six parity tests pass.
- Do NOT introduce new CLI flags during migration; parity means parity. New features are separate PRs after this lands.
- Do NOT couple Phase 10e schema extension (preset_name / pipeline_name / pipeline_hash) into this phase — that work lives in Phase 10e on top of this refactor.

---

### Phase 4: Extractors + 9b-claude (complexity: moderate, kind: feature)

**Objective:** Move findings extraction from `bin/extract-phase.sh` (codex-only) into the Python package, add the Claude-reviewer extractor that 9b deferred, and convert `bin/extract-phase.sh` to a compatibility shim.

**What to implement:**
- `swarm-do/py/swarm_do/telemetry/extractors/__init__.py` — argparse entrypoint dispatching to per-reviewer extractors.
- `swarm-do/py/swarm_do/telemetry/extractors/codex_review.py` — port of the current `extract-phase.sh` codex-review handler. Same `stable_finding_hash_v1` algorithm (sha256 of `{file_normalized, category_class, line_start/10, normalized_summary_tokens}`); same path normalization (symlink resolve → worktree prefix strip → canonical form).
- `swarm-do/py/swarm_do/telemetry/extractors/claude_review.py` — NEW. Parses `agent-review` and `agent-code-review` notes (bd-issue notes format: Markdown with structured sections per the role files). Emits one `findings.jsonl` row per flagged item, sharing the same stable-hash algorithm as codex_review.py so equivalent findings across backends dedup cleanly.
- `swarm-do/bin/extract-phase.sh` becomes a shim: sources `bin/_lib/python-bootstrap.sh`, `exec python3 -m swarm_do.telemetry.extractors "$@"`. Prior bash body preserved as `.legacy` for the duration of Phase 4's parity verification, then deleted at phase close.
- Close the 9b-claude bead filed in Phase 2 on successful verification.

**Caller audit (required):** grep all of `swarm-do/bin/*`, `swarm-do/skills/*`, `swarm-do/hooks/*`, and `swarm-do/plugin.json` for references to `extract-phase.sh`. Every caller must continue invoking the bash shim with unchanged flags. If any caller sources the script (rather than exec'ing it), rewrite that caller to use the shim interface before deleting the legacy bash.

**Verify:**
- Codex parity: run `extract-phase.sh.legacy` and `bin/extract-phase.sh` on the same pinned fixture (pre-recorded codex review output); byte-equal findings.jsonl rows.
- Claude extractor: fixture = synthetic `agent-review` notes blob with 3 flagged items. Extractor emits 3 findings.jsonl rows. Stable hash of each row equals what codex_review.py would emit if given an equivalent codex-format input (prove with a side-by-side fixture pair covering one identical finding).
- Caller audit output: listed in the phase notes, with confirmation that each caller still works (manual smoke-test per caller or a scripted invocation).
- 9b-claude bead is closed (`bd show <id>` state=closed with a "merged in phase-4" note).

**Anti-pattern guards:**
- Do NOT change the `stable_finding_hash_v1` algorithm during the port. Phase 10a can introduce `_v2` via an algorithm bump; here is parity only.
- Do NOT change file path normalization (symlink / worktree prefix / canonicalization). Breaking this breaks cross-run dedup silently.
- Do NOT add new categories, severities, or reviewer roles beyond codex/claude in this phase.
- Do NOT delete the legacy bash until the codex parity test passes AND every caller audit item is confirmed.
- Do NOT ship the Claude extractor without a matching fixture + test — an untested extractor writing to the finding ledger corrupts future sampler/adjudication runs.

---

### Phase 5: Role spec unification (complexity: moderate, kind: refactor)

**Objective:** Collapse the dual `agents/` + `roles/*/shared.md` trees into a single canonical `role-specs/` source with generated outputs. Rename the Phase-0 codex-review persona so it no longer collides with the pipeline reviewer role.

**What to implement:**
- `swarm-do/role-specs/agent-<role>.md` — 14 files, one per role currently in `agents/`. Content structure: frontmatter (`name`, `description`, `consumers` = list of `{agents,roles-shared}`), role body. The generator transforms a single spec into both `agents/agent-<role>.md` and `roles/<role>/shared.md` (where applicable).
- `swarm-do/py/swarm_do/roles/__init__.py`.
- `swarm-do/py/swarm_do/roles/cli.py` — argparse with subcommands `gen --write`, `gen --check`, `gen readme-section`, `list`.
- `swarm-do/py/swarm_do/roles/spec.py` — reads + validates role-specs, returns typed objects.
- `swarm-do/py/swarm_do/roles/render.py` — `to_agents_md(spec)`, `to_shared_md(spec)` rendering functions. Every rendered output starts with `<!-- generated from role-specs/agent-<role>.md — do not edit -->`.
- `swarm-do/py/swarm_do/roles/variants.py` — placeholder (Phase 10g will populate).
- `swarm-do/py/swarm_do/roles/tests/` — fixtures + `test_spec_parser.py`, `test_renderers.py`, `test_roundtrip.py` (spec → render → parse → identical contract).
- Rename split: `role-specs/agent-codex-review.md` = pipeline reviewer (current `roles/agent-codex-review/shared.md` content semantics). `role-specs/agent-codex-review-phase0.md` = Phase-0 blinded-adjudication persona (current `agents/agent-codex-review.md` content semantics).
- Update `swarm-do/bin/codex-review-phase:19` to resolve `agent-codex-review-phase0` (verify current line number — may drift as the file evolves).
- Run `python -m swarm_do.roles gen --write` and commit the regenerated `agents/` and `roles/*/shared.md` outputs. Every generated file carries the top-of-file stamp.

**Verify:**
- `python -m swarm_do.roles gen --check` exits 0.
- Roundtrip test for every role: `spec.parse(render.to_agents_md(spec.load(path))) == spec.load(path)` (contract invariants; not byte-equal since render emits canonical form).
- `bin/codex-review-phase agent-codex-review-phase0 <args>` successfully loads the Phase-0 persona content and invokes `codex exec --json` (or the dry-run equivalent if codex CLI absent on the host).
- `bin/load-role.sh agent-codex-review` still returns a valid role body (now generated from the pipeline spec).
- `bin/swarm-run` spawning agent-codex-review reads the generated `roles/agent-codex-review/shared.md`; prompt_bundle_hash output by `hash-bundle.sh agent-codex-review claude` is stable across identical generator invocations.
- No orphaned files under `roles/` or `agents/` that don't map to a role-spec.

**Anti-pattern guards:**
- Do NOT edit generated files by hand. The stamp + CI drift check + human discipline together enforce this.
- Do NOT generate `roles/<role>/claude.md` or `codex.md` overlays — those stay hand-authored (they are small adapters on top of `shared.md`, not restatements of the role).
- Do NOT skip the codex-review rename — leaving the collision is the exact drift-vector problem this phase exists to fix.
- Do NOT introduce variant files in this phase (Phase 10g territory; `variants.py` is a placeholder here).
- Do NOT forget to update `bin/codex-review-phase` — a rename-without-caller-update breaks the Phase 0 harness silently.

---

### Phase 6: Contract-doc generation (complexity: simple, kind: refactor)

**Objective:** Regenerate all contract-level docs (schemas/telemetry/README.md, README.md sections listed in Part 4.5 of the plan) from the registry and role-specs. Commit the generated output. Install the drift check so future phases can't introduce silent restated content.

**What to implement:**
- `swarm-do/py/swarm_do/telemetry/gen.py` — subcommands `docs --write/--check`, `readme-section --write/--check`. Emits output bounded by `<!-- BEGIN: generated-by swarm_do.telemetry.gen <subcmd> -->` / `<!-- END: ... -->` markers. Refuses to write outside its own markers; scans only inside them for `--check`.
- `py/swarm_do/roles/cli.py` grows `gen readme-section --write/--check` (same marker scheme; generates the Roles inventory table in `swarm-do/README.md`).
- Regenerate and commit:
  - `swarm-do/schemas/telemetry/README.md` (full file — marker covers the contract sections; narrative preamble stays hand-authored between markers).
  - `swarm-do/README.md` "Telemetry commands" section (marker-bounded).
  - `swarm-do/README.md` "Roles" section (marker-bounded).
- Install drift check: add a `--check-docs` flag to `bin/swarm-telemetry --test` that runs the four `--check` commands listed in the plan's Part 5 verification item 6. Exit non-zero on any drift.

**Verify:**
- `python -m swarm_do.telemetry.gen docs --check` exits 0.
- `python -m swarm_do.telemetry.gen readme-section --check` exits 0.
- `python -m swarm_do.roles gen --check` exits 0.
- `python -m swarm_do.roles gen readme-section --check` exits 0.
- Manually edit a generated line in `schemas/telemetry/README.md` inside the markers; `--check` fails with a clear diff message. Revert.
- Manually edit narrative text OUTSIDE the markers in `schemas/telemetry/README.md`; `--check` still passes. Revert.
- `bin/swarm-telemetry --test --check-docs` exits 0 on clean tree.

**Anti-pattern guards:**
- Do NOT write generated content outside the BEGIN/END markers. The generator must refuse; a human who bypasses with a text editor gets caught by `--check`.
- Do NOT duplicate field names / ledger names / subcommand lists into narrative prose outside the markers. Any contract-level content inside narrative is new drift surface; keep it inside markers or delete it.
- Do NOT generate ADRs or the plan file — those are authoritative narrative, not contract docs.
- Do NOT skip installing `--check-docs` on `--test`; without it, the next phase can land drift without CI.
