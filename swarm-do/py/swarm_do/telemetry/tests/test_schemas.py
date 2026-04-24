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
        for ledger in ("runs", "findings", "outcomes", "adjudications", "finding_outcomes"):
            schema = load_schema(ledger)
            self.assertIsInstance(schema, dict, msg=f"ledger={ledger}")

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


if __name__ == "__main__":
    unittest.main()
