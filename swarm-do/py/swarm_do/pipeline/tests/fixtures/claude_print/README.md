Real `claude -p --output-format json` fixtures must be committed here before
the `claude-print` phase launcher can become eligible.

Required fixture shapes:

- successful phase run
- failed phase run
- blocked or needs-input phase run

Unit tests may use fake runner output, but the production capability probe keeps
`claude-print` ineligible until these real samples exist.
