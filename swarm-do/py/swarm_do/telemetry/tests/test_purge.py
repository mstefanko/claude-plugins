"""Purge subcommand tests: retention-based row filtering, atomic rewrites, dry-run."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

from swarm_do.telemetry.cli import _parse_days_type
from swarm_do.telemetry.jsonl import atomic_write, stream_read
from swarm_do.telemetry.subcommands import purge


class ParseDaysTests(unittest.TestCase):
    def test_parse_days_valid_90d(self) -> None:
        result = _parse_days_type("90d")
        self.assertEqual(result, 90)

    def test_parse_days_valid_0d(self) -> None:
        result = _parse_days_type("0d")
        self.assertEqual(result, 0)

    def test_parse_days_valid_365d(self) -> None:
        result = _parse_days_type("365d")
        self.assertEqual(result, 365)

    def test_parse_days_invalid_hours(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            _parse_days_type("90h")

    def test_parse_days_invalid_minutes(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            _parse_days_type("30m")

    def test_parse_days_invalid_seconds(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            _parse_days_type("1s")

    def test_parse_days_invalid_bare_number(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            _parse_days_type("90")

    def test_parse_days_invalid_word(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            _parse_days_type("abc")


class PurgeRemoveOldRowTests(unittest.TestCase):
    def test_purge_removes_old_row(self) -> None:
        """Fixture: 3 rows at NOW-30d, NOW-60d, NOW-120d; --older-than 90d removes only 120d row."""
        with tempfile.TemporaryDirectory() as tmpdir:
            now = datetime.now(timezone.utc)
            path = Path(tmpdir) / "telemetry" / "runs.jsonl"

            # Create 3 rows at different ages.
            rows = [
                {
                    "id": "r1",
                    "timestamp_start": (now - timedelta(days=30)).isoformat(),
                },
                {
                    "id": "r2",
                    "timestamp_start": (now - timedelta(days=60)).isoformat(),
                },
                {
                    "id": "r3",
                    "timestamp_start": (now - timedelta(days=120)).isoformat(),
                },
            ]
            atomic_write(path, rows)

            # Purge with --older-than 90d.
            args = argparse.Namespace(
                older_than=90,
                ledger="runs",
                dry_run=False,
            )
            os.environ["CLAUDE_PLUGIN_DATA"] = tmpdir

            exit_code = purge.run(args)
            self.assertEqual(exit_code, 0)

            # Check: only 2 rows remain (r1, r2); r3 is gone.
            readback = list(stream_read(path))
            self.assertEqual(len(readback), 2)
            self.assertEqual({r["id"] for r in readback}, {"r1", "r2"})

    def test_purge_empty_ledger_not_present(self) -> None:
        """Missing ledger file: exit 0, print 'not present, skipped', continue."""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(
                older_than=90,
                ledger="runs",
                dry_run=False,
            )
            os.environ["CLAUDE_PLUGIN_DATA"] = tmpdir

            # Capture stdout.
            old_stdout = sys.stdout
            sys.stdout = StringIO()
            try:
                exit_code = purge.run(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            self.assertEqual(exit_code, 0)
            self.assertIn("not present, skipped", output)

    def test_purge_all_ledgers(self) -> None:
        """No --ledger specified: iterate all 5 ledgers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            now = datetime.now(timezone.utc)
            os.environ["CLAUDE_PLUGIN_DATA"] = tmpdir

            # Create 5 ledger files, each with 1 row.
            ledger_names = ["runs", "findings", "outcomes", "adjudications", "finding_outcomes"]
            ts_fields = {
                "runs": "timestamp_start",
                "findings": "timestamp",
                "outcomes": "timestamp",
                "adjudications": "timestamp",
                "finding_outcomes": "observed_at",
            }

            for ledger_name in ledger_names:
                path = Path(tmpdir) / "telemetry" / f"{ledger_name}.jsonl"
                ts_field = ts_fields[ledger_name]
                rows = [
                    {
                        "id": f"{ledger_name}_1",
                        ts_field: (now - timedelta(days=30)).isoformat(),
                    }
                ]
                atomic_write(path, rows)

            # Purge with --older-than 90d, no --ledger.
            args = argparse.Namespace(
                older_than=90,
                ledger=None,
                dry_run=False,
            )

            old_stdout = sys.stdout
            sys.stdout = StringIO()
            try:
                exit_code = purge.run(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            self.assertEqual(exit_code, 0)
            # All 5 ledgers should be processed.
            for ledger_name in ledger_names:
                self.assertIn(ledger_name, output)

    def test_dry_run_no_modify(self) -> None:
        """--dry-run reports counts but does not modify file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            now = datetime.now(timezone.utc)
            path = Path(tmpdir) / "telemetry" / "runs.jsonl"

            rows = [
                {
                    "id": "r1",
                    "timestamp_start": (now - timedelta(days=120)).isoformat(),
                }
            ]
            atomic_write(path, rows)

            # Get original inode.
            original_stat = os.stat(path)

            args = argparse.Namespace(
                older_than=90,
                ledger="runs",
                dry_run=True,
            )
            os.environ["CLAUDE_PLUGIN_DATA"] = tmpdir

            old_stdout = sys.stdout
            sys.stdout = StringIO()
            try:
                exit_code = purge.run(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            # File should be unchanged.
            after_stat = os.stat(path)
            self.assertEqual(original_stat.st_ino, after_stat.st_ino)
            self.assertEqual(original_stat.st_mtime, after_stat.st_mtime)

            # Output should say "would remove".
            self.assertIn("would remove", output)

    def test_purge_output_format(self) -> None:
        """Output matches 'purge: <ledger>: removed N of M rows (kept M-N)'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            now = datetime.now(timezone.utc)
            path = Path(tmpdir) / "telemetry" / "runs.jsonl"

            rows = [
                {
                    "id": "r1",
                    "timestamp_start": (now - timedelta(days=30)).isoformat(),
                },
                {
                    "id": "r2",
                    "timestamp_start": (now - timedelta(days=120)).isoformat(),
                },
            ]
            atomic_write(path, rows)

            args = argparse.Namespace(
                older_than=90,
                ledger="runs",
                dry_run=False,
            )
            os.environ["CLAUDE_PLUGIN_DATA"] = tmpdir

            old_stdout = sys.stdout
            sys.stdout = StringIO()
            try:
                exit_code = purge.run(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            self.assertIn("purge: runs: removed 1 of 2 rows (kept 1)", output)

    def test_older_than_overrides_default(self) -> None:
        """Explicit --older-than overrides DEFAULT_RETENTION_DAYS."""
        with tempfile.TemporaryDirectory() as tmpdir:
            now = datetime.now(timezone.utc)
            path = Path(tmpdir) / "telemetry" / "runs.jsonl"

            # 2 rows: one at 30d, one at 60d.
            rows = [
                {
                    "id": "r1",
                    "timestamp_start": (now - timedelta(days=30)).isoformat(),
                },
                {
                    "id": "r2",
                    "timestamp_start": (now - timedelta(days=60)).isoformat(),
                },
            ]
            atomic_write(path, rows)

            # Use --older-than 45d (not default 180d for runs).
            args = argparse.Namespace(
                older_than=45,
                ledger="runs",
                dry_run=False,
            )
            os.environ["CLAUDE_PLUGIN_DATA"] = tmpdir

            exit_code = purge.run(args)
            self.assertEqual(exit_code, 0)

            # r2 (60d) should be removed; r1 (30d) should remain.
            readback = list(stream_read(path))
            self.assertEqual(len(readback), 1)
            self.assertEqual(readback[0]["id"], "r1")

    def test_purge_older_than_0d_empty_ledger(self) -> None:
        """--older-than 0d on empty ledger: exit 0, 'not present, skipped'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(
                older_than=0,
                ledger="runs",
                dry_run=False,
            )
            os.environ["CLAUDE_PLUGIN_DATA"] = tmpdir

            old_stdout = sys.stdout
            sys.stdout = StringIO()
            try:
                exit_code = purge.run(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout

            self.assertEqual(exit_code, 0)
            self.assertIn("not present, skipped", output)


class PurgeTelemetryDirLayoutTests(unittest.TestCase):
    """Regression tests for the telemetry-dir resolution bug.

    Real swarm-run writes ledgers to $CLAUDE_PLUGIN_DATA/telemetry/<ledger>.jsonl.
    purge must resolve to the same path — not $CLAUDE_PLUGIN_DATA/<ledger>.jsonl.
    """

    def test_purge_reads_from_telemetry_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Place the ledger where swarm-run actually writes it.
            real_path = Path(tmpdir) / "telemetry" / "runs.jsonl"
            now = datetime.now(timezone.utc)
            atomic_write(
                real_path,
                [
                    {"id": "keep", "timestamp_start": (now - timedelta(days=30)).isoformat()},
                    {"id": "drop", "timestamp_start": (now - timedelta(days=120)).isoformat()},
                ],
            )
            # Decoy at the old (buggy) location — should not be touched.
            decoy_path = Path(tmpdir) / "runs.jsonl"
            atomic_write(decoy_path, [{"id": "decoy", "timestamp_start": (now - timedelta(days=500)).isoformat()}])

            args = argparse.Namespace(older_than=90, ledger="runs", dry_run=False)
            os.environ["CLAUDE_PLUGIN_DATA"] = tmpdir
            try:
                self.assertEqual(purge.run(args), 0)
            finally:
                os.environ.pop("CLAUDE_PLUGIN_DATA", None)

            readback = list(stream_read(real_path))
            self.assertEqual({r["id"] for r in readback}, {"keep"})

            decoy_rows = list(stream_read(decoy_path))
            self.assertEqual(len(decoy_rows), 1, "decoy at bad path must not be touched")


if __name__ == "__main__":
    unittest.main()
