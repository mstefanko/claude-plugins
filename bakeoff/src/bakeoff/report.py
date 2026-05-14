from __future__ import annotations

from typing import Any


def render_report(decision: dict[str, Any], worker_outputs: list[dict[str, Any]]) -> str:
    """Render a markdown report from decision.json and worker artifacts."""
    raise NotImplementedError("Phase 2 will implement report rendering.")
