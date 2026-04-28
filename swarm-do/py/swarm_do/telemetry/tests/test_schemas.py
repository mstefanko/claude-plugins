"""schemas.load_schema + validate_row smoke tests."""

from __future__ import annotations

import unittest

from swarm_do.telemetry.schemas import (
    SchemaNotFoundError,
    ValidationError,
    load_schema,
    validate_row,
)


class LoadSchemaTests(unittest.TestCase):
    def test_load_returns_dict_for_each_ledger(self) -> None:
        for ledger in (
            "runs",
            "findings",
            "outcomes",
            "adjudications",
            "finding_outcomes",
            "run_events",
            "observations",
            "knowledge",
        ):
            schema = load_schema(ledger)
            self.assertIsInstance(schema, dict, msg=f"ledger={ledger}")

    def test_runs_load_prefers_v2_schema(self) -> None:
        schema = load_schema("runs")
        self.assertEqual(schema.get("$id"), "https://mstefanko-plugins/swarm-do/telemetry/runs.schema.json#v2")

    def test_unknown_ledger_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            load_schema("nonexistent_ledger")


class ValidateRowTests(unittest.TestCase):
    def test_missing_required_field_raises(self) -> None:
        schema = {"required": ["run_id", "timestamp_start"]}
        with self.assertRaises(ValidationError) as cm:
            validate_row({"run_id": "abc"}, schema)
        self.assertIn("missing required fields", str(cm.exception))
        self.assertIn("timestamp_start", str(cm.exception))

    def test_all_required_present_passes(self) -> None:
        schema = {"required": ["a", "b"]}
        # Should not raise
        validate_row({"a": 1, "b": 2, "c": 3}, schema)

    def test_no_required_clause_passes(self) -> None:
        validate_row({"anything": True}, {})

    def test_non_object_row_raises(self) -> None:
        with self.assertRaises(ValidationError):
            validate_row([1, 2, 3], {"required": ["x"]})

    def test_runs_v2_unit_fields_validate(self) -> None:
        from swarm_do.telemetry.schemas import validate_value

        schema = load_schema("runs")
        row = {field: None for field in schema["required"]}
        row.update(
            {
                "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "timestamp_start": "2026-04-24T00:00:00Z",
                "backend": "codex",
                "model": "gpt-5.4",
                "effort": "medium",
                "role": "agent-writer",
                "risk_tags": [],
                "issue_id": "bd-1",
                "pipeline_name": "default",
                "exit_code": 0,
                "schema_ok": True,
                "work_unit_id": "unit-a",
                "decompose_complexity": "moderate",
                "decompose_source": "explicit",
                "unit_tool_call_count": 12,
            }
        )
        self.assertEqual(validate_value(row, schema), [])

    def test_observations_v2_details_validate(self) -> None:
        from swarm_do.telemetry.schemas import validate_value

        schema = load_schema("observations")
        self.assertEqual(
            schema.get("$id"),
            "https://mstefanko-plugins/swarm-do/telemetry/observations.schema.json#v2",
        )
        row = {
            "ts": "2026-04-24T00:00:00Z",
            "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "phase_id": "agent-writer",
            "event_type": "writer_exit",
            "tool": "swarm-run",
            "file_paths": None,
            "bead_ids": ["bd-1"],
            "diff_size_bytes": 10,
            "source": "swarm-run-exit",
            "details": {
                "role": "agent-writer",
                "stage_id": "agent-writer",
                "unit_id": "unit-a",
                "structured_event_count": 7,
                "tool_call_count": 6,
                "tool_category_counts": {"read": 2, "edit": 1},
                "uncategorized_tool_count": 0,
                "repeated_read_histogram": [{"file_path": "py/a.py", "count": 2}],
                "source_read_count": 2,
                "bd_show_count": 1,
                "first_edit_tool_call_index": 5,
                "first_test_tool_call_index": 6,
                "markers": {"needs_context_count": 0},
                "token_usage": {"cache_hit_ratio": 0.25},
            },
            "schema_ok": True,
        }
        self.assertEqual(validate_value(row, schema), [])

    def test_run_events_accept_prepare_event_types(self) -> None:
        from swarm_do.telemetry.schemas import validate_value

        schema = load_schema("run_events")
        for event_type in (
            "prepare_started",
            "prepare_lint_findings",
            "prepare_review_findings",
            "prepare_safe_fixes_accepted",
            "prepare_safe_fixes_proposed_unaccepted",
            "prepare_ready_for_acceptance",
            "prepare_blocking_findings",
            "prepare_accepted",
            "prepare_stale_rejected",
            "prepare_dispatch_started",
        ):
            with self.subTest(event_type=event_type):
                row = {
                    "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                    "timestamp": "2026-04-28T00:00:00Z",
                    "event_type": event_type,
                    "details": {},
                    "schema_ok": True,
                }
                self.assertEqual(validate_value(row, schema), [])


if __name__ == "__main__":
    unittest.main()
