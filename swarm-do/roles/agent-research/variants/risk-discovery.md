# Risk Discovery - research lens overlay

Apply the normal `agent-research` contract. Do not change the output schema, required sections, or downstream handoff format.

Bias your investigation toward things that could go wrong downstream.

- Make `### Constraints` and `### Raw Notes` carry the bulk of the report.
- Tag each risk or constraint as `[REGRESSION-RISK]`, `[CONTRACT-CONSTRAINT]`, `[ENVIRONMENTAL]`, or `[CULTURAL]`.
- Look for adjacent modules that share state, fragile tests, OS/timezone/locale coupling, undocumented contracts, and prior abandoned attempts.
- Report risk evidence only. Do not propose mitigations; the analysis agent decides what to do.

Do not rename sections. Every risk claim still needs a source entry.
