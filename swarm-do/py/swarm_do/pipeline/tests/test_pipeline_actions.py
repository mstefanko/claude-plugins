from __future__ import annotations

import argparse
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from swarm_do.pipeline import actions as actions_module
from swarm_do.pipeline.actions import (
    add_pipeline_stage_from_module,
    create_user_preset_graph,
    fork_pipeline,
    fork_preset,
    fork_preset_and_pipeline,
    reset_fan_out_routes,
    reset_stage_agent_lens,
    reset_stage_agent_route,
    save_user_pipeline,
    set_fan_out_routes,
    set_prompt_variant_lenses,
    set_provider_review_config,
    set_stage_agent_lens,
    set_stage_agent_route,
    set_user_preset_pipeline,
    suggest_user_preset_name,
)
from swarm_do.pipeline.paths import current_preset_path, user_presets_dir
from swarm_do.pipeline.cli import cmd_preset_diff
from swarm_do.pipeline.diff import diff_user_pipeline, stock_drift_for_pipeline
from swarm_do.pipeline.registry import find_pipeline, find_preset, load_pipeline, load_preset
from swarm_do.pipeline.render_yaml import render_pipeline_yaml, render_yaml
from swarm_do.pipeline.simple_yaml import YamlError, loads


class PipelinePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        self.td = tempfile.TemporaryDirectory()
        os.environ["CLAUDE_PLUGIN_DATA"] = self.td.name

    def tearDown(self) -> None:
        self.td.cleanup()
        if self._old_data is None:
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
        else:
            os.environ["CLAUDE_PLUGIN_DATA"] = self._old_data

    @property
    def root(self) -> Path:
        return Path(self.td.name)

    def test_fork_preset_records_source_and_preserves_budget_tables(self) -> None:
        path = fork_preset("ultra-plan", "my-ultra")

        data = load_preset(path)
        self.assertEqual(data["name"], "my-ultra")
        self.assertEqual(data["origin"], "user")
        self.assertEqual(data["forked_from"], "ultra-plan")
        self.assertTrue(data["forked_from_hash"].startswith("sha256:"))
        self.assertEqual(data["budget"]["max_writer_tool_calls"], 60)
        self.assertEqual(data["decompose"]["mode"], "off")
        self.assertEqual(data["mem_prime"]["adapter"], "dispatch_file")

    def test_fork_pipeline_records_source_and_validates_rendered_yaml(self) -> None:
        path = fork_pipeline("ultra-plan", "my-ultra-pipe")

        data = load_pipeline(path)
        self.assertEqual(data["name"], "my-ultra-pipe")
        self.assertEqual(data["origin"], "user")
        self.assertEqual(data["forked_from"], "ultra-plan")
        self.assertEqual(data["stages"][1]["fan_out"]["variants"], ["explorer-a", "explorer-b", "explorer-c"])

    def test_coupled_fork_writes_preset_and_pipeline_as_matching_pair(self) -> None:
        preset_path, pipeline_path = fork_preset_and_pipeline("ultra-plan", "ultra-plan", "my-coupled")

        preset = load_preset(preset_path)
        self.assertNotIn("pipeline", preset)
        self.assertEqual(preset["pipeline_inline"]["name"], "my-coupled")
        self.assertEqual(preset["pipeline_inline_source"]["name"], "ultra-plan")
        self.assertEqual(load_pipeline(pipeline_path)["name"], "my-coupled")
        self.assertEqual(find_preset("my-coupled").origin, "user")
        self.assertEqual(find_pipeline("my-coupled").origin, "user")

    def test_coupled_fork_partial_failure_rolls_back_pipeline(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "simulated failure"):
            fork_preset_and_pipeline(
                "ultra-plan",
                "ultra-plan",
                "partial-coupled",
                _simulate_failure_after_pipeline=True,
            )

        self.assertFalse((self.root / "pipelines" / "partial-coupled.yaml").exists())
        self.assertFalse((self.root / "presets" / "partial-coupled.toml").exists())
        self.assertIsNone(find_pipeline("partial-coupled"))
        self.assertIsNone(find_preset("partial-coupled"))

    def test_name_collisions_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "preset already exists"):
            fork_preset("balanced", "ultra-plan")
        with self.assertRaisesRegex(ValueError, "pipeline already exists"):
            fork_pipeline("default", "ultra-plan")

    def test_invalid_pipeline_is_rejected_before_save(self) -> None:
        bad = loads(
            """
pipeline_version: 1
name: bad
stages:
  - id: explore
    fan_out:
      role: agent-analysis
      count: 1
      variant: prompt_variants
      variants: [missing-variant]
    merge:
      strategy: synthesize
      agent: agent-analysis-judge
"""
        )

        with self.assertRaisesRegex(ValueError, "variant file missing"):
            save_user_pipeline("bad", bad)
        self.assertFalse((self.root / "pipelines" / "bad.yaml").exists())

    def test_save_user_pipeline_rejects_preview_only_pipeline(self) -> None:
        preview_only = loads(
            """
pipeline_version: 1
name: review-only
stages:
  - id: review
    agents:
      - role: agent-review
"""
        )

        with self.assertRaisesRegex(ValueError, "preview-only"):
            save_user_pipeline("review-only", preview_only)
        self.assertFalse((self.root / "pipelines" / "review-only.yaml").exists())

    def test_fork_pipeline_rejects_preview_only_source(self) -> None:
        pipelines = self.root / "pipelines"
        pipelines.mkdir()
        (pipelines / "legacy-preview.yaml").write_text(
            render_pipeline_yaml(
                loads(
                    """
pipeline_version: 1
name: legacy-preview
origin: user
stages:
  - id: review
    agents:
      - role: agent-review
"""
                )
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "preview-only"):
            fork_pipeline("legacy-preview", "legacy-preview-copy")
        self.assertFalse((self.root / "pipelines" / "legacy-preview-copy.yaml").exists())

    def test_stable_yaml_renderer_round_trips_pipeline_subset(self) -> None:
        pipeline = loads(
            """
pipeline_version: 1
name: stable
description: Render check
stages:
  - id: research
    agents:
      - role: agent-research
  - id: review
    depends_on: [research]
    agents:
      - role: agent-review
        lens: correctness-rubric
        backend: claude
        model: claude-opus-4-7
        effort: high
"""
        )

        rendered = render_pipeline_yaml(pipeline)
        self.assertEqual(loads(rendered), pipeline)
        self.assertIn("depends_on: [research]", rendered)

    def test_stable_yaml_renderer_preserves_numeric_strings(self) -> None:
        rendered = render_pipeline_yaml(
            {
                "pipeline_version": 1,
                "name": "numeric-string",
                "stages": [
                    {
                        "id": "123",
                        "agents": [{"role": "agent-research"}],
                    }
                ],
            }
        )

        self.assertEqual(loads(rendered)["stages"][0]["id"], "123")

    def test_simple_yaml_round_trips_supported_scalar_corpus(self) -> None:
        value = {
            "plain": "alpha",
            "space": "hello world",
            "reserved": "true",
            "numeric": "42",
            "hash": "value # not a comment",
            "colon": "a: b",
            "quote": 'say "hi"',
            "backslash": "roles\\agent",
            "list": ["x y", "false", "1.2", "bracket [value]"],
        }

        self.assertEqual(loads(render_yaml(value)), value)

    def test_simple_yaml_rejects_control_character_scalars(self) -> None:
        with self.assertRaisesRegex(YamlError, "control characters"):
            loads("name: bad\x01\n")
        with self.assertRaisesRegex(YamlError, "control characters"):
            loads('name: "\\u0001"\n')

    def test_stock_pipeline_mutation_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "stock pipelines are read-only"):
            set_stage_agent_route(
                "default",
                "analysis",
                0,
                backend="codex",
                model="gpt-5.4",
                effort="high",
            )

    def test_stage_agent_route_can_be_set_and_reset(self) -> None:
        fork_pipeline("default", "route-edit")
        set_stage_agent_route(
            "route-edit",
            "analysis",
            0,
            backend="codex",
            model="gpt-5.4",
            effort="high",
        )
        edited = load_pipeline(find_pipeline("route-edit").path)
        agent = next(stage for stage in edited["stages"] if stage["id"] == "analysis")["agents"][0]
        self.assertEqual(agent["backend"], "codex")

        reset_stage_agent_route("route-edit", "analysis", 0)
        reset = load_pipeline(find_pipeline("route-edit").path)
        agent = next(stage for stage in reset["stages"] if stage["id"] == "analysis")["agents"][0]
        self.assertEqual(agent, {"role": "agent-analysis"})

    def test_stage_agent_lens_can_be_set_and_reset(self) -> None:
        fork_pipeline("default", "agent-lens-edit")
        set_stage_agent_lens("agent-lens-edit", "analysis", 0, "architecture-risk")

        edited = load_pipeline(find_pipeline("agent-lens-edit").path)
        agent = next(stage for stage in edited["stages"] if stage["id"] == "analysis")["agents"][0]
        self.assertEqual(agent["lens"], "architecture-risk")

        reset_stage_agent_lens("agent-lens-edit", "analysis", 0)
        reset = load_pipeline(find_pipeline("agent-lens-edit").path)
        agent = next(stage for stage in reset["stages"] if stage["id"] == "analysis")["agents"][0]
        self.assertNotIn("lens", agent)

    def test_stage_agent_lens_rejects_incompatible_lens_before_save(self) -> None:
        fork_pipeline("default", "bad-agent-lens-edit")
        with self.assertRaisesRegex(ValueError, "compatible with agent-analysis"):
            set_stage_agent_lens("bad-agent-lens-edit", "writer", 0, "architecture-risk")

        saved = load_pipeline(find_pipeline("bad-agent-lens-edit").path)
        agent = next(stage for stage in saved["stages"] if stage["id"] == "writer")["agents"][0]
        self.assertNotIn("lens", agent)

    def test_stage_agent_lens_rejects_path_like_lens_id_before_save(self) -> None:
        fork_pipeline("default", "path-lens-edit")
        with self.assertRaisesRegex(ValueError, "unknown lens"):
            set_stage_agent_lens("path-lens-edit", "analysis", 0, "../escape")

        saved = load_pipeline(find_pipeline("path-lens-edit").path)
        agent = next(stage for stage in saved["stages"] if stage["id"] == "analysis")["agents"][0]
        self.assertNotIn("lens", agent)

    def test_fan_out_route_reset_returns_to_resolver_default_shape(self) -> None:
        pipeline = loads(
            """
pipeline_version: 1
name: route-fan
stages:
  - id: writers
    fan_out:
      role: agent-writer
      count: 2
      variant: same
    merge:
      strategy: synthesize
      agent: agent-writer-judge
"""
        )
        save_user_pipeline("route-fan", pipeline)
        set_fan_out_routes(
            "route-fan",
            "writers",
            [
                {"backend": "claude", "model": "claude-opus-4-7", "effort": "high"},
                {"backend": "codex", "model": "gpt-5.4", "effort": "xhigh"},
            ],
        )
        edited = load_pipeline(find_pipeline("route-fan").path)
        self.assertEqual(edited["stages"][0]["fan_out"]["variant"], "models")

        reset_fan_out_routes("route-fan", "writers")
        reset = load_pipeline(find_pipeline("route-fan").path)
        self.assertEqual(reset["stages"][0]["fan_out"], {"role": "agent-writer", "count": 2, "variant": "same"})

    def test_prompt_variant_lenses_reject_models_route_combination(self) -> None:
        fork_pipeline("compete", "compete-edit")
        with self.assertRaisesRegex(ValueError, "cannot combine"):
            set_prompt_variant_lenses("compete-edit", "writers", ["architecture-risk"])

    def test_user_pipeline_cannot_be_activated_on_user_preset(self) -> None:
        presets = self.root / "presets"
        presets.mkdir()
        preset_path = presets / "user.toml"
        preset_path.write_text(
            """
name = "user"
pipeline = "default"
origin = "user"

[budget]
max_agents_per_run = 20
max_estimated_cost_usd = 5.0
max_wall_clock_seconds = 1800
""",
            encoding="utf-8",
        )
        pipelines = self.root / "pipelines"
        pipelines.mkdir()
        (pipelines / "review-only.yaml").write_text(
            render_pipeline_yaml(
                loads(
                    """
pipeline_version: 1
name: review-only
stages:
  - id: review
    agents:
      - role: agent-review
"""
                )
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "stock pipeline"):
            set_user_preset_pipeline("user", "review-only")
        self.assertEqual(load_preset(preset_path)["pipeline"], "default")

    def test_prompt_variant_lenses_compile_to_existing_variant_names(self) -> None:
        fork_pipeline("ultra-plan", "lens-edit")
        set_prompt_variant_lenses("lens-edit", "exploration", ["state-data", "api-contract"])

        edited = load_pipeline(find_pipeline("lens-edit").path)
        fan = next(stage for stage in edited["stages"] if stage["id"] == "exploration")["fan_out"]
        self.assertEqual(fan["count"], 2)
        self.assertEqual(fan["variants"], ["explorer-c", "explorer-b"])

    def test_prompt_variant_lenses_compile_for_research_and_review_roles(self) -> None:
        save_user_pipeline(
            "research-lens-edit",
            loads(
                """
pipeline_version: 1
name: research-lens-edit
stages:
  - id: research
    fan_out:
      role: agent-research
      count: 3
      variant: same
    merge:
      strategy: synthesize
      agent: agent-research-merge
"""
            ),
        )
        set_prompt_variant_lenses("research-lens-edit", "research", ["codebase-map", "prior-art-search"])
        research = load_pipeline(find_pipeline("research-lens-edit").path)
        self.assertEqual(research["stages"][0]["fan_out"]["variants"], ["codebase-map", "prior-art-search"])

        save_user_pipeline(
            "review-lens-edit",
            loads(
                """
pipeline_version: 1
name: review-lens-edit
origin: user
forked_from: review
stages:
  - id: review
    fan_out:
      role: agent-review
      count: 3
      variant: same
    merge:
      strategy: synthesize
      agent: agent-code-synthesizer
"""
            ),
        )
        set_prompt_variant_lenses("review-lens-edit", "review", ["correctness-rubric", "api-contract", "edge-case-review"])
        review = load_pipeline(find_pipeline("review-lens-edit").path)
        self.assertEqual(review["stages"][0]["fan_out"]["variants"], ["correctness-rubric", "api-contract", "edge-case-review"])

    def test_module_stage_addition_uses_catalog_template(self) -> None:
        fork_pipeline("default", "module-edit")
        add_pipeline_stage_from_module("module-edit", "codex-review", stage_id="codex-review-extra")

        edited = load_pipeline(find_pipeline("module-edit").path)
        stage = next(stage for stage in edited["stages"] if stage["id"] == "codex-review-extra")
        self.assertEqual(stage["agents"][0]["role"], "agent-codex-review")
        self.assertEqual(stage["failure_tolerance"]["mode"], "best-effort")

    def test_provider_review_module_and_config_editor_use_selection_policy(self) -> None:
        fork_pipeline("default", "provider-review-edit")
        set_provider_review_config(
            "provider-review-edit",
            "provider-review",
            selection="explicit",
            providers=["codex", "claude", "codex"],
            timeout_seconds=900,
            max_parallel=2,
        )

        edited = load_pipeline(find_pipeline("provider-review-edit").path)
        stage = next(stage for stage in edited["stages"] if stage["id"] == "provider-review")
        self.assertEqual(stage["provider"]["type"], "swarm-review")
        self.assertEqual(stage["provider"]["selection"], "explicit")
        self.assertEqual(stage["provider"]["providers"], ["codex", "claude"])
        self.assertEqual(stage["provider"]["max_parallel"], 2)

    def test_module_stage_addition_rejects_path_like_module_id(self) -> None:
        fork_pipeline("default", "path-module-edit")
        with self.assertRaisesRegex(ValueError, "unknown module"):
            add_pipeline_stage_from_module("path-module-edit", "../codex-review")

        edited = load_pipeline(find_pipeline("path-module-edit").path)
        self.assertFalse(any(stage.get("id") == "codex-review" for stage in edited["stages"]))

    def test_stock_drift_and_diff_use_recorded_source(self) -> None:
        fork_pipeline("default", "drift-edit")
        drift = stock_drift_for_pipeline("drift-edit")
        diff = diff_user_pipeline("drift-edit")

        self.assertTrue(drift.tracked)
        self.assertFalse(drift.drifted)
        self.assertTrue(diff.has_changes)
        self.assertIn("forked_from", diff.text())

    def test_preset_diff_cli_uses_recorded_source_for_renamed_fork(self) -> None:
        fork_preset_and_pipeline("balanced", "default", "renamed-balanced")

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = cmd_preset_diff(argparse.Namespace(name="renamed-balanced"))

        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("--- stock/balanced", text)
        self.assertIn("+++ user/renamed-balanced", text)
        self.assertNotIn("no stock preset with the same name", text)


class CreateUserPresetGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        self.td = tempfile.TemporaryDirectory()
        os.environ["CLAUDE_PLUGIN_DATA"] = self.td.name

    def tearDown(self) -> None:
        self.td.cleanup()
        if self._old_data is None:
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
        else:
            os.environ["CLAUDE_PLUGIN_DATA"] = self._old_data

    def _make_user_preset_mapping(self, name: str = "freshly-built") -> dict:
        # Build a valid user preset mapping using the stock ultra-plan as the
        # graph source via fork_preset_and_pipeline, then re-shape to inline.
        preset_path, _ = fork_preset_and_pipeline("ultra-plan", "ultra-plan", "tmp-source")
        data = load_preset(preset_path)
        # tmp-source preset still references pipeline by name; resolve inline.
        from swarm_do.pipeline.graph_source import resolve_preset_graph
        resolved = resolve_preset_graph(data)
        data.pop("pipeline", None)
        data["pipeline_inline"] = dict(resolved.graph)
        data["pipeline_inline"]["name"] = name
        data["name"] = name
        data["origin"] = "user"
        # Remove the temp preset/pipeline files so the new name can be reused.
        os.remove(preset_path)
        tmp_pipeline = find_pipeline("tmp-source")
        if tmp_pipeline is not None:
            os.remove(tmp_pipeline.path)
        return data

    def test_writes_toml_file_under_presets_dir(self) -> None:
        mapping = self._make_user_preset_mapping("freshly-built")

        path = create_user_preset_graph("freshly-built", mapping)

        self.assertTrue(path.exists())
        self.assertEqual(path.parent, user_presets_dir())
        self.assertEqual(path.name, "freshly-built.toml")

    def test_round_trip_through_preset_loader(self) -> None:
        mapping = self._make_user_preset_mapping("round-trip")

        path = create_user_preset_graph("round-trip", mapping)

        reloaded = load_preset(path)
        self.assertEqual(reloaded["name"], "round-trip")
        self.assertEqual(reloaded["origin"], "user")
        self.assertIn("pipeline_inline", reloaded)
        self.assertNotIn("pipeline", reloaded)
        item = find_preset("round-trip")
        self.assertIsNotNone(item)
        self.assertEqual(item.origin, "user")

    def test_rejects_invalid_name(self) -> None:
        mapping = self._make_user_preset_mapping("temp-mapping")
        mapping["name"] = "not a valid name!"
        with self.assertRaises(ValueError):
            create_user_preset_graph("not a valid name!", mapping)

    def test_rejects_collision_with_existing_preset(self) -> None:
        mapping = self._make_user_preset_mapping("collide-preset")
        create_user_preset_graph("collide-preset", mapping)

        # Build another mapping for the same name.
        mapping2 = self._make_user_preset_mapping("collide-preset")
        with self.assertRaises(ValueError) as cm:
            create_user_preset_graph("collide-preset", mapping2)
        self.assertIn("already exists", str(cm.exception))

    def test_rejects_collision_with_stock_preset(self) -> None:
        mapping = self._make_user_preset_mapping("ultra-plan")
        with self.assertRaises(ValueError):
            create_user_preset_graph("ultra-plan", mapping)

    def test_rejects_collision_with_existing_pipeline(self) -> None:
        # Fork a pipeline so a user pipeline named 'pipe-collide' exists.
        fork_pipeline("ultra-plan", "pipe-collide")
        mapping = self._make_user_preset_mapping("pipe-collide")
        with self.assertRaises(ValueError) as cm:
            create_user_preset_graph("pipe-collide", mapping)
        self.assertIn("pipeline", str(cm.exception).lower())

    def test_rejects_collision_with_stock_pipeline(self) -> None:
        # 'default' is a stock pipeline name.
        mapping = self._make_user_preset_mapping("default")
        with self.assertRaises(ValueError):
            create_user_preset_graph("default", mapping)

    def test_rejects_mapping_without_pipeline_inline(self) -> None:
        mapping = self._make_user_preset_mapping("missing-inline")
        mapping.pop("pipeline_inline")
        mapping["pipeline"] = "ultra-plan"
        with self.assertRaises(ValueError) as cm:
            create_user_preset_graph("missing-inline", mapping)
        self.assertIn("pipeline_inline", str(cm.exception))

    def test_rejects_mapping_with_non_user_origin(self) -> None:
        mapping = self._make_user_preset_mapping("bad-origin")
        mapping["origin"] = "stock"
        with self.assertRaises(ValueError) as cm:
            create_user_preset_graph("bad-origin", mapping)
        self.assertIn("origin", str(cm.exception))

    def test_activate_true_writes_current_preset(self) -> None:
        mapping = self._make_user_preset_mapping("active-one")

        path = create_user_preset_graph("active-one", mapping, activate=True)

        self.assertTrue(path.exists())
        active_text = current_preset_path().read_text(encoding="utf-8").strip()
        self.assertEqual(active_text, "active-one")

    def test_activation_failure_leaves_file_in_place(self) -> None:
        mapping = self._make_user_preset_mapping("activate-fail")

        with mock.patch.object(
            actions_module,
            "activate_preset",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                create_user_preset_graph("activate-fail", mapping, activate=True)

        target = user_presets_dir() / "activate-fail.toml"
        self.assertTrue(target.exists())
        self.assertIsNotNone(find_preset("activate-fail"))


class SuggestUserPresetNameTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_data = os.environ.get("CLAUDE_PLUGIN_DATA")
        self.td = tempfile.TemporaryDirectory()
        os.environ["CLAUDE_PLUGIN_DATA"] = self.td.name

    def tearDown(self) -> None:
        self.td.cleanup()
        if self._old_data is None:
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
        else:
            os.environ["CLAUDE_PLUGIN_DATA"] = self._old_data

    def test_returns_stem_when_no_collision(self) -> None:
        self.assertEqual(suggest_user_preset_name("totally-new-name"), "totally-new-name")

    def test_returns_suffix_on_single_collision(self) -> None:
        # 'ultra-plan' is a stock preset/pipeline → first collision.
        self.assertEqual(suggest_user_preset_name("ultra-plan"), "ultra-plan-custom")

    def test_returns_numbered_variant_on_multiple_collisions(self) -> None:
        # ultra-plan and ultra-plan-custom both collide; expect ultra-plan-custom-2.
        fork_preset("ultra-plan", "ultra-plan-custom")
        self.assertEqual(
            suggest_user_preset_name("ultra-plan"),
            "ultra-plan-custom-2",
        )

    def test_cap_exhaustion_raises(self) -> None:
        # Mock find_preset to always return a sentinel so every candidate collides.
        sentinel = object()
        with mock.patch.object(actions_module, "find_preset", return_value=sentinel), \
             mock.patch.object(actions_module, "find_pipeline", return_value=None):
            with self.assertRaises(ValueError):
                suggest_user_preset_name("anything")


if __name__ == "__main__":
    unittest.main()
