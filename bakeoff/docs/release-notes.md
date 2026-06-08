# Bakeoff Release Notes

## Unreleased

- Build judge failures now exit `4` (`decision_incomplete`) instead of generic
  runtime failure. Provider artifacts are durable, but there is no selected
  patch unless `decision.json.selected_patch_provider` or legacy
  `decision.json.canonical_winner` is non-null. Scripts should handle exit `4`
  by inspecting `decision.json`, `report.md`, and `diagnostics.json`.
- Work orders now support `run_mode: "single_provider"` with exactly one
  provider. Single-provider runs skip the judge, emit
  `single_provider_result` or `single_provider_failed`, leave
  `canonical_winner` null, and expose selected build patches through
  `selected_patch_provider`.
