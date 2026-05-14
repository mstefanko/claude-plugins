from __future__ import annotations

from typing import Any

DEFAULT_MODEL_IDS = {
    "claude_sonnet": "claude-sonnet-4-6",
    "claude_opus": "claude-opus-4-7",
    "codex": "gpt-5.5",
}


def build_worker_prompt(work_order: dict[str, Any], provider: dict[str, Any]) -> str:
    """Build the worker prompt for gather, compare, or analyze mode."""
    raise NotImplementedError("Phase 2 will implement provider prompt construction.")


def build_judge_prompt(work_order: dict[str, Any], worker_outputs: list[dict[str, Any]]) -> str:
    """Build the artifact-only judge prompt for the selected mode."""
    raise NotImplementedError("Phase 2 will implement judge prompt construction.")
