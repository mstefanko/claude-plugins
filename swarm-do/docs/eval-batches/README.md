# Eval Batch Manifests

Use this directory for controlled dogfood comparison manifests referenced by
`docs/eval-recipes.md`. A batch is promotion evidence only when the manifest and
telemetry report together identify the compared arms, the source data, and the
manual safety observations.

Minimum manifest shape:

```markdown
# Prepare Gate Batch YYYY-MM

## Scope

- Batch id:
- Date range:
- Operator:
- Repo(s):
- Purpose:

## Arms

| Arm | Variant label | Description | Config or preset |
|---|---|---|---|
| A | `prep6.example.a` |  |  |
| B | `prep6.example.b` |  |  |

## Phases

| Phase id | Beads issue | Repo | Base SHA | Kind | Complexity | Risk tags | Worktree A | Worktree B | Included | Exclusion reason |
|---|---|---|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |  | yes |  |

## Manual Safety Notes

| Phase id | Arm | Operator interventions | Plan-review minutes | Missed docs fix | Spec/review mismatch notes |
|---|---|---:|---:|---|---|
|  |  |  |  | no |  |

## Report Commands

```bash
bin/swarm-telemetry experiment-report --batch <batch-id>
```

## Decision

- Decision: HOLD | PROMOTE | ROLLBACK
- Reason:
- Unknown safety metrics:
```

Rules:

- Paired arms must start from the same base SHA in isolated worktrees or clones.
- Rows with null phase kind or complexity do not count toward controlled
  comparison totals.
- Exclusions must stay visible in the manifest.
- Manual safety notes are required even when telemetry captures the matching
  automated signal.
