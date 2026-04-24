# role-specs/

Canonical source for all swarm-do agent role definitions (15 roles).

Each `agent-<name>.md` file contains YAML frontmatter (`name`, `description`,
`consumers`) followed by the role's prompt body.  The `consumers` field
controls which output files are generated:

- `agents`       → `swarm-do/agents/agent-<name>.md`
- `roles-shared` → `swarm-do/roles/agent-<name>/shared.md`

**Edit here, never in the generated outputs.**  After editing, regenerate:

```
python3 -m swarm_do.roles gen --write
```

Use `--check` (no `--write`) to verify no drift without modifying files.
