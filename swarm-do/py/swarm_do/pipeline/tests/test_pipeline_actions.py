from __future__ import annotations

import argparse
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from swarm_do.pipeline.actions import (
    add_pipeline_stage_from_module,
    fork_pipeline,
    fork_preset,
    fork_preset_and_pipeline,
    reset_fan_out_routes,
    reset_stage_agent_lens,
    reset_stage_agent_route,
    save_user_pipeline,
    set_fan_out_routes,
    set_prompt_variant_lenses,
    set_stage_agent_lens,
    set_stage_agent_route,
    set_user_preset_pipeline,
)
from swarm_do.pipeline.cli import cmd_preset_diff
from swarm_do.pipeline.diff import diff_user_pipeline, stock_drift_for_pipeline
from swarm_do.pipeline.registry import find_pipeline, find_preset, load_pipeline, load_preset
from swarm_do.pipeline.render_yaml import render_pipeline_yaml
from swarm_do.pipeline.simple_yaml import loads


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

        self.assertEqual(load_preset(preset_path)["pipeline"], "my-coupled")
        self.assertEqual(load_pipeline(pipeline_path)["name"], "my-coupled")
        self.assertEqual(find_preset("my-coupled").origin, "user")
        self.assertEqual(find_pipeline("my-coupled").origin, "user")

    def test_coupled_fork_partial_failure_leaves_only_inactive_pipeline(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "simulated failure"):
            fork_preset_and_pipeline(
                "ultra-plan",
                "ultra-plan",
                "partial-coupled",
                _simulate_failure_after_pipeline=True,
            )

        self.assertTrue((self.root / "pipelines" / "partial-coupled.yaml").is_file())
        self.assertFalse((self.root / "presets" / "partial-coupled.toml").exists())
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

    def test_preview_only_output_pipeline_cannot_be_activated_on_user_preset(self) -> None:
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
        save_user_pipeline(
            "review-only",
            loads(
                """
pipeline_version: 1
name: review-only
stages:
  - id: review
    agents:
      - role: agent-review
"""
            ),
        )

        with self.assertRaisesRegex(ValueError, "preview-only"):
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


if __name__ == "__main__":
    unittest.main()
