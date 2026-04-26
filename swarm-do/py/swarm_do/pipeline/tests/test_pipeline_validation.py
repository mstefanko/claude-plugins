from __future__ import annotations

import argparse
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from swarm_do.pipeline import catalog
from swarm_do.pipeline.cli import cmd_research
from swarm_do.pipeline.engine import graph_lines, stage_agent_count, topological_layers
from swarm_do.pipeline.registry import find_pipeline, load_pipeline
from swarm_do.pipeline.resolver import BackendResolver
from swarm_do.pipeline.simple_yaml import loads
from swarm_do.pipeline.validation import schema_lint_pipeline, validate_preset_and_pipeline, variant_existence_errors


class PipelineValidationTests(unittest.TestCase):
    def test_default_pipeline_layers_analysis_and_clarify_in_parallel(self) -> None:
        item = find_pipeline("default")
        self.assertIsNotNone(item)
        pipeline = load_pipeline(item.path)
        self.assertEqual(
            topological_layers(pipeline),
            [["research"], ["analysis", "clarify"], ["writer"], ["provider-review", "spec-review"], ["docs", "review"]],
        )
        provider_stage = next(stage for stage in pipeline["stages"] if stage["id"] == "provider-review")
        self.assertEqual(provider_stage["provider"]["type"], "swarm-review")
        self.assertEqual(provider_stage["provider"]["selection"], "auto")
        self.assertNotIn("providers", provider_stage["provider"])
        result, *_ = validate_preset_and_pipeline("balanced")
        self.assertTrue(result.ok, result.errors)

    def test_stock_review_pipeline_collects_provider_evidence_before_synthesis(self) -> None:
        item = find_pipeline("review")
        self.assertIsNotNone(item)
        pipeline = load_pipeline(item.path)

        self.assertEqual(topological_layers(pipeline), [["provider-review"], ["review"]])
        provider_stage = pipeline["stages"][0]
        self.assertEqual(provider_stage["provider"]["type"], "swarm-review")
        self.assertEqual(provider_stage["provider"]["selection"], "auto")
        self.assertNotIn("providers", provider_stage["provider"])
        result, *_ = validate_preset_and_pipeline("review")
        self.assertTrue(result.ok, result.errors)

    def test_stock_implementation_pipelines_use_auto_provider_review_without_allowlists(self) -> None:
        for name in ("default", "lightweight", "ultra-plan"):
            with self.subTest(name=name):
                item = find_pipeline(name)
                self.assertIsNotNone(item)
                pipeline = load_pipeline(item.path)
                stage = next(stage for stage in pipeline["stages"] if stage["id"] == "provider-review")
                self.assertEqual(stage["provider"]["type"], "swarm-review")
                self.assertEqual(stage["provider"]["selection"], "auto")
                self.assertNotIn("providers", stage["provider"])
                review = next(stage for stage in pipeline["stages"] if stage["id"] == "review")
                self.assertIn("provider-review", review.get("depends_on") or [])

    def test_hybrid_review_adds_codex_review_after_spec_review(self) -> None:
        item = find_pipeline("hybrid-review")
        self.assertIsNotNone(item)
        pipeline = load_pipeline(item.path)
        self.assertEqual(
            topological_layers(pipeline),
            [["research"], ["analysis", "clarify"], ["writer"], ["spec-review"], ["codex-review", "docs", "review"]],
        )
        result, *_ = validate_preset_and_pipeline("hybrid-review")
        self.assertTrue(result.ok, result.errors)

    def test_mco_review_lab_adds_read_only_provider_before_claude_review(self) -> None:
        item = find_pipeline("mco-review-lab")
        self.assertIsNotNone(item)
        pipeline = load_pipeline(item.path)
        self.assertEqual(
            topological_layers(pipeline),
            [["research"], ["analysis", "clarify"], ["writer"], ["mco-review", "spec-review"], ["docs", "review"]],
        )
        mco_stage = next(stage for stage in pipeline["stages"] if stage["id"] == "mco-review")
        self.assertEqual(stage_agent_count(mco_stage), 1)
        rendered = "\n".join(graph_lines(pipeline))
        self.assertIn("provider=mco command=review providers=['claude']", rendered)
        self.assertIn("memory=False", rendered)
        result, *_ = validate_preset_and_pipeline("mco-review-lab")
        self.assertTrue(result.ok, result.errors)

    def test_research_pipeline_is_output_only_fanout_profile(self) -> None:
        item = find_pipeline("research")
        self.assertIsNotNone(item)
        pipeline = load_pipeline(item.path)
        self.assertEqual(topological_layers(pipeline), [["research"]])
        self.assertEqual(stage_agent_count(pipeline["stages"][0]), 4)
        rendered = "\n".join(graph_lines(pipeline))
        self.assertIn("fan_out=3 role=agent-research", rendered)
        self.assertNotIn("agent-writer", rendered)
        result, *_ = validate_preset_and_pipeline("research")
        self.assertTrue(result.ok, result.errors)

    def test_research_cli_dry_run_validates_profile_without_activation(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = cmd_research(argparse.Namespace(preset="research", target=[], dry_run=True))

        self.assertEqual(code, 0)
        rendered = stdout.getvalue()
        self.assertIn("Budget preview", rendered)
        self.assertIn("research preset research is valid", rendered)

    def test_provider_stage_is_mutually_exclusive_with_agent_stage(self) -> None:
        pipeline = loads(
            """
pipeline_version: 1
name: bad-provider
stages:
  - id: mco
    agents:
      - role: agent-review
    provider:
      type: mco
      command: review
      providers: [claude]
      timeout_seconds: 1800
"""
        )
        errors = schema_lint_pipeline(pipeline)
        self.assertTrue(any("exactly one of agents, fan_out, or provider" in e for e in errors))

    def test_provider_stage_rejects_memory_and_unknown_provider(self) -> None:
        pipeline = loads(
            """
pipeline_version: 1
name: bad-provider
stages:
  - id: mco
    provider:
      type: mco
      command: review
      providers: [claude, not-real]
      memory: true
      timeout_seconds: 1800
"""
        )
        errors = schema_lint_pipeline(pipeline)
        self.assertTrue(any("unsupported MCO provider" in e for e in errors))
        self.assertTrue(any("memory=true is not allowed" in e for e in errors))

    def test_swarm_review_provider_stage_supports_auto_selection(self) -> None:
        pipeline = loads(
            """
pipeline_version: 1
name: provider-review
stages:
  - id: provider-review
    provider:
      type: swarm-review
      command: review
      selection: auto
      output: findings
      memory: false
      timeout_seconds: 1800
      max_parallel: 2
"""
        )

        self.assertEqual(schema_lint_pipeline(pipeline), [])
        self.assertEqual(stage_agent_count(pipeline["stages"][0]), 2)
        rendered = "\n".join(graph_lines(pipeline))
        self.assertIn("provider=swarm-review command=review selection=auto", rendered)

    def test_swarm_review_rejects_providers_unless_selection_is_explicit(self) -> None:
        pipeline = loads(
            """
pipeline_version: 1
name: bad-provider-review
stages:
  - id: provider-review
    provider:
      type: swarm-review
      command: review
      selection: auto
      providers: [claude]
      timeout_seconds: 1800
"""
        )

        errors = schema_lint_pipeline(pipeline)
        self.assertTrue(any("providers is only valid when selection is explicit" in e for e in errors))

    def test_stock_swarm_review_rejects_hardcoded_provider_lists(self) -> None:
        pipeline = loads(
            """
pipeline_version: 1
name: stock-provider-review
origin: stock
stages:
  - id: provider-review
    provider:
      type: swarm-review
      command: review
      selection: explicit
      providers: [claude]
      timeout_seconds: 1800
"""
        )

        errors = schema_lint_pipeline(pipeline)
        self.assertTrue(any("providers is not allowed in stock swarm-review pipelines" in e for e in errors))

    def test_failure_tolerance_string_is_rejected(self) -> None:
        pipeline = loads(
            """
pipeline_version: 1
name: bad
stages:
  - id: fan
    fan_out:
      role: agent-analysis
      count: 3
      variant: same
    merge:
      strategy: synthesize
      agent: agent-analysis-judge
    failure_tolerance: 2-of-3
"""
        )
        errors = schema_lint_pipeline(pipeline)
        self.assertTrue(any("failure_tolerance must be a structured object" in e for e in errors))

    def test_cycle_detection_rejects_pipeline(self) -> None:
        pipeline = loads(
            """
pipeline_version: 1
name: cycle
stages:
  - id: a
    depends_on: [b]
    agents:
      - role: agent-research
  - id: b
    depends_on: [a]
    agents:
      - role: agent-analysis
"""
        )
        with self.assertRaisesRegex(ValueError, "cycle detected"):
            topological_layers(pipeline)

    def test_pipeline_parallelism_is_linted_and_displayed(self) -> None:
        pipeline = loads(
            """
pipeline_version: 1
name: parallel-ok
parallelism: 2
stages:
  - id: a
    agents:
      - role: agent-research
"""
        )
        self.assertEqual(schema_lint_pipeline(pipeline), [])

        bad = dict(pipeline)
        bad["parallelism"] = 0
        errors = schema_lint_pipeline(bad)
        self.assertTrue(any("parallelism must be an integer" in e for e in errors))

    def test_single_agent_lens_schema_lints_valid_overlay(self) -> None:
        pipeline = loads(
            """
pipeline_version: 1
name: single-lens
stages:
  - id: analysis
    agents:
      - role: agent-analysis
        lens: architecture-risk
"""
        )
        self.assertEqual(schema_lint_pipeline(pipeline), [])
        self.assertEqual(variant_existence_errors(pipeline), [])

    def test_single_agent_lens_rejects_stacking_unknown_and_incompatible_lenses(self) -> None:
        stacked = loads(
            """
pipeline_version: 1
name: stacked
stages:
  - id: analysis
    agents:
      - role: agent-analysis
        lenses: [architecture-risk, api-contract]
"""
        )
        stacked_errors = schema_lint_pipeline(stacked)
        self.assertTrue(any("lenses is not supported" in e for e in stacked_errors))

        unknown = loads(
            """
pipeline_version: 1
name: unknown
stages:
  - id: analysis
    agents:
      - role: agent-analysis
        lens: not-real
"""
        )
        unknown_errors = schema_lint_pipeline(unknown)
        self.assertTrue(any("unknown lens: not-real" in e for e in unknown_errors))

        incompatible = loads(
            """
pipeline_version: 1
name: incompatible
stages:
  - id: writer
    agents:
      - role: agent-writer
        lens: architecture-risk
"""
        )
        incompatible_errors = schema_lint_pipeline(incompatible)
        self.assertTrue(any("compatible with agent-analysis" in e for e in incompatible_errors))

    def test_single_agent_lens_missing_variant_file_fails_validation(self) -> None:
        pipeline = loads(
            """
pipeline_version: 1
name: missing-single-lens-file
stages:
  - id: analysis
    agents:
      - role: agent-analysis
        lens: fake-missing
"""
        )
        fake_lens = catalog.LensSpec(
            lens_id="fake-missing",
            label="Fake Missing",
            category="test",
            description="test lens with absent file",
            stability="test",
            roles=("agent-analysis",),
            stage_kinds=("agents",),
            execution_mode="single_agent",
            variant_name="fake-missing",
            variant_path="/tmp/swarm-do-missing-lens-file.md",
            output_contract=catalog.ANALYSIS_CONTRACT,
            merge_expectation="test",
        )
        with patch.object(catalog, "_PROMPT_LENSES", catalog._PROMPT_LENSES + (fake_lens,)):
            errors = variant_existence_errors(pipeline)
        self.assertTrue(any("variant file missing" in e and "fake-missing" in e for e in errors))

    def test_merge_agents_cannot_carry_lens_field(self) -> None:
        pipeline = loads(
            """
pipeline_version: 1
name: merge-lens
stages:
  - id: explore
    fan_out:
      role: agent-analysis
      count: 2
      variant: same
    merge:
      strategy: synthesize
      agent: agent-analysis-judge
      lens: architecture-risk
"""
        )

        errors = schema_lint_pipeline(pipeline)
        self.assertTrue(any("merge.lens is not supported" in e for e in errors))
        self.assertFalse(any("unknown keys: lens" in e for e in errors))

    def test_stage_agent_count_tolerates_malformed_stage_shapes(self) -> None:
        self.assertEqual(stage_agent_count({"fan_out": {"count": "many"}, "merge": []}), 0)
        self.assertEqual(stage_agent_count({"provider": {"providers": "claude"}}), 1)
        self.assertEqual(stage_agent_count({"agents": "agent-review"}), 0)

    def test_bare_model_id_in_models_variant_is_rejected(self) -> None:
        pipeline = loads(
            """
pipeline_version: 1
name: bad-models
stages:
  - id: writers
    fan_out:
      role: agent-writer
      count: 2
      variant: models
      routes: [gpt-5.4, claude-opus-4-7]
    merge:
      strategy: synthesize
      agent: agent-writer-judge
"""
        )
        errors = schema_lint_pipeline(pipeline)
        self.assertTrue(any("bare model IDs are invalid" in e for e in errors))

    def test_unresolved_named_model_routes_are_rejected_during_preset_validation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "presets").mkdir()
            (data / "pipelines").mkdir()
            (data / "pipelines" / "unresolved.yaml").write_text(
                """
pipeline_version: 1
name: unresolved
stages:
  - id: writers
    fan_out:
      role: agent-writer
      count: 2
      variant: models
      routes: [fast, slow]
    merge:
      strategy: synthesize
      agent: agent-writer-judge
""",
                encoding="utf-8",
            )
            (data / "presets" / "unresolved.toml").write_text(
                """
name = "unresolved"
pipeline = "unresolved"
origin = "user"

[budget]
max_agents_per_run = 20
max_estimated_cost_usd = 5.0
max_wall_clock_seconds = 1800
""",
                encoding="utf-8",
            )
            old = os.environ.get("CLAUDE_PLUGIN_DATA")
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                result, *_ = validate_preset_and_pipeline("unresolved")
                self.assertFalse(result.ok)
                self.assertTrue(any("named route not found" in e for e in result.errors))
            finally:
                if old is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old

    def test_named_model_routes_resolve_from_preset_routing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "presets").mkdir()
            (data / "pipelines").mkdir()
            (data / "pipelines" / "named-routes.yaml").write_text(
                """
pipeline_version: 1
name: named-routes
stages:
  - id: writers
    fan_out:
      role: agent-writer
      count: 2
      variant: models
      routes: [fast, slow]
    merge:
      strategy: synthesize
      agent: agent-writer-judge
""",
                encoding="utf-8",
            )
            (data / "presets" / "named-routes.toml").write_text(
                """
name = "named-routes"
pipeline = "named-routes"
origin = "user"

[routing]
fast = { backend = "claude", model = "claude-opus-4-7", effort = "high" }
slow = { backend = "codex", model = "gpt-5.4", effort = "xhigh" }

[budget]
max_agents_per_run = 20
max_estimated_cost_usd = 5.0
max_wall_clock_seconds = 1800
""",
                encoding="utf-8",
            )
            old = os.environ.get("CLAUDE_PLUGIN_DATA")
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                result, *_ = validate_preset_and_pipeline("named-routes")
                self.assertTrue(result.ok, result.errors)
            finally:
                if old is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old

    def test_inline_stage_override_cannot_move_synthesizer_to_codex(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "presets").mkdir()
            (data / "pipelines").mkdir()
            (data / "pipelines" / "bad-synth.yaml").write_text(
                """
pipeline_version: 1
name: bad-synth
stages:
  - id: synth
    agents:
      - role: agent-code-synthesizer
        backend: codex
        model: gpt-5.4
        effort: high
""",
                encoding="utf-8",
            )
            (data / "presets" / "bad-synth.toml").write_text(
                """
name = "bad-synth"
pipeline = "bad-synth"
origin = "user"

[budget]
max_agents_per_run = 20
max_estimated_cost_usd = 5.0
max_wall_clock_seconds = 1800
""",
                encoding="utf-8",
            )
            old = os.environ.get("CLAUDE_PLUGIN_DATA")
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                result, *_ = validate_preset_and_pipeline("bad-synth")
                self.assertFalse(result.ok)
                self.assertTrue(any("stage synth role agent-code-synthesizer" in e for e in result.errors))
            finally:
                if old is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old

    def test_variant_lint_catches_dangling_variant(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "presets").mkdir()
            (data / "pipelines").mkdir()
            (data / "pipelines" / "dangling.yaml").write_text(
                """
pipeline_version: 1
name: dangling
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
""",
                encoding="utf-8",
            )
            (data / "presets" / "dangling.toml").write_text(
                """
name = "dangling"
pipeline = "dangling"
origin = "user"

[budget]
max_agents_per_run = 20
max_estimated_cost_usd = 5.0
max_wall_clock_seconds = 1800
""",
                encoding="utf-8",
            )
            old = os.environ.get("CLAUDE_PLUGIN_DATA")
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                result, *_ = validate_preset_and_pipeline("dangling")
                self.assertFalse(result.ok)
                self.assertTrue(any("variant file missing" in e for e in result.errors))
            finally:
                if old is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old


