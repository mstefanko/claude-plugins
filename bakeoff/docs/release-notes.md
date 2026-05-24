# Bakeoff Release Notes

## Unreleased

- Build judge failures now exit `4` (`decision_incomplete`) instead of generic
  runtime failure. Provider artifacts are durable, but there is no selected
  patch unless `decision.json.canonical_winner` is non-null. Scripts should
  handle exit `4` by inspecting `decision.json`, `report.md`, and
  `diagnostics.json`.
