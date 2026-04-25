from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from swarm_do.pipeline import actions as pipeline_actions
from swarm_do.pipeline.actions import (
    InFlightRun,
    add_pipeline_stage_from_module,
    fork_preset_and_pipeline,
    load_in_flight,
    request_handoff,
    rename_user_preset,
    set_base_route,
    set_stage_agent_route,
    set_user_preset_pipeline,
    set_user_preset_route,
)
from swarm_do.pipeline.config_hash import active_config_hash
from swarm_do.pipeline.providers import ProviderCheck, ProviderDoctorReport
from swarm_do.pipeline.registry import find_pipeline, load_pipeline, load_preset
from swarm_do.tui.state import (
    draft_add_module_stage,
    draft_remove_stage,
    draft_reset_fan_out_routes,
    draft_set_fan_out_branch_route,
    draft_set_stage_agent_route,
    draft_status_line,
    draft_validation_lines,
    effective_fan_out_branch_route,
    effective_stage_agent_route,
    latest_checkpoint_event,
    latest_observation,
    load_observations,
    load_run_events,
    module_palette_rows,
    pipeline_gallery_rows,
    pipeline_lens_rows,
    pipeline_stage_rows,
    pipeline_validation_report,
    pipeline_workbench_preview,
    select_source_preset_for_pipeline,
    stage_inspector_text,
    start_pipeline_draft,
    status_summary,
    suggested_fork_name,
    token_burn_last_24h,
    validate_pipeline_draft,
)


class EnvTestCase(unittest.TestCase):
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


