# Edge Case Review - review lens overlay

Apply the normal `agent-review` contract. Do not change the verdict vocabulary, section names, or no-edit rule.

Bias your review toward edge cases: null, empty, single-element, off-by-one, overflow, timezone ambiguity, unicode normalization, and concurrency boundaries.

- For each item in `### Issues Found`, tag it `[NULL]`, `[OFF-BY-ONE]`, `[BOUNDARY]`, `[EMPTY]`, `[OVERFLOW]`, `[TIME-ZONE]`, or `[UNICODE]`.
- Name the concrete input or state that triggers the failure.
- In `### Production Risk`, explain whether the edge is likely in normal operation or only in rare recovery/import/migration paths.

Drop any concern that cannot be expressed as a concrete failing input.
