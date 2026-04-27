from __future__ import annotations

import unittest
from pathlib import Path

from swarm_do.pipeline.recipes import (
    GraphStackSpec,
    NewPresetBuildResult,
    PresetRecipeSpec,
    RoutingPackageSpec,
    apply_graph_stack,
    build_blank_preset_draft,
    build_recipe_preset,
    get_graph_stack,
    get_preset_recipe,
    get_routing_package,
    list_graph_stacks,
    list_preset_recipes,
    list_routing_packages,
)
from swarm_do.pipeline.simple_yaml import load_yaml


# Repo layout: this test file lives at
# swarm-do/py/swarm_do/pipeline/tests/test_recipes.py
# parents[0]=tests, parents[1]=pipeline, parents[2]=swarm_do,
# parents[3]=py, parents[4]=swarm-do. Fixtures live at swarm-do/pipelines/.
_REPO_PIPELINES_DIR = Path(__file__).resolve().parents[4] / "pipelines"


_EXPECTED_RECIPE_IDS = {
    "balanced-default",
    "claude-only-diagnostic",
    "codex-only-fallback",
    "lightweight",
    "hybrid-review",
    "ultra-plan",
    "repair-loop",
    "smart-friend",
    "competitive-implementation",
    "research-memo",
    "brainstorm",
    "design-plan",
    "review-evidence",
    "strict-review-evidence",
}

_EXPECTED_STACK_IDS = {
    "default-implementation",
    "default-research",
    "default-design",
    "default-review",
}


class RecipeCatalogTests(unittest.TestCase):
    def test_list_preset_recipes_includes_every_required_recipe(self) -> None:
        ids = {spec.recipe_id for spec in list_preset_recipes()}
        self.assertEqual(_EXPECTED_RECIPE_IDS, ids)

    def test_recipe_specs_are_frozen_dataclasses(self) -> None:
        spec = list_preset_recipes()[0]
        self.assertIsInstance(spec, PresetRecipeSpec)
        with self.assertRaises(Exception):
            # frozen=True -> attribute assignment raises
            spec.recipe_id = "x"  # type: ignore[misc]

    def test_get_preset_recipe_round_trips(self) -> None:
        for spec in list_preset_recipes():
            self.assertIs(get_preset_recipe(spec.recipe_id), spec)

    def test_get_preset_recipe_unknown_raises_keyerror(self) -> None:
        with self.assertRaises(KeyError) as ctx:
            get_preset_recipe("does-not-exist")
        self.assertIn("does-not-exist", str(ctx.exception))

    def test_intent_is_implementation_or_output_only(self) -> None:
        for spec in list_preset_recipes():
            self.assertIn(spec.intent, {"Implementation", "Output-only"}, spec.recipe_id)


class RoutingPackageTests(unittest.TestCase):
    def test_list_routing_packages_returns_all_referenced_packages(self) -> None:
        package_ids = {pkg.package_id for pkg in list_routing_packages()}
        for spec in list_preset_recipes():
            self.assertIn(
                spec.default_routing_package_id,
                package_ids,
                f"{spec.recipe_id} default routing not registered",
            )

    def test_get_routing_package_round_trips(self) -> None:
        for pkg in list_routing_packages():
            self.assertIs(get_routing_package(pkg.package_id), pkg)
            self.assertIsInstance(pkg, RoutingPackageSpec)

    def test_get_routing_package_unknown_raises_keyerror(self) -> None:
        with self.assertRaises(KeyError):
            get_routing_package("nope")


class GraphStackTests(unittest.TestCase):
    def test_list_graph_stacks_has_required_ids_only(self) -> None:
        ids = {stack.stack_id for stack in list_graph_stacks()}
        self.assertEqual(_EXPECTED_STACK_IDS, ids)

    def test_get_graph_stack_round_trips(self) -> None:
        for stack in list_graph_stacks():
            self.assertIs(get_graph_stack(stack.stack_id), stack)
            self.assertIsInstance(stack, GraphStackSpec)

    def test_get_graph_stack_unknown_raises_keyerror(self) -> None:
        with self.assertRaises(KeyError):
            get_graph_stack("invented-stack")


