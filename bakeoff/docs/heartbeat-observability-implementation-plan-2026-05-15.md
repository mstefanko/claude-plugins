# Heartbeat Observability for Bakeoff - Superseded Plan

Date: 2026-05-15
Status: superseded by
`docs/operator-ux-dogfood-tightening-implementation-plan-2026-05-15.md`

The heartbeat observability work has been folded into the operator-UX dogfood
tightening plan so prompt discipline, heartbeat telemetry, Codex output capture,
output-cap behavior, CLI recovery wording, reports, triage surfaces, tests, and
README updates have one active implementation plan.

Use the consolidated plan for implementation. In particular, it now owns:

- heartbeat formatting with separate retained `out` and `err` byte counts
- quiet-provider messaging that is explicitly subprocess telemetry, not semantic
  model progress
- Codex final-message capture via `--output-last-message` when available
- deferral of raw stdout/stderr snippet streaming until tail buffering,
  sanitization, and redaction are designed

This file remains only as a pointer to avoid two overlapping active specs.
