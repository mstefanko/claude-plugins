from __future__ import annotations

import unittest

from swarm_do.pipeline.catalog import (
    compile_prompt_variant_fan_out,
    discover_prompt_variant_files,
    explain_lens_incompatibility,
    get_lens,
    get_module,
    list_modules,
    list_prompt_lenses,
    list_route_lenses,
)


class PipelineCatalogTests(unittest.TestCase):
    def test_ultra_plan_lenses_map_stable_ids_to_existing_variants(self) -> None:
        lenses = {lens.lens_id: lens for lens in list_prompt_lenses(role="agent-analysis", stage_kind="fan_out")}

        self.assertEqual(lenses["architecture-risk"].variant_name, "explorer-a")
        self.assertEqual(lenses["api-contract"].variant_name, "explorer-b")
        self.assertEqual(lenses["state-data"].variant_name, "explorer-c")
        for lens in lenses.values():
            self.assertIsNotNone(lens.variant_file)
            self.assertTrue(lens.variant_file.is_file())
            self.assertEqual(lens.execution_mode, "fan_out_only")
            self.assertIn("Preserve the agent-analysis output schema", lens.output_contract.schema_rule)

    def test_lens_metadata_compiles_to_current_prompt_variant_fan_out_shape(self) -> None:
        fan_out = compile_prompt_variant_fan_out(
            "agent-analysis",
            ["architecture-risk", "api-contract", "state-data"],
        )

        self.assertEqual(
            fan_out,
            {
                "role": "agent-analysis",
                "count": 3,
                "variant": "prompt_variants",
                "variants": ["explorer-a", "explorer-b", "explorer-c"],
            },
        )

    def test_catalog_explains_v1_prompt_lens_limitations(self) -> None:
        agents_reason = explain_lens_incompatibility("architecture-risk", role="agent-analysis", stage_kind="agents")
        merge_reason = explain_lens_incompatibility("architecture-risk", role="agent-analysis", stage_kind="merge")

        self.assertIn("fan-out-only", agents_reason or "")
        self.assertIn("merge schema has no variant", merge_reason or "")

    def test_scanned_variants_are_enriched_by_typed_lenses(self) -> None:
        scanned = discover_prompt_variant_files()
        self.assertEqual(set(scanned["agent-analysis"]), {"explorer-a", "explorer-b", "explorer-c"})
        self.assertEqual(get_lens("state-data").variant_name, "explorer-c")

    def test_module_and_route_catalogs_include_mco_gating(self) -> None:
        module_ids = {module.module_id for module in list_modules()}
        self.assertIn("mco-review", module_ids)
        self.assertTrue(get_module("mco-review").experimental)
        self.assertTrue(get_module("mco-review").requires_provider_doctor)
        self.assertIn("fan-out-model-routes", {lens.lens_id for lens in list_route_lenses()})


if __name__ == "__main__":
    unittest.main()
