# Codebase Map - research lens overlay

Apply the normal `agent-research` claim-first contract. Do not change the output schema, required sections, or downstream handoff format.

Bias your investigation toward an exhaustive map of the affected subsystem.

- Make `### Research Claims` the dominant section.
- Produce more `[required]` and `[helpful]` `R-###` file-map claims than a normal research pass.
- Tag each file-map claim with the file's role in the system when useful: `[ENTRY-POINT]`, `[CONFIG]`, `[HOT-PATH]`, `[TEST]`, `[FIXTURE]`, or `[GENERATED]`.
- Use Grep and Glob to find entry points, config files, tests, fixtures, generators, and role/pipeline integration points.
- Keep `### Relevant Files` as a compact index, not the main evidence carrier.
- Capture cross-module conventions as claim records with `analysis_need` and file:line evidence.

Do not evaluate or recommend changes. Your value is complete surface-area mapping with file:line citations.