class TuiStateTests(EnvTestCase):
    def test_status_summary_renders_na_for_unobserved_cost_and_429(self) -> None:
        tel = self.root / "telemetry"
        tel.mkdir()
        (tel / "runs.jsonl").write_text(
            json.dumps(
                {
                    "timestamp_start": "2026-04-24T12:00:00Z",
                    "backend": "claude",
                    "estimated_cost_usd": None,
                    "last_429_at": None,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        summary = status_summary(now=datetime(2026, 4, 24, 13, tzinfo=UTC))
        rendered = summary.render()
        self.assertIn("runs_today=1", rendered)
        self.assertIn("cost_today=n/a", rendered)
        self.assertIn("last_429_claude=n/a", rendered)

    def test_token_burn_keeps_backend_na_when_tokens_are_null(self) -> None:
        rows = [
            {
                "timestamp_start": "2026-04-24T12:00:00Z",
                "backend": "codex",
                "input_tokens": None,
                "output_tokens": None,
            }
        ]
        burn = token_burn_last_24h(rows, now=datetime(2026, 4, 24, 13, tzinfo=UTC))
        self.assertIsNone(burn["codex"])

    def test_in_flight_lockfiles_load(self) -> None:
        locks = self.root / "in-flight"
        locks.mkdir()
        (locks / "bd-abc.lock").write_text(
            json.dumps(
                {
                    "issue_id": "abc",
                    "role": "agent-writer",
                    "backend": "claude",
                    "model": "claude-opus-4-7",
                    "effort": "high",
                    "pid": 123,
                    "status": "running",
                }
            ),
            encoding="utf-8",
        )
        runs = load_in_flight()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].issue_id, "abc")
        self.assertEqual(runs[0].display_pid, "123")

    def test_run_events_and_observations_are_structured(self) -> None:
        tel = self.root / "telemetry"
        tel.mkdir()
        (tel / "run_events.jsonl").write_text(
            json.dumps(
                {
                    "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                    "timestamp": "2026-04-24T12:00:00Z",
                    "event_type": "checkpoint_written",
                    "phase_id": "writer",
                    "schema_ok": True,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (tel / "observations.jsonl").write_text(
            json.dumps(
                {
                    "ts": "2026-04-24T12:00:00Z",
                    "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                    "event_type": "writer_exit",
                    "source": "swarm-run-exit",
                    "schema_ok": True,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.assertEqual(load_run_events()[0]["event_type"], "checkpoint_written")
        self.assertEqual(load_observations()[0]["event_type"], "writer_exit")
        self.assertEqual(latest_checkpoint_event()["phase_id"], "writer")
        self.assertEqual(latest_observation()["source"], "swarm-run-exit")

        rendered = status_summary(now=datetime(2026, 4, 24, 13, tzinfo=UTC)).render()
        self.assertIn("latest_checkpoint=01ARZ3NDEKTSV4RRFFQ69G5FAV:writer", rendered)
        self.assertIn("latest_observation=writer_exit:swarm-run-exit", rendered)

    def test_pipeline_workbench_preview_includes_typed_lens_metadata(self) -> None:
        pipeline = {
            "pipeline_version": 1,
            "name": "ultra-preview",
            "stages": [
                {
                    "id": "exploration",
                    "fan_out": {
                        "role": "agent-analysis",
                        "count": 3,
                        "variant": "prompt_variants",
                        "variants": ["explorer-a", "explorer-b", "explorer-c"],
                    },
                    "merge": {"strategy": "synthesize", "agent": "agent-analysis-judge"},
                }
            ],
        }

        rows = pipeline_lens_rows(pipeline)
        preview = pipeline_workbench_preview(pipeline)

        self.assertEqual([row["lens_id"] for row in rows], ["architecture-risk", "api-contract", "state-data"])
        self.assertIn("fan_out_only", preview)
        self.assertIn("Preserve the agent-analysis output schema", preview)

    def test_pipeline_workbench_preview_includes_route_and_fanout_inspector(self) -> None:
        pipeline = {
            "pipeline_version": 1,
            "name": "route-preview",
            "stages": [
                {
                    "id": "analysis",
                    "agents": [
                        {
                            "role": "agent-analysis",
                            "backend": "codex",
                            "model": "gpt-5.4",
                            "effort": "high",
                        }
                    ],
                },
                {
                    "id": "writers",
                    "depends_on": ["analysis"],
                    "fan_out": {
                        "role": "agent-writer",
                        "count": 2,
                        "variant": "models",
                        "routes": [
                            {"backend": "claude", "model": "claude-opus-4-7", "effort": "high"},
                            {"backend": "codex", "model": "gpt-5.4-mini", "effort": "medium"},
                        ],
                    },
                    "merge": {"strategy": "synthesize", "agent": "agent-writer-judge"},
                },
            ],
        }

        preview = pipeline_workbench_preview(pipeline)

        self.assertIn("agent[0]: agent-analysis route=codex/gpt-5.4/high", preview)
        self.assertIn("branch[0]: route=claude/claude-opus-4-7/high", preview)
        self.assertIn("branch[1]: route=codex/gpt-5.4-mini/medium", preview)

    def test_pipeline_gallery_groups_by_intent_and_stage_inspector_focuses_selected_stage(self) -> None:
        rows = pipeline_gallery_rows()
        default = next(row for row in rows if row.name == "default")
        self.assertEqual(default.intent, "implement")
        self.assertEqual(default.preset, "balanced")
        self.assertEqual(select_source_preset_for_pipeline("default"), "balanced")
        self.assertEqual(suggested_fork_name("default"), "default-edit")

        pipeline = load_pipeline(find_pipeline("ultra-plan").path)
        stage_rows = pipeline_stage_rows(pipeline)
        self.assertEqual(stage_rows[0].stage_id, "research")
        inspector = stage_inspector_text(pipeline, "exploration")

        self.assertIn("kind: fan_out", inspector)
        self.assertIn("branch[0]: variant=explorer-a lens=architecture-risk", inspector)

    def test_pipeline_draft_validation_reports_invalid_without_mutating_file(self) -> None:
        fork_preset_and_pipeline("balanced", "default", "draft-invalid")
        item = find_pipeline("draft-invalid")
        before = item.path.read_text(encoding="utf-8")
        draft = start_pipeline_draft("draft-invalid")
        draft.pipeline["stages"][0]["depends_on"] = ["missing-stage"]

        result = validate_pipeline_draft(draft)
        rail = "\n".join(draft_validation_lines(draft))

        self.assertFalse(result.ok)
        self.assertIn("depends_on references unknown stage missing-stage", rail)
        self.assertIn("save blocked", rail)
        self.assertEqual(item.path.read_text(encoding="utf-8"), before)

    def test_pipeline_draft_stage_route_edits_are_undoable_and_deferred_until_save(self) -> None:
        fork_preset_and_pipeline("balanced", "default", "route-draft")
        item = find_pipeline("route-draft")
        before = item.path.read_text(encoding="utf-8")
        draft = start_pipeline_draft("route-draft")

        draft_set_stage_agent_route(
            draft,
            "analysis",
            0,
            backend="codex",
            model="gpt-5.4",
            effort="high",
        )

        route = effective_stage_agent_route(draft, "analysis", 0)
        self.assertEqual(route["backend"], "codex")
        self.assertIn("undo=1 redo=0", draft_status_line(draft))
        self.assertEqual(item.path.read_text(encoding="utf-8"), before)
        self.assertTrue(validate_pipeline_draft(draft).ok)

        self.assertTrue(draft.undo())
        agent = next(stage for stage in draft.pipeline["stages"] if stage["id"] == "analysis")["agents"][0]
        self.assertEqual(agent, {"role": "agent-analysis"})
        self.assertIn("undo=0 redo=1", draft_status_line(draft))

        self.assertTrue(draft.redo())
        route = effective_stage_agent_route(draft, "analysis", 0)
        self.assertEqual(route["backend"], "codex")

    def test_pipeline_draft_fan_out_branch_routes_can_be_changed_and_reset(self) -> None:
        fork_preset_and_pipeline("competitive", "compete", "fanout-draft")
        draft = start_pipeline_draft("fanout-draft")

        draft_set_fan_out_branch_route(
            draft,
            "writers",
            0,
            backend="codex",
            model="gpt-5.4-mini",
            effort="medium",
        )

        route = effective_fan_out_branch_route(draft, "writers", 0)
        fan = next(stage for stage in draft.pipeline["stages"] if stage["id"] == "writers")["fan_out"]
        self.assertEqual(route["model"], "gpt-5.4-mini")
        self.assertEqual(fan["variant"], "models")
        self.assertEqual(fan["routes"][1]["backend"], "codex")

        draft_reset_fan_out_routes(draft, "writers")
        fan = next(stage for stage in draft.pipeline["stages"] if stage["id"] == "writers")["fan_out"]
        self.assertEqual(fan, {"role": "agent-writer", "count": 2, "variant": "same"})
        self.assertTrue(validate_pipeline_draft(draft).ok)

    def test_pipeline_draft_module_palette_add_remove_and_undo(self) -> None:
        fork_preset_and_pipeline("balanced", "default", "module-draft")
        draft = start_pipeline_draft("module-draft")
        palette = module_palette_rows(draft.pipeline)

        self.assertIn("provider doctor required", next(row for row in palette if row["module_id"] == "mco-review")["detail"])
        with self.assertRaisesRegex(ValueError, "still required"):
            draft_remove_stage(draft, "research")

        draft_add_module_stage(draft, "codex-review", stage_id="codex-review-ui")
        self.assertTrue(any(stage["id"] == "codex-review-ui" for stage in draft.pipeline["stages"]))
        self.assertTrue(validate_pipeline_draft(draft).ok)

        draft_remove_stage(draft, "codex-review-ui")
        self.assertFalse(any(stage["id"] == "codex-review-ui" for stage in draft.pipeline["stages"]))
        self.assertTrue(draft.undo())
        self.assertTrue(any(stage["id"] == "codex-review-ui" for stage in draft.pipeline["stages"]))

    def test_pipeline_workbench_preview_includes_validation_and_diff_for_user_fork(self) -> None:
        fork_preset_and_pipeline("balanced", "default", "ui-preview")
        set_stage_agent_route("ui-preview", "analysis", 0, backend="codex", model="gpt-5.4", effort="high")
        pipeline = load_pipeline(find_pipeline("ui-preview").path)

        preview = pipeline_workbench_preview(pipeline, pipeline_name="ui-preview", include_validation=True)

        self.assertIn("source=default changed=true", preview)
        self.assertIn("drift: source unchanged", preview)
        self.assertIn("validation:", preview)
        self.assertIn("OK structural validation", preview)
        self.assertIn("agent[0]: agent-analysis route=codex/gpt-5.4/high", preview)

    def test_pipeline_validation_report_includes_mco_doctor_blocker(self) -> None:
        fork_preset_and_pipeline("balanced", "default", "mco-ui-preview")
        add_pipeline_stage_from_module("mco-ui-preview", "mco-review", stage_id="mco-review-ui")

        def fake_doctor(**kwargs) -> ProviderDoctorReport:
            return ProviderDoctorReport(
                active_preset="mco-ui-preview",
                pipeline_name="mco-ui-preview",
                required_backends=("claude", "codex"),
                required_providers=("mco",),
                checks=(
                    ProviderCheck("backend:claude", "ok", "claude found"),
                    ProviderCheck("provider:mco", "error", "selected MCO provider(s) not ready: claude=auth_check_failed"),
                ),
            )

        report = pipeline_validation_report(
            "mco-ui-preview",
            include_provider_doctor=True,
            provider_doctor_fn=fake_doctor,
        )

        self.assertIn("provider doctor: ERROR required=mco", report)
        self.assertIn("ERROR provider:mco: selected MCO provider(s) not ready", report)


class TuiActionTests(EnvTestCase):
    def test_config_hash_changes_when_backends_toml_changes(self) -> None:
        before = active_config_hash()
        set_base_route("agent-docs", None, "codex", "gpt-5.4-mini", "medium")
        after = active_config_hash()
        self.assertNotEqual(before, after)

    def test_invariant_rejects_orchestrator_to_codex(self) -> None:
        with self.assertRaisesRegex(ValueError, "orchestrator"):
            set_base_route("orchestrator", None, "codex", "gpt-5.4", "high")

    def test_invalid_pipeline_change_does_not_mutate_user_preset(self) -> None:
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
        with self.assertRaisesRegex(ValueError, "pipeline not found"):
            set_user_preset_pipeline("user", "missing")
        self.assertEqual(load_preset(preset_path)["pipeline"], "default")

    def test_user_preset_route_edit_validates_before_write(self) -> None:
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
        set_user_preset_route("user", "agent-docs", "simple", "codex", "gpt-5.4-mini", "medium")
        routing = load_preset(preset_path)["routing"]
        self.assertEqual(routing["roles.agent-docs.simple"]["backend"], "codex")

    def test_preset_rename_rejects_path_traversal(self) -> None:
        presets = self.root / "presets"
        presets.mkdir()
        (presets / "user.toml").write_text('name = "user"\norigin = "user"\npipeline = "default"\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "preset name"):
            rename_user_preset("user", "../escape")
        self.assertFalse((self.root / "escape.toml").exists())

    def test_handoff_rejects_path_traversal_issue_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "issue id"):
            request_handoff("../escape", "codex")
        self.assertFalse((self.root / "escape.lock").exists())

    def test_cancel_refuses_non_swarm_run_pid(self) -> None:
        run = InFlightRun("bd-1", "agent-writer", "claude", "opus", "high", 12345, None, "running", self.root / "in-flight" / "bd-1.lock")
        old = pipeline_actions._pid_command
        pipeline_actions._pid_command = lambda pid: "/usr/bin/python something-else"
        try:
            with self.assertRaisesRegex(ValueError, "non-swarm-run"):
                pipeline_actions.cancel_run(run)
        finally:
            pipeline_actions._pid_command = old


if __name__ == "__main__":
    unittest.main()
