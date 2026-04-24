"""Tests for swarm_do.telemetry.gen readme-section subcommand."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ..gen import (
    MARKER_BEGIN_TELEMETRY_README,
    MARKER_END_TELEMETRY_README,
    cmd_readme_section_check,
    cmd_readme_section_write,
    render_telemetry_commands_table,
)


class TestRenderTelemetryCommandsTable(unittest.TestCase):
    """Tests for render_telemetry_commands_table function."""

    def test_commands_table_format(self):
        """Test that commands table is rendered with expected format."""
        commands = {
            "dump": "Pretty-print a JSONL ledger as a JSON array.",
            "validate": "Validate every ledger row against its JSON schema.",
        }
        table = render_telemetry_commands_table(commands)
        # Check table header
        self.assertIn("| Subcommand | What it does |", table)
        self.assertIn("|------------|--------------|", table)
        # Check that commands are present
        self.assertIn("dump", table)
        self.assertIn("validate", table)

    def test_commands_table_escapes_pipes(self):
        """Test that pipes in help text are escaped."""
        commands = {"test": "Help with | pipe character."}
        table = render_telemetry_commands_table(commands)
        self.assertIn("Help with \\| pipe character.", table)


class TestCmdReadmeSectionWrite(unittest.TestCase):
    """Tests for cmd_readme_section_write function."""

    def test_writes_to_file(self):
        """Test that --write updates the README file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            readme_path = tmp_path / "swarm-do" / "README.md"
            readme_path.parent.mkdir(parents=True)

            # Create initial file with markers
            initial_content = (
                "# README\n"
                f"{MARKER_BEGIN_TELEMETRY_README}\n"
                "(placeholder)\n"
                f"{MARKER_END_TELEMETRY_README}\n"
            )
            readme_path.write_text(initial_content)

            # Mock PLUGIN_ROOT
            with patch("swarm_do.telemetry.gen.PLUGIN_ROOT", tmp_path):
                result = cmd_readme_section_write()

            self.assertEqual(result, 0)
            content = readme_path.read_text()
            self.assertIn(MARKER_BEGIN_TELEMETRY_README, content)
            self.assertIn(MARKER_END_TELEMETRY_README, content)
            # Should have command table
            self.assertIn("| Subcommand | What it does |", content)

    def test_fails_on_missing_file(self):
        """Test that --write fails when README does not exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            with patch("swarm_do.telemetry.gen.PLUGIN_ROOT", tmp_path):
                result = cmd_readme_section_write()

            self.assertEqual(result, 1)


class TestCmdReadmeSectionCheck(unittest.TestCase):
    """Tests for cmd_readme_section_check function."""

    def test_check_passes_on_clean(self):
        """Test that --check passes when content is up-to-date."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            readme_path = tmp_path / "swarm-do" / "README.md"
            readme_path.parent.mkdir(parents=True)

            # Create initial file with markers
            initial_content = (
                "# README\n"
                f"{MARKER_BEGIN_TELEMETRY_README}\n"
                "(placeholder)\n"
                f"{MARKER_END_TELEMETRY_README}\n"
            )
            readme_path.write_text(initial_content)

            with patch("swarm_do.telemetry.gen.PLUGIN_ROOT", tmp_path):
                # Write first to generate correct content
                cmd_readme_section_write()
                # Then check should pass
                result = cmd_readme_section_check()

            self.assertEqual(result, 0)

    def test_check_detects_drift(self):
        """Test that --check fails when content has drifted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            readme_path = tmp_path / "swarm-do" / "README.md"
            readme_path.parent.mkdir(parents=True)

            # Create initial file with markers
            initial_content = (
                "# README\n"
                f"{MARKER_BEGIN_TELEMETRY_README}\n"
                "(placeholder)\n"
                f"{MARKER_END_TELEMETRY_README}\n"
            )
            readme_path.write_text(initial_content)

            with patch("swarm_do.telemetry.gen.PLUGIN_ROOT", tmp_path):
                # Write correct content first
                cmd_readme_section_write()

                # Modify the content between markers
                content = readme_path.read_text()
                content = content.replace("| Subcommand |", "| Modified |")
                readme_path.write_text(content)

                # Check should now fail
                result = cmd_readme_section_check()

            self.assertEqual(result, 1)

    def test_check_fails_on_missing_file(self):
        """Test that --check fails when file does not exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            with patch("swarm_do.telemetry.gen.PLUGIN_ROOT", tmp_path):
                result = cmd_readme_section_check()

            self.assertEqual(result, 1)


class TestIntegration(unittest.TestCase):
    """Integration tests for gen readme-section workflow."""

    def test_write_then_check_integration(self):
        """Test full workflow: write then check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            readme_path = tmp_path / "swarm-do" / "README.md"
            readme_path.parent.mkdir(parents=True)

            # Create initial file with markers
            initial_content = (
                "# README\n"
                f"{MARKER_BEGIN_TELEMETRY_README}\n"
                "(placeholder)\n"
                f"{MARKER_END_TELEMETRY_README}\n"
            )
            readme_path.write_text(initial_content)

            with patch("swarm_do.telemetry.gen.PLUGIN_ROOT", tmp_path):
                # Write should succeed
                self.assertEqual(cmd_readme_section_write(), 0)

                # Check should pass
                self.assertEqual(cmd_readme_section_check(), 0)

                # Modify file outside markers
                content = readme_path.read_text()
                content = "# Extra header\n" + content
                readme_path.write_text(content)

                # Check should still pass
                self.assertEqual(cmd_readme_section_check(), 0)

                # Modify file inside markers
                content = content.replace("dump", "modified")
                readme_path.write_text(content)

                # Check should now fail
                self.assertEqual(cmd_readme_section_check(), 1)


if __name__ == "__main__":
    unittest.main()
