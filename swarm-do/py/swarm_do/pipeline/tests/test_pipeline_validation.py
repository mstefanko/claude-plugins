from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.engine import topological_layers
from swarm_do.pipeline.registry import find_pipeline, load_pipeline
from swarm_do.pipeline.resolver import BackendResolver
from swarm_do.pipeline.simple_yaml import loads
from swarm_do.pipeline.validation import schema_lint_pipeline, validate_preset_and_pipeline


class PipelineValidationTests(unittest.TestCase):
    def test_default_pipeline_layers_analysis_and_clarify_in_parallel(self) -> None:
        item = find_pipeline("default")
        self.assertIsNotNone(item)
        pipeline = load_pipeline(item.path)
        self.assertEqual(
            topological_layers(pipeline),
            [["research"], ["analysis", "clarify"], ["writer"], ["spec-review"], ["docs", "review"]],
        )

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