class BuildRecipePresetTests(unittest.TestCase):
    def test_balanced_default_builds_user_preset_with_inline_pipeline(self) -> None:
        result = build_recipe_preset("balanced-default", "balanced-custom")
        self.assertIsInstance(result, NewPresetBuildResult)
        self.assertEqual(result.errors, ())
        preset = result.preset_mapping
        self.assertEqual(preset["origin"], "user")
        self.assertEqual(preset["name"], "balanced-custom")
        self.assertIn("pipeline_inline", preset)
        # NEVER reference a stock pipeline by name
        self.assertNotIn("pipeline", preset)
        # Pipeline name is overridden to the supplied preset name
        self.assertEqual(preset["pipeline_inline"]["name"], "balanced-custom")
        # routing was overridden by the default routing package
        self.assertIn("routing", preset)
        self.assertIn("budget", preset)

    def test_every_recipe_validates_without_errors(self) -> None:
        for spec in list_preset_recipes():
            result = build_recipe_preset(spec.recipe_id, f"{spec.recipe_id}-custom")
            self.assertEqual(
                result.errors,
                (),
                f"{spec.recipe_id} produced unexpected errors: {result.errors}",
            )
            self.assertEqual(result.preset_mapping["origin"], "user")
            self.assertNotIn("pipeline", result.preset_mapping)
            self.assertIn("pipeline_inline", result.preset_mapping)

    def test_description_defaults_to_display_name(self) -> None:
        spec = get_preset_recipe("balanced-default")
        result = build_recipe_preset("balanced-default", "balanced-custom")
        self.assertEqual(result.preset_mapping["description"], spec.display_name)

    def test_description_override_used_when_provided(self) -> None:
        result = build_recipe_preset(
            "balanced-default",
            "balanced-custom",
            description="My custom description",
        )
        self.assertEqual(result.preset_mapping["description"], "My custom description")

    def test_routing_package_override_replaces_routing(self) -> None:
        result = build_recipe_preset(
            "balanced-default",
            "balanced-custom",
            routing_package_id="claude-only",
        )
        # routing must come from claude-only (which has agent-research)
        self.assertIn("roles.agent-research", result.preset_mapping["routing"])

    def test_unknown_recipe_id_raises(self) -> None:
        with self.assertRaises(KeyError):
            build_recipe_preset("nope", "x")

    def test_unknown_routing_package_raises(self) -> None:
        with self.assertRaises(KeyError):
            build_recipe_preset("balanced-default", "x", routing_package_id="nope")

    def test_root_keys_subset_of_known_preset_keys(self) -> None:
        # Guard against introducing keys that render_toml would silently
        # drop. See _ROOT_TABLES in actions.py and PRESET_TOP_KEYS in
        # validation.py.
        allowed = {
            "name",
            "description",
            "origin",
            "pipeline_inline",
            "routing",
            "budget",
            "decompose",
            "mem_prime",
            "review_providers",
        }
        for spec in list_preset_recipes():
            preset = build_recipe_preset(spec.recipe_id, f"{spec.recipe_id}-x").preset_mapping
            extra = set(preset.keys()) - allowed
            self.assertFalse(extra, f"{spec.recipe_id} has unexpected keys: {extra}")


class BlankPresetDraftTests(unittest.TestCase):
    def test_blank_preset_has_user_origin_and_empty_stages(self) -> None:
        result = build_blank_preset_draft("blank-name", "blank-desc")
        self.assertEqual(result.preset_mapping["origin"], "user")
        self.assertEqual(result.preset_mapping["pipeline_inline"]["stages"], [])
        self.assertEqual(result.pipeline_mapping["stages"], [])
        self.assertEqual(result.preset_mapping["name"], "blank-name")
        self.assertEqual(result.preset_mapping["description"], "blank-desc")
        # Schema-lint surfaces the empty-stages error rather than suppressing it.
        joined = " | ".join(result.errors)
        self.assertIn("stages must be a non-empty array", joined)


