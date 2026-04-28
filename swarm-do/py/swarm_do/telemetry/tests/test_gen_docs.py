"""Tests for swarm_do.telemetry.gen docs subcommand."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from swarm_do.telemetry import gen as telemetry_gen
from swarm_do.telemetry.gen import (
    MARKER_BEGIN_TELEMETRY_DOCS,
    MARKER_END_TELEMETRY_DOCS,
    cmd_docs_check,
    cmd_docs_write,
    render_ledger_table,
    replace_between_markers,
)
from swarm_do.telemetry.registry import LEDGERS, PLUGIN_ROOT


class TestReplaceBetweenMarkers(unittest.TestCase):
    """Tests for replace_between_markers helper."""

    def test_happy_path(self):
        """Test successful replacement between markers."""
        content = "start\n<!-- BEGIN -->\nold\n<!-- END -->\nend"
        new_content = replace_between_markers(
            content, "<!-- BEGIN -->", "<!-- END -->", "new"
        )
        self.assertIn("<!-- BEGIN -->", new_content)
        self.assertIn("<!-- END -->", new_content)
        self.assertIn("new", new_content)
        self.assertNotIn("old", new_content)

    def test_missing_begin_marker(self):
        """Test raises ValueError when BEGIN marker absent."""
        content = "<!-- END -->"
        with self.assertRaises(ValueError) as ctx:
            replace_between_markers(
                content, "<!-- BEGIN -->", "<!-- END -->", "body"
            )
        self.assertIn("BEGIN marker not found", str(ctx.exception))

    def test_missing_end_marker(self):
        """Test raises ValueError when END marker absent."""
        content = "<!-- BEGIN -->"
        with self.assertRaises(ValueError) as ctx:
            replace_between_markers(
                content, "<!-- BEGIN -->", "<!-- END -->", "body"
            )
        self.assertIn("END marker not found", str(ctx.exception))

    def test_begin_after_end(self):
        """Test raises ValueError when BEGIN comes after END."""
        content = "<!-- END -->\n<!-- BEGIN -->"
        with self.assertRaises(ValueError) as ctx:
            replace_between_markers(
                content, "<!-- BEGIN -->", "<!-- END -->", "body"
            )
        self.assertIn("BEGIN marker comes after END marker", str(ctx.exception))


class TestRenderLedgerTable(unittest.TestCase):
    """Tests for render_ledger_table function."""

    def test_ledger_table_format(self):
        """Test that ledger table is rendered with expected format."""
        table = render_ledger_table(LEDGERS)
        # Check table header
        self.assertIn("| Ledger | Filename | Schema | Fallback count |", table)
        self.assertIn("|--------|----------|--------|----------------|", table)
        # Check that all ledgers are present
        for ledger_name in LEDGERS.keys():
            self.assertIn(ledger_name, table)

    def test_ledger_table_has_content(self):
        """Test that table contains all ledger rows."""
        table = render_ledger_table(LEDGERS)
        lines = table.split("\n")
        # Should have header, separator, and rows for each ledger
        self.assertGreaterEqual(len(lines), 2 + len(LEDGERS))


class TestCmdDocsWrite(unittest.TestCase):
    """Tests for cmd_docs_write function."""

    def test_writes_to_file(self):
        """Test that --write creates/updates the README file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            schema_dir = tmp_path / "swarm-do" / "schemas" / "telemetry"
            schema_dir.mkdir(parents=True)
            readme_path = schema_dir / "README.md"

            # Mock PLUGIN_ROOT to point to tmpdir
            with patch.object(telemetry_gen, "PLUGIN_ROOT", tmp_path):
                result = cmd_docs_write()

            self.assertEqual(result, 0)
            self.assertTrue(readme_path.exists())
            content = readme_path.read_text()
            self.assertIn(MARKER_BEGIN_TELEMETRY_DOCS, content)
            self.assertIn(MARKER_END_TELEMETRY_DOCS, content)
            self.assertIn("| runs |", content)

    def test_write_creates_parent_dirs(self):
        """Test that --write creates necessary parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            with patch.object(telemetry_gen, "PLUGIN_ROOT", tmp_path):
                result = cmd_docs_write()

            self.assertEqual(result, 0)
            schema_dir = tmp_path / "swarm-do" / "schemas" / "telemetry"
            self.assertTrue(schema_dir.exists())


class TestCmdDocsCheck(unittest.TestCase):
    """Tests for cmd_docs_check function."""

    def test_check_passes_on_clean(self):
        """Test that --check passes (returns 0) when content is up-to-date."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            schema_dir = tmp_path / "swarm-do" / "schemas" / "telemetry"
            schema_dir.mkdir(parents=True)
            readme_path = schema_dir / "README.md"

            # Create file with up-to-date content
            with patch.object(telemetry_gen, "PLUGIN_ROOT", tmp_path):
                cmd_docs_write()
                result = cmd_docs_check()

            self.assertEqual(result, 0)

    def test_check_detects_drift(self):
        """Test that --check fails (returns 1) when content has drifted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            schema_dir = tmp_path / "swarm-do" / "schemas" / "telemetry"
            schema_dir.mkdir(parents=True)
            readme_path = schema_dir / "README.md"

            # Create file with initial content
            with patch.object(telemetry_gen, "PLUGIN_ROOT", tmp_path):
                cmd_docs_write()

                # Modify the content between markers to introduce drift
                content = readme_path.read_text()
                content = content.replace("| runs |", "| modified |")
                readme_path.write_text(content)

                # Now check should fail
                result = cmd_docs_check()

            self.assertEqual(result, 1)

    def test_check_fails_on_missing_file(self):
        """Test that --check fails when file does not exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            with patch.object(telemetry_gen, "PLUGIN_ROOT", tmp_path):
                result = cmd_docs_check()

            self.assertEqual(result, 1)


class TestIntegration(unittest.TestCase):
    """Integration tests for gen docs workflow."""

    def test_write_then_check_integration(self):
        """Test full workflow: write then check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            schema_dir = tmp_path / "swarm-do" / "schemas" / "telemetry"

            with patch.object(telemetry_gen, "PLUGIN_ROOT", tmp_path):
                # Write should succeed
                self.assertEqual(cmd_docs_write(), 0)

                # Check should pass
                self.assertEqual(cmd_docs_check(), 0)

                # Modify file outside markers
                readme_path = schema_dir / "README.md"
                content = readme_path.read_text()
                content = "# New header\n" + content
                readme_path.write_text(content)

                # Check should still pass (drift only inside markers)
                self.assertEqual(cmd_docs_check(), 0)

                # Modify file inside markers
                lines = content.split("\n")
                for i, line in enumerate(lines):
                    if "| runs |" in line:
                        lines[i] = "| modified |"
                        break
                content = "\n".join(lines)
                readme_path.write_text(content)

                # Check should now fail
                self.assertEqual(cmd_docs_check(), 1)


if __name__ == "__main__":
    unittest.main()
