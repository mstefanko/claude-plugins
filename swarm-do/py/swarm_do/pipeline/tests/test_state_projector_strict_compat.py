from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swarm_do.pipeline import state_projector
from swarm_do.pipeline.tests.test_state_projector import materialize_fixture


class StateProjectorStrictCompatTests(unittest.TestCase):
    def test_non_strict_schema_variant_projects_on_old_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            run_id = materialize_fixture("clean-single-phase", data_dir)
            with mock.patch.object(state_projector.sqlite3, "sqlite_version_info", (3, 31, 0)):
                self.assertNotIn("STRICT", state_projector.schema_sql())
                result = state_projector.project_run(run_id, data_dir=data_dir)

            self.assertEqual(result.row_counts["runs"], 1)
            self.assertEqual(result.row_counts["phase_attempts"], 1)


if __name__ == "__main__":
    unittest.main()
