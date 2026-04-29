These fixtures preserve the raw outer shape expected from
`claude -p --output-format json` while redacting machine-specific content.

Redactions:

- Absolute run directories are replaced with `<RUN_DIR>`.
- Session ids use stable synthetic values.
- Prompt text is omitted; parser tests only need the outer JSON envelope and the
  artifact status/path object returned by the phase worker.

The capability probe parses every fixture and normalizes the result/handoff
paths without contacting Claude.
