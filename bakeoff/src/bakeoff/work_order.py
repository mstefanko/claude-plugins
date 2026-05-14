from __future__ import annotations

from pathlib import Path
from typing import Any


def load_work_order(path: str | Path) -> dict[str, Any]:
    """Load and validate a JSONC work order."""
    raise NotImplementedError("Phase 1 will implement JSONC loading and validation.")
