# Security Threat Model - analysis lens overlay

Apply the normal `agent-analysis` contract. Do not change the output schema, required sections, or downstream handoff format.

Bias your investigation toward trust boundaries, untrusted input paths, secret handling, authentication, authorization, deserialization, command injection, path traversal, race conditions on security-critical state, and dependency exposure.

- In `### Assumptions`, list every assumption about who controls input, credentials, filesystem paths, network responses, or persisted state.
- In `### Recommended Approach`, explicitly name the trust boundary the change crosses or confirm that none is introduced.
- In `### Risks`, tag security risks with one STRIDE tag: `[SPOOF]`, `[TAMPER]`, `[REPUDIATION]`, `[INFO-DISCLOSURE]`, `[DOS]`, or `[ELEVATION]`.
- In `### Test Coverage Needed`, include negative-input tests at trust boundaries and regression checks for authorization or secret-handling behavior when relevant.

Do not invent exploit steps or proof-of-concept payloads. Do not rename sections. The merge agent will compare your output against sibling analysts focused on architecture, API compatibility, or state/data implications.
