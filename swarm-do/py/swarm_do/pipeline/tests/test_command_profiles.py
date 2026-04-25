from __future__ import annotations

import argparse
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from swarm_do.pipeline.cli import cmd_brainstorm, cmd_design, cmd_research, cmd_review


class CommandProfileTests(unittest.TestCase):
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

    def _dry_run(self, func, preset: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        args = argparse.Namespace(preset=preset, target=[], dry_run=True)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = func(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_output_profile_dry_runs_validate_matching_stock_presets(self) -> None:
        cases = (
            (cmd_brainstorm, "brainstorm"),
            (cmd_research, "research"),
            (cmd_design, "design"),
            (cmd_review, "review"),
        )

        for func, preset in cases:
            with self.subTest(preset=preset):
                code, stdout, stderr = self._dry_run(func, preset)

                self.assertEqual(code, 0, stderr)
                self.assertIn("Budget preview", stdout)
                self.assertIn("Stage graph", stdout)
                self.assertIn(f"{preset} preset {preset} is valid", stdout)

    def test_output_profile_rejects_wrong_preset_binding(self) -> None:
        code, _stdout, stderr = self._dry_run(cmd_design, "research")

        self.assertEqual(code, 1)
        self.assertIn("expected design", stderr)


if __name__ == "__main__":
    unittest.main()
