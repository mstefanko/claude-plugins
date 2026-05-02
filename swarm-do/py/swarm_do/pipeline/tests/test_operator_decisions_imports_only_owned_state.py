from __future__ import annotations

import ast
import unittest
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PIPELINE_ROOT / "operator_decisions.py"


class OperatorDecisionNamingFenceTests(unittest.TestCase):
    def test_operator_decisions_imports_only_owned_state(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(SOURCE))
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported_names.update(alias.name for alias in node.names)
                self.assertFalse(
                    (node.module or "").endswith("phase_sessions"),
                    "operator_decisions.py must route phase-session writes through phase_session_store",
                )
            elif isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)

        self.assertNotIn("add_shared_decision", imported_names)
        self.assertNotIn("shared_decisions.v1.json", source)


if __name__ == "__main__":
    unittest.main()
