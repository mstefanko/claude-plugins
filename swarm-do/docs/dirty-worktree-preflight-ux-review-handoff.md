# Dirty Worktree Preflight UX Review Handoff

Date: 2026-05-01

## Problem

Prepared phase-session launches were blocked by any dirty source checkout path
under the project subdir, except copied run artifacts. In normal dogfood use,
agents and operators frequently leave documentation, ADRs, plan files, and
other review artifacts dirty. That made the safe-worktree preflight too rigid:
the usual recovery path was to commit the files, rerun dispatch, then hit a
second failure because the prepared artifact's `git_base_sha` no longer matched
the new `HEAD`.

The practical goals were:

- Do not block on unrelated dirty Markdown or planning files.
- Still block if dirty source files overlap the phase work the run is about to
  perform.
- Preserve prepared dirty plan content inside the safe worktree.
- Allow two independent prepared plans to coexist when their declared work
  scopes do not overlap.
- Keep the `git_base_sha` gate explicit. Base drift still requires an operator
  to inspect and run `bin/swarm prepare refresh-base <run-id>` or re-prepare.

## Current Patch

Files changed:

- `py/swarm_do/pipeline/execution_worktree.py`
- `py/swarm_do/pipeline/tests/test_execution_worktree.py`

### Safe-worktree dirty source policy

`resolve_run_execution_worktree()` now derives `source_dirty_block_patterns`
from prepared work-unit `allowed_files`, legacy `files`, and `context_files`.

`_assert_clean_source_project()` still reads `git status --porcelain=v1 -z
--untracked-files=all -- <project-subdir>`, but it now blocks only when a dirty
path overlaps those prepared run patterns. Dirty copied artifacts are still
ignored as before.

Effect:

- Dirty `planning/notes.md` does not block a run scoped to `docs/new.md`.
- Dirty `docs/new.md` still blocks that run.
- Dirty `docs/helper.md` also blocks that run because it is in the parent
  directory of the declared target and may be undeclared context.
- This is not a blanket `.md` allowlist. It is scope-based, so dirty Markdown
  that is actually in the run's allowed/context scope still blocks.

Ignored source dirty paths are now exposed in the safe-worktree launch metadata
as `source_dirty_ignored_paths`. That makes under-declared context visible in
`phase_launches/<phase>/attempt-*/command.json` without stopping independent
work.

### Source plan overlay

The safe worktree now copies `source_plan_path` as an artifact with kind
`source_plan`. This matters when the prepared artifact was intentionally created
from an uncommitted plan file: the launcher worktree must see the same source
plan bytes that prepare verified.

To avoid corrupting adoption behavior, `source_plan` is not treated as a normal
repo-visible run artifact. It is ignored in dirty/status/adoption checks only
while the safe-worktree copy still matches the SHA copied at launch. If a writer
edits the plan in the safe worktree, it becomes a real change again.

### Base drift remains an explicit gate

This patch does not auto-refresh `git_base_sha` during dispatch. A prior draft
did, but review correctly flagged that as eroding the operator-approved base
gate. If `verify_prepared_for_dispatch()` returns only `git_base_sha` drift,
the operator still decides whether to run:

```sh
bin/swarm prepare refresh-base <run-id>
```

or to re-prepare after inspecting the committed diff between the prepared base
and current `HEAD`.

## Why This Shape

The old policy was safe but too coarse. Blocking on all dirty files avoided
silent omission from the safe worktree, but it also made unrelated review and
planning work stop real phase execution.

The new policy keeps the important safety property: dirty files that the run
may read or write still block. Sibling files in the same declared directory
also block to catch common under-declared helper/context edits. Unrelated dirty
files are allowed because they are neither copied nor part of the prepared
scope, and they are listed in launch metadata for operator visibility.

The source-plan overlay handles the special case where a dirty plan file is not
an unrelated local edit, but the source input that was just prepared. Without
copying it, the safe worktree may contain the committed old plan while
`prepared_plan.v1.json` describes the dirty new plan.

## Reviewer Focus

Please review these areas closely:

- Scope matching in `_source_dirty_path_overlaps_run_scope()`: confirm the
  exact-file, directory-prefix, glob, project-relative, and git-relative cases
  are correct for monorepo-subdir checkouts.
- Parent-directory blocking: confirm blocking same-directory siblings of
  declared files catches enough under-declared context without being too coarse.
- Visibility: confirm `source_dirty_ignored_paths` in launch metadata is the
  right surface, or decide whether CLI non-JSON output should also print it.
- The `source_plan` overlay lifecycle: unchanged copied source plans should not
  appear as adoption changes, but modified source plans should.
- Base drift UX: this patch intentionally leaves `git_base_sha` as a hard
  dispatch gate. A future opt-in command may inspect
  `git diff <old-base>..<HEAD> -- <prepared scope>` before refreshing, but that
  policy is not shipped here.
- Concurrency implications: separate run ids create separate safe worktrees.
  The source checkout dirty gate should now permit independent dirty plan/docs
  files when they do not overlap each run's declared file scope.

## Tests Run

Focused tests:

```sh
PYTHONPATH=py python3 -m unittest py.swarm_do.pipeline.tests.test_execution_worktree.ExecutionWorktreeTests py.swarm_do.pipeline.tests.test_prepare_artifact.PreparedArtifactWriterTests
```

Result: 52 tests passed.

Full pipeline tests:

```sh
PYTHONPATH=py python3 -m unittest discover py/swarm_do/pipeline/tests
```

Result: 618 tests passed, 2 skipped.

## Existing Unrelated Worktree State

The working tree also has an unrelated untracked path outside this plugin
subdir:

```text
? ../.swarm-do/worktrees/decomposer-fix
```

This patch did not touch or clean that path.
