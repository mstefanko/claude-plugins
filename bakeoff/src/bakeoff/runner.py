from __future__ import annotations

from collections.abc import Sequence
from typing import Any


async def run_provider(argv: Sequence[str], prompt: str, budgets: dict[str, Any]) -> dict[str, Any]:
    """Run one provider subprocess under the external timeout and output caps."""
    raise NotImplementedError("Phase 1 will implement provider subprocess execution.")
