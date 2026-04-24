# Review notes for issue-42

## Review

### Verdict: NEEDS_CHANGES

### Checks Run
- pytest: 3 failed, 87 passed
- ruff check: clean

### Issues Found
1. internal/api/foo.go:42 — Window uses exclusive upper bound causing off-by-one
2. pkg/parse/token.go:100-120 — Returns nil without checking error path
3. cmd/cli/main.go:7 — Missing context propagation on subprocess spawn

### Production Risk
Backpressure not tested under sustained load.

## Status: COMPLETE
