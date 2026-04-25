"""Conservative work-unit budget estimates and enforcement helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


DEFAULT_MAX_WRITER_TOOL_CALLS = 60
DEFAULT_MAX_WRITER_OUTPUT_BYTES = 60_000
DEFAULT_MAX_HANDOFFS = 1


@dataclass(frozen=True)
class BudgetEstimate:
    tool_call_estimate: int
    output_byte_estimate: int
    tokens_estimate: int

    def to_dict(self) -> dict[str, int]:
        return {
            "tool_call_estimate": self.tool_call_estimate,
            "output_byte_estimate": self.output_byte_estimate,
            "tokens_estimate": self.tokens_estimate,
        }


@dataclass(frozen=True)
class WriterBudgetResult:
    status: str
    failure_reason: str | None
    tool_calls: int | None
    output_bytes: int | None
    handoff_count: int
    warnings: list[str]

    @property
    def escalated(self) -> bool:
        return self.status == "escalated"


def estimate_unit_budget(unit: Mapping[str, Any]) -> BudgetEstimate:
    files = _unit_files(unit)
    acceptance = unit.get("acceptance_criteria") if isinstance(unit.get("acceptance_criteria"), list) else []
    tool_calls = 8 + 4 * len(files) + 2 * len(acceptance)
    output_bytes = 2000 + 1500 * len(files)
    tokens = max(1, output_bytes // 4)
    return BudgetEstimate(tool_calls, output_bytes, tokens)


def budget_lint_errors(
    unit: Mapping[str, Any],
    *,
    max_writer_tool_calls: int = DEFAULT_MAX_WRITER_TOOL_CALLS,
    max_writer_output_bytes: int = DEFAULT_MAX_WRITER_OUTPUT_BYTES,
) -> list[str]:
    estimate = estimate_unit_budget(unit)
    errors: list[str] = []
    unit_id = unit.get("id", "<unknown>")
    if estimate.tool_call_estimate > max_writer_tool_calls:
        errors.append(
            f"{unit_id}: estimated tool calls {estimate.tool_call_estimate} exceed max_writer_tool_calls {max_writer_tool_calls}"
        )
    if estimate.output_byte_estimate > max_writer_output_bytes:
        errors.append(
            f"{unit_id}: estimated output bytes {estimate.output_byte_estimate} exceed max_writer_output_bytes {max_writer_output_bytes}"
        )
    return errors


def parse_writer_return_block(text: str) -> dict[str, Any] | None:
    """Extract the last JSON object containing writer budget fields."""

    decoder = json.JSONDecoder()
    matches: list[dict[str, Any]] = []
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and {"work_unit_id", "tool_calls", "output_bytes"} <= set(value):
            matches.append(value)
    return matches[-1] if matches else None


def evaluate_writer_budget(
    *,
    expected_work_unit_id: str,
    writer_return: str,
    diff_size_bytes: int = 0,
    max_writer_tool_calls: int = DEFAULT_MAX_WRITER_TOOL_CALLS,
    max_writer_output_bytes: int = DEFAULT_MAX_WRITER_OUTPUT_BYTES,
    max_handoffs: int = DEFAULT_MAX_HANDOFFS,
    telemetry_tool_call_count: int | None = None,
) -> WriterBudgetResult:
    block = parse_writer_return_block(writer_return)
    if block is None:
        return WriterBudgetResult("escalated", "other", None, None, 0, ["writer return block missing"])

    if block.get("work_unit_id") != expected_work_unit_id:
        return WriterBudgetResult(
            "escalated",
            "other",
            _int_or_none(block.get("tool_calls")),
            _int_or_none(block.get("output_bytes")),
            _int_or_zero(block.get("handoff_count")),
            ["writer return work_unit_id mismatch"],
        )

    self_reported_calls = _int_or_none(block.get("tool_calls"))
    measured_calls = telemetry_tool_call_count if telemetry_tool_call_count is not None else self_reported_calls
    self_reported_output = _int_or_none(block.get("output_bytes"))
    output_bytes = (self_reported_output or len(writer_return.encode("utf-8"))) + max(0, diff_size_bytes)
    handoff_count = _int_or_zero(block.get("handoff_count"))
    if bool(block.get("handoff")) and handoff_count == 0:
        handoff_count = 1

    warnings: list[str] = []
    if telemetry_tool_call_count is not None and self_reported_calls is not None:
        delta = abs(telemetry_tool_call_count - self_reported_calls)
        allowed = max(1, int(telemetry_tool_call_count * 0.10))
        if delta > allowed:
            warnings.append("writer self-report differs from backend telemetry by more than 10%; telemetry wins")

    if handoff_count > max_handoffs:
        return WriterBudgetResult("escalated", "repeat_handoff", measured_calls, output_bytes, handoff_count, warnings)
    if measured_calls is None:
        return WriterBudgetResult("escalated", "other", None, output_bytes, handoff_count, warnings)
    if measured_calls > max_writer_tool_calls:
        return WriterBudgetResult(
            "escalated",
            "budget_breach_tool_calls",
            measured_calls,
            output_bytes,
            handoff_count,
            warnings,
        )
    if output_bytes > max_writer_output_bytes:
        return WriterBudgetResult(
            "escalated",
            "budget_breach_output_bytes",
            measured_calls,
            output_bytes,
            handoff_count,
            warnings,
        )
    return WriterBudgetResult("ok", None, measured_calls, output_bytes, handoff_count, warnings)


def _unit_files(unit: Mapping[str, Any]) -> list[str]:
    value = unit.get("allowed_files", unit.get("files"))
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _int_or_zero(value: Any) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None and parsed >= 0 else 0
