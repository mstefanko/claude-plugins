from __future__ import annotations

import json
from pathlib import Path

import pytest


class FakeClaude:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch

    def set_frames(self, frames: list[object], *, exit_code: int = 0, delay_ms: int = 0) -> None:
        self._monkeypatch.setenv("SWARM_FAKE_CLAUDE_FRAMES", json.dumps(frames))
        self._monkeypatch.setenv("SWARM_FAKE_CLAUDE_EXIT_CODE", str(exit_code))
        self._monkeypatch.setenv("SWARM_FAKE_CLAUDE_DELAY_MS", str(delay_ms))


@pytest.fixture
def fake_claude_on_path(fake_path_bin: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClaude:
    fake = Path(__file__).resolve().parent / "fakes" / "fake_claude.py"
    shim = fake_path_bin / "claude"
    shim.write_text(f"#!/usr/bin/env bash\nexec python3 {fake!s} \"$@\"\n", encoding="utf-8")
    shim.chmod(0o755)
    return FakeClaude(monkeypatch)
