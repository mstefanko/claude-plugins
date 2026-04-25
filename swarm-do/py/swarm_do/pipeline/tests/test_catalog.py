from __future__ import annotations

import unittest

from swarm_do.pipeline.catalog import (
    compile_prompt_variant_fan_out,
    discover_prompt_variant_files,
    explain_lens_incompatibility,
    get_lens,
    get_module,
    list_modules,
    list_pipeline_profiles,
    list_prompt_lenses,
    list_route_lenses,
    pipeline_activation_error,
    pipeline_profile_for,
)
from swarm_do.pipeline.registry import find_pipeline, load_pipeline


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
        self.assertGreaterEqual(
            set(scanned["agent-analysis"]),
            {"explorer-a", "explorer-b", "explorer-c", "security-threat-model"},
        )
        self.assertGreaterEqual(
            set(scanned["agent-research"]),
            {"prior-art-search", "codebase-map", "risk-discovery"},
        )
        self.assertGreaterEqual(
            set(scanned["agent-review"]),
            {"correctness-rubric", "api-contract", "security-threat-model", "performance-review", "edge-case-review"},
        )
        self.assertEqual(get_lens("state-data").variant_name, "explorer-c")

    def test_phase3_lenses_compile_to_role_specific_prompt_variants(self) -> None:
        research = compile_prompt_variant_fan_out(
            "agent-research",
            ["codebase-map", "prior-art-search", "risk-discovery"],
        )
        self.assertEqual(research["variants"], ["codebase-map", "prior-art-search", "risk-discovery"])

        analysis_security = compile_prompt_variant_fan_out("agent-analysis", ["security-threat-model"])
        self.assertEqual(analysis_security["variants"], ["security-threat-model"])

        review = compile_prompt_variant_fan_out(
            "agent-review",
            ["correctness-rubric", "api-contract", "security-threat-model", "performance-review", "edge-case-review"],
        )
        self.assertEqual(
            review["variants"],
            ["correctness-rubric", "api-contract", "security-threat-model", "performance-review", "edge-case-review"],
        )
        self.assertIn("agent-review output schema", get_lens("api-contract").output_contract_for_role("agent-review").schema_rule)

    def test_module_and_route_catalogs_include_mco_gating(self) -> None:
        module_ids = {module.module_id for module in list_modules()}
        self.assertIn("mco-review", module_ids)
        self.assertTrue(get_module("mco-review").experimental)
        self.assertTrue(get_module("mco-review").requires_provider_doctor)
        self.assertIn("fan-out-model-routes", {lens.lens_id for lens in list_route_lenses()})

    def test_pipeline_profiles_mark_research_runnable_and_unknown_output_only_preview(self) -> None:
        profiles = {profile.profile_id: profile for profile in list_pipeline_profiles()}
        self.assertEqual(profiles["research"].command_name, "/swarm-do:research")
        self.assertFalse(profiles["research"].preview_only)

        research = load_pipeline(find_pipeline("research").path)
        self.assertEqual(pipeline_profile_for("research", research).profile_id, "research")
        self.assertIsNone(pipeline_activation_error("research", research))

        preview_only = {
            "pipeline_version": 1,
            "name": "review-only",
            "stages": [{"id": "review", "agents": [{"role": "agent-review"}]}],
        }
        self.assertEqual(pipeline_profile_for("review-only", preview_only).profile_id, "preview-only")
        self.assertIn("preview-only", pipeline_activation_error("review-only", preview_only) or "")


if __name__ == "__main__":
    unittest.main()
