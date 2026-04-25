# Codebase Map - research lens overlay

Apply the normal `agent-research` contract. Do not change the output schema, required sections, or downstream handoff format.

Bias your investigation toward an exhaustive map of the affected subsystem.

- Make `### Relevant Files` the dominant section.
- Tag each file's role in the system: `[ENTRY-POINT]`, `[CONFIG]`, `[HOT-PATH]`, `[TEST]`, `[FIXTURE]`, or `[GENERATED]`.
- Use Grep and Glob to find entry points, config files, tests, fixtures, generators, and role/pipeline integration points.
- In `### Existing Patterns`, summarize cross-module conventions the writer must follow.

Do not evaluate or recommend changes. Your value is complete surface-area mapping with file:line citations.
