"""Schema loading + row validation.

Phase 1 responsibility: match the legacy bash validator's semantics — parse +
required-field check. The legacy `_validate_ledger` (swarm-telemetry.legacy
lines 133-178) uses jq to:
  1. Verify each JSONL row parses as JSON (jq -e .).
  2. Compute missing = ($required_fields - keys) and report any missing names.

Phase 3 will extend this module to a full draft-07 validator. For Phase 1 we
implement required-field checking against the JSON schema's top-level
`required` array so Python and bash produce equivalent pass/fail verdicts for
the same rows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .registry import LEDGERS


class SchemaNotFoundError(FileNotFoundError):
    """Raised when no entry in a ledger's fallback_order exists on disk."""


class ValidationError(ValueError):
    """Raised by validate_row when a row fails required-field checking.

    Message format mirrors the bash validator's "missing required fields:
    <names>" output so Phase 3 can tighten message parity.
    """


def load_schema(ledger_name: str) -> Dict[str, Any]:
    """Return the first schema JSON in LEDGERS[ledger_name].fallback_order
    that exists on disk. Raises KeyError for unknown ledgers and
    SchemaNotFoundError if no fallback is present.
    """
    ledger = LEDGERS[ledger_name]  # raises KeyError on unknown ledger
    for candidate in ledger.fallback_order:
        if candidate.is_file():
            with candidate.open("r", encoding="utf-8") as f:
                return json.load(f)
    tried = ", ".join(str(p) for p in ledger.fallback_order)
    raise SchemaNotFoundError(
        f"no schema file found for ledger '{ledger_name}' (tried: {tried})"
    )


def validate_row(row: Any, schema: Dict[str, Any]) -> None:
    """Phase 1 validator: parse + required-field parity with bash.

    Semantic contract (from legacy lines 133-178):
      - The input must be a JSON object. Bash treats any non-object as a
        parse failure.
      - Missing keys from the schema's top-level `required` list produce
        a ValidationError whose message lists the names, space-separated,
        to mirror the legacy "missing required fields:" output.

    Phase 3 will port full draft-07 type / enum / pattern / format checks.
    """
    if not isinstance(row, dict):
        raise ValidationError(
            f"row is not a JSON object (got {type(row).__name__})"
        )

    required: List[str] = list(schema.get("required", []) or [])
    if not required:
        return

    missing = [field for field in required if field not in row]
    if missing:
        raise ValidationError(
            "missing required fields: " + " ".join(missing)
        )
