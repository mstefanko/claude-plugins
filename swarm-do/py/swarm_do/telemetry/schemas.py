"""Schema loading + row validation.

Phase 1 responsibility: match the legacy bash validator's semantics — parse +
required-field check. The legacy `_validate_ledger` (swarm-telemetry.legacy
lines 173-349) uses an embedded python heredoc to run partial draft-07
validation (type / enum / pattern / format=date-time / minimum / maximum /
required / additionalProperties / nested object + array).

Phase 3 extends this module with `validate_value` — a byte-parity port of the
legacy embedded validator's error-message format. `validate_row` remains the
simple shim used by Phase 1 call sites.
"""

from __future__ import annotations

import datetime
import json
import re
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

    Phase 3 code should use validate_value() directly for draft-07 parity.
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


# ---------------------------------------------------------------------------
# Phase 3 draft-07 validator — byte-parity port of legacy lines 214-306.
# ---------------------------------------------------------------------------


def _py_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _matches_type(value: Any, schema_type: str) -> bool:
    if schema_type == "null":
        return value is None
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "object":
        return isinstance(value, dict)
    return False


def _is_number(value: Any) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)


def _parse_datetime(value: Any):
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None


def validate_value(value: Any, schema: Dict[str, Any], json_path: str = "$") -> List[str]:
    """Return a list of error strings matching legacy message format exactly.

    Legacy port reference: swarm-telemetry.legacy:257-306 (embedded python).
    """
    errors: List[str] = []

    schema_type = schema.get("type")
    if schema_type is not None:
        allowed_types = schema_type if isinstance(schema_type, list) else [schema_type]
        if not any(_matches_type(value, candidate) for candidate in allowed_types):
            allowed = "|".join(str(candidate) for candidate in allowed_types)
            return [f"{json_path}: expected type {allowed}, got {_py_type_name(value)}"]

    if value is None:
        return errors

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{json_path}: expected one of {schema['enum']}, got {value!r}")

    if "pattern" in schema and isinstance(value, str):
        if re.fullmatch(schema["pattern"], value) is None:
            errors.append(f"{json_path}: value {value!r} does not match /{schema['pattern']}/")

    if schema.get("format") == "date-time" and isinstance(value, str):
        if _parse_datetime(value) is None:
            errors.append(f"{json_path}: value {value!r} is not a valid date-time")

    if "minimum" in schema and _is_number(value) and value < schema["minimum"]:
        errors.append(f"{json_path}: value {value!r} is less than minimum {schema['minimum']}")

    if "maximum" in schema and _is_number(value) and value > schema["maximum"]:
        errors.append(f"{json_path}: value {value!r} is greater than maximum {schema['maximum']}")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                errors.append(f"{json_path}: missing required property {required!r}")

        if schema.get("additionalProperties") is False:
            for key in value.keys():
                if key not in properties:
                    errors.append(f"{json_path}: unexpected property {key!r}")

        for key, child_schema in properties.items():
            if key in value:
                errors.extend(validate_value(value[key], child_schema, f"{json_path}.{key}"))

    if isinstance(value, list) and "items" in schema:
        for idx, item in enumerate(value):
            errors.extend(validate_value(item, schema["items"], f"{json_path}[{idx}]"))

    return errors
