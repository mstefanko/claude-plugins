"""Regression coverage for `swarm-telemetry query` sqlite connection cleanup."""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swarm_do.telemetry.subcommands import query


class _TrackedConnection:
    def __init__(self, inner: sqlite3.Connection, closed: list[bool]) -> None:
        self._inner = inner
        self._closed = closed

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    @property
    def row_factory(self):
        return self._inner.row_factory

    @row_factory.setter
    def row_factory(self, value) -> None:
        self._inner.row_factory = value

    def close(self) -> None:
        self._closed.append(True)
        self._inner.close()


class QueryCloseTests(unittest.TestCase):
    def test_run_closes_sqlite_connection_every_time(self) -> None:
        closed: list[bool] = []
        real_connect = sqlite3.connect

        def connect(*args, **kwargs):
            return _TrackedConnection(real_connect(*args, **kwargs), closed)

        with tempfile.TemporaryDirectory() as td:
            Path(td, "telemetry").mkdir()
            with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": td}), mock.patch.object(
                query.sqlite3,
                "connect",
                side_effect=connect,
            ), contextlib.redirect_stdout(io.StringIO()):
                for _ in range(100):
                    self.assertEqual(query.run(argparse.Namespace(sql="SELECT 1 AS ok")), 0)

        self.assertEqual(len(closed), 100)


if __name__ == "__main__":
    unittest.main()