class ApplyGraphStackTests(unittest.TestCase):
    def _empty_pipeline(self) -> dict:
        return {
            "pipeline_version": 1,
            "name": "x",
            "description": "d",
            "stages": [],
        }

    def test_empty_mode_applies_unconditionally_to_empty_pipeline(self) -> None:
        result = apply_graph_stack(
            self._empty_pipeline(),
            "default-implementation",
            "empty",
        )
        self.assertEqual(result.errors, ())
        stack = get_graph_stack("default-implementation")
        self.assertEqual(
            len(result.pipeline_mapping["stages"]),
            len(stack.stage_templates),
        )

    def test_empty_mode_refuses_when_stages_present(self) -> None:
        pipeline = self._empty_pipeline()
        pipeline["stages"] = [{"id": "research", "agents": [{"role": "agent-research"}]}]
        result = apply_graph_stack(pipeline, "default-implementation", "empty")
        self.assertNotEqual(result.errors, ())
        joined = " | ".join(result.errors)
        self.assertIn("empty", joined)

    def test_append_missing_adds_only_missing_stage_ids(self) -> None:
        pipeline = self._empty_pipeline()
        pipeline["stages"] = [
            {"id": "research", "agents": [{"role": "agent-research"}]},
        ]
        result = apply_graph_stack(pipeline, "default-implementation", "append-missing")
        self.assertEqual(result.errors, ())
        stage_ids = [s["id"] for s in result.pipeline_mapping["stages"]]
        # research stays; the rest of default-implementation fills in.
        self.assertEqual(stage_ids[0], "research")
        for required_id in ("analysis", "clarify", "writer", "review", "docs"):
            self.assertIn(required_id, stage_ids)

    def test_append_missing_refuses_on_id_collision_with_diff(self) -> None:
        pipeline = self._empty_pipeline()
        # Same id 'research' but with a *different* shape than the default stack.
        pipeline["stages"] = [
            {"id": "research", "agents": [{"role": "different-agent-role"}]},
        ]
        result = apply_graph_stack(pipeline, "default-implementation", "append-missing")
        self.assertNotEqual(result.errors, ())
        joined = " | ".join(result.errors)
        self.assertIn("research", joined)
        self.assertIn("differs", joined)

    def test_replace_mode_overwrites_stages(self) -> None:
        pipeline = self._empty_pipeline()
        pipeline["stages"] = [
            {"id": "research", "agents": [{"role": "agent-research"}]},
        ]
        result = apply_graph_stack(pipeline, "default-research", "replace")
        self.assertEqual(result.errors, ())
        # default-research stack is single-stage fan-out
        self.assertEqual(len(result.pipeline_mapping["stages"]), 1)
        self.assertEqual(result.pipeline_mapping["stages"][0]["id"], "research")
        self.assertIn("fan_out", result.pipeline_mapping["stages"][0])

    def test_unknown_mode_returns_error(self) -> None:
        result = apply_graph_stack(
            self._empty_pipeline(),
            "default-implementation",
            "bogus-mode",
        )
        self.assertNotEqual(result.errors, ())
        joined = " | ".join(result.errors)
        self.assertIn("bogus-mode", joined)

    def test_unknown_stack_id_raises_keyerror(self) -> None:
        with self.assertRaises(KeyError):
            apply_graph_stack(self._empty_pipeline(), "no-such-stack", "empty")


class FixtureDriftTests(unittest.TestCase):
    """Each recipe's graph_builder must produce the same dict (after key
    normalization) as its anchor pipelines/*.yaml fixture.

    Compares structurally, NOT byte-for-byte. The recipe builder produces a
    pipeline mapping whose ``name`` matches the stock fixture name (because
    the builder is called *before* build_recipe_preset overrides ``name``).
    """

    def test_every_recipe_graph_matches_anchor_fixture(self) -> None:
        self.assertTrue(
            _REPO_PIPELINES_DIR.is_dir(),
            f"pipelines dir not found at {_REPO_PIPELINES_DIR}",
        )
        for spec in list_preset_recipes():
            fixture_path = _REPO_PIPELINES_DIR / f"{spec._pipeline_fixture}.yaml"
            self.assertTrue(
                fixture_path.is_file(),
                f"missing fixture for {spec.recipe_id}: {fixture_path}",
            )
            expected = load_yaml(fixture_path)
            built = spec.graph_builder()
            self.assertEqual(
                built,
                expected,
                f"{spec.recipe_id} drifts from {spec._pipeline_fixture}.yaml",
            )


if __name__ == "__main__":
    unittest.main()
