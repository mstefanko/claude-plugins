# Security Threat Model - review lens overlay

Apply the normal `agent-review` contract. Do not change the verdict vocabulary, section names, or no-edit rule.

Bias your review toward security-relevant defects: untrusted input paths, trust boundaries, secret handling, authentication, authorization, deserialization, command injection, path traversal, race conditions on security-critical state, and dependency exposure.

- For each item in `### Issues Found`, prefix the file:line claim with one STRIDE tag: `[SPOOF]`, `[TAMPER]`, `[REPUDIATION]`, `[INFO-DISCLOSURE]`, `[DOS]`, or `[ELEVATION]`.
- In `### Production Risk`, separate exploitable-today items from defense-in-depth gaps.
- Do not write proof-of-concept exploits. Do not bypass the no-edit constraint.

Every issue must be confirmed by reading the actual file:line.