class ResolverTests(unittest.TestCase):
    def test_preset_route_override_wins(self) -> None:
        resolver = BackendResolver(preset_name="balanced")
        route = resolver.resolve("agent-docs", "simple")
        self.assertEqual(route.backend, "codex")
        self.assertEqual(route.setting_source, "active-preset")

    def test_base_backends_fallback_wins_before_role_default(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "backends.toml"
            path.write_text(
                """
[roles.agent-review]
backend = "codex"
model = "gpt-5.4"
effort = "high"
""",
                encoding="utf-8",
            )
            resolver = BackendResolver(preset_name=None, base_backends_path=path)
            route = resolver.resolve("agent-review", "hard")
            self.assertEqual(route.backend, "codex")
            self.assertEqual(route.setting_source, "backends.toml")

    def test_invariant_rejects_orchestrator_to_codex(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "presets").mkdir()
            (data / "presets" / "bad.toml").write_text(
                """
name = "bad"
pipeline = "default"
origin = "user"

[routing]
"roles.orchestrator" = { backend = "codex", model = "gpt-5.4", effort = "high" }

[budget]
max_agents_per_run = 20
max_estimated_cost_usd = 5.0
max_wall_clock_seconds = 1800
""",
                encoding="utf-8",
            )
            old = os.environ.get("CLAUDE_PLUGIN_DATA")
            os.environ["CLAUDE_PLUGIN_DATA"] = td
            try:
                result, *_ = validate_preset_and_pipeline("bad")
                self.assertFalse(result.ok)
                self.assertTrue(any("orchestrator must resolve" in e for e in result.errors))
            finally:
                if old is None:
                    os.environ.pop("CLAUDE_PLUGIN_DATA", None)
                else:
                    os.environ["CLAUDE_PLUGIN_DATA"] = old


if __name__ == "__main__":
    unittest.main()
