# Bakeoff Run Appendix

Optional templates and bulky tables for the `bakeoff-run` skill. Load only the
section needed for the active drafting state.

## Task-Fit Repair Menu

```text
This may not need Bakeoff because <reason>. A direct one-pass answer would
<direct evidence path>; do that outside Bakeoff if that is all you need.

If you still want Bakeoff, reply `draft anyway`.

Better Bakeoff shapes:
1. <label> - fixes <missing lens or decision>. Goal: <goal>. Output: <evidence/output shape>.
2. <label> - fixes <missing lens or decision>. Goal: <goal>. Output: <evidence/output shape>.
```

Show at most two rewrites and never show a third. Each rewrite must preserve
the user's intent and state what it fixes, the goal, and expected evidence.

## Split Proposal And Preview

```text
This looks like it cleanly splits into <N> independent Bakeoff work orders:

1. <part one goal>
2. <part two goal>
3. <part three goal>

Each can run separately with the same shared context, and none depends on
another result. Reply `split` to draft separate work orders, or tell me to keep
it as one.
```

```text
Draft work orders:
1. <part-1-id> (<type>) -> ./<base-id>.part-1.work-order.json
   Goal: <brief goal>
   Providers: <provider summary>; judge: <judge summary>
2. <part-2-id> (<type>) -> ./<base-id>.part-2.work-order.json
   Goal: <brief goal>
   Providers: <provider summary>; judge: <judge summary>

Files to write:
- ./<base-id>.part-1.work-order.json
- ./<base-id>.part-2.work-order.json

Commands to run:
- bakeoff <research|build> ./<base-id>.part-1.work-order.json ...
- bakeoff <research|build> ./<base-id>.part-2.work-order.json ...

Write these files and run them one after another? Reply `write and run` to
continue, reply `show` to print the full JSON, or tell me what to change.
```

For eligible non-build parallel splits, replace the last question with:

```text
Choose how to run them:

- `sequential` - write, validate, then run one after another.
- `parallel` - write, validate, then run all <N> at once.
- `show` - print the JSON before approving.

Parallel cost note: <N> runs x <provider-count> providers can launch up to
<N*provider-count> provider workers at once, followed by judge and any triage
phases. Child output will be captured per run, and `latest` will point to one
child run, not the group.
```

## Parallel Fanout Skeleton

```sh
tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/bakeoff-parallel.XXXXXX") || exit 1

start_child() {
  label=$1
  run_id=$2
  work_order=$3
  shift 3
  (
    "${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" research "$work_order" \
      --run-id "$run_id" "$@" --json --quiet
    printf '%s\n' "$?" > "$tmpdir/$label.exit"
  ) > "$tmpdir/$label.stdout" 2> "$tmpdir/$label.stderr" &
  printf '%s\n' "$!" > "$tmpdir/$label.pid"
}
```

Progress examples:

```text
parallel bakeoff: launched 3 runs
parallel bakeoff: running 3/3: architecture, security, ux
parallel bakeoff: completed security exit=0; running 2/3
parallel bakeoff: completed architecture exit=4; running 1/3
parallel bakeoff: completed ux exit=0; summarizing
```

## Multi-Lens Presets

| Lens slug | Synonyms and examples | Focus |
| --- | --- | --- |
| `correctness` | correctness, bugs, behavior, edge cases, error handling, data correctness | Changed behavior, edge cases, data correctness, and error handling. |
| `tests` | tests, test coverage, regression tests, missing tests, stale tests | Missing, misleading, or stale tests for changed behavior. |
| `security` | security, auth, authn, authz, injection, SQL injection, XSS, CSRF, secrets, data exposure, trust boundary | Concrete auth, injection, secrets, trust-boundary, and unsafe data-flow risks. |
| `performance` | performance, perf, latency, memory, resource use, scaling, database queries, N+1 | Changed hot paths, resource use, repeated work, avoidable I/O, and scaling risks. |
| `ux` | UX, frontend, UI, accessibility, a11y, copy, loading states, error states, responsive behavior | User-visible regressions, accessibility, copy/state mismatch, loading/error behavior. |
| `maintainability` | maintainability, readability, coupling, architecture risk, migration risk | Defect-prone structure, confusing ownership, fragile coupling, and migration risks. |
| `reliability` | reliability, resilience, concurrency, races, retries, timeouts, idempotency | Concurrency, retries, timeouts, idempotency, failure handling, and resilience risks. |

## Multi-Lens Preview

```text
This will run <N> separate review runs:

1. Security review
2. Performance review
3. UX/frontend behavior review

Each run asks the configured reviewers to inspect the same change from one
lens, then merges and verifies that lens's findings.

Cost note: this is about <N>x a normal review. With the configured
<budget-seconds> second budget, each lens can reserve up to about
<per-lens-minutes> minutes worst-case (reviewers, merge, verification). <N>
lenses can therefore reserve up to about <computed-total> minutes worst-case,
though typical runs may finish sooner.

Verification is on for each lens by default. Synthesis is not automatic; after
the runs finish I will summarize the lens results and ask whether you want one
prioritized fix plan.

Write, validate, and run these one after another? Reply `write and run`, reply
`show` to print the full JSON, or tell me what to change.
```

If `--no-triage` is set, omit verification from the estimate, state findings
will be raw and unverified, and count two phases instead of three. Provider
reviews run in parallel within a lens, so count one worker phase per lens.

## Multi-Lens Stop And Summary

On a stopped sequence, show completed lenses with run ids, report paths, and
triage states; the stopped lens with command, exit/failure, and artifacts;
remaining lenses; and whether a partial summary file was written. Ask:

```text
Continue with the remaining lenses? Reply `continue lenses`, or tell me what
to change.
```

Summary file layout:

```text
# Multi-Lens Review Summary

Summary file: <path>

## Runs
## Triage Counts
## Most Actionable
## Overlap
## Clean Lenses
## Caveats
## Next Commands
## Optional Synthesis
```
