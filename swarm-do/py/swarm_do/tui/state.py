"""Shared state readers for the swarm-do TUI.

This module intentionally has no Textual dependency so it can be unit-tested
without installing the optional TUI stack.
"""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from swarm_do.pipeline.actions import InFlightRun, in_flight_dir, load_in_flight
from swarm_do.pipeline.catalog import lens_for_variant
from swarm_do.pipeline.context import current_context
from swarm_do.pipeline.engine import graph_lines
from swarm_do.pipeline.paths import resolve_data_dir
from swarm_do.pipeline.resolver import active_preset_name


@dataclasses.dataclass(frozen=True)
class StatusSummary:
    preset: str
    pipeline: str
    runs_today: int
    cost_today: float | None
    last_429_claude: str | None
    last_429_codex: str | None
    latest_checkpoint: dict[str, Any] | None = None
    latest_observation: dict[str, Any] | None = None

    def render(self) -> str:
        cost = f"${self.cost_today:.4f}" if self.cost_today is not None else "n/a"
        claude = self.last_429_claude or "n/a"
        codex = self.last_429_codex or "n/a"
        rendered = (
            f"preset={self.preset} pipeline={self.pipeline} runs_today={self.runs_today} "
            f"cost_today={cost} last_429_claude={claude} last_429_codex={codex}"
        )
        if self.latest_checkpoint:
            rendered += (
                " latest_checkpoint="
                f"{self.latest_checkpoint.get('run_id', 'n/a')}:"
                f"{self.latest_checkpoint.get('phase_id') or 'n/a'}"
            )
        if self.latest_observation:
            rendered += (
                " latest_observation="
                f"{self.latest_observation.get('event_type', 'unknown')}:"
                f"{self.latest_observation.get('source') or 'n/a'}"
            )
        return rendered


def telemetry_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or resolve_data_dir()) / "telemetry"


def runs_path(data_dir: Path | None = None) -> Path:
    return telemetry_dir(data_dir) / "runs.jsonl"


def run_events_path(data_dir: Path | None = None) -> Path:
    return telemetry_dir(data_dir) / "run_events.jsonl"


def observations_path(data_dir: Path | None = None) -> Path:
    return telemetry_dir(data_dir) / "observations.jsonl"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def load_runs(data_dir: Path | None = None) -> list[dict[str, Any]]:
    return read_jsonl(runs_path(data_dir))


def load_run_events(data_dir: Path | None = None) -> list[dict[str, Any]]:
    return read_jsonl(run_events_path(data_dir))


def load_observations(data_dir: Path | None = None) -> list[dict[str, Any]]:
    return read_jsonl(observations_path(data_dir))


def latest_checkpoint_event(data_dir: Path | None = None) -> dict[str, Any] | None:
    for row in reversed(load_run_events(data_dir)):
        if row.get("event_type") == "checkpoint_written":
            return row
    return None


def latest_observation(data_dir: Path | None = None) -> dict[str, Any] | None:
    rows = load_observations(data_dir)
    return rows[-1] if rows else None


def token_burn_last_24h(rows: list[dict[str, Any]], now: datetime | None = None) -> dict[str, int | None]:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=24)
    totals: dict[str, int] = {}
    observed: set[str] = set()
    for row in rows:
        ts = _parse_ts(row.get("timestamp_start"))
        if ts is None or ts < cutoff:
            continue
        backend = str(row.get("backend") or "unknown")
        total = 0
        for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
            value = row.get(key)
            if isinstance(value, int):
                total += value
                observed.add(backend)
        totals[backend] = totals.get(backend, 0) + total
    result: dict[str, int | None] = {}
    for backend in sorted({str(r.get("backend") or "unknown") for r in rows} | set(totals)):
        result[backend] = totals.get(backend, 0) if backend in observed else None
    return result


def status_summary(data_dir: Path | None = None, now: datetime | None = None) -> StatusSummary:
    rows = load_runs(data_dir)
    now = now or datetime.now(UTC)
    today = now.date()
    runs_today = 0
    cost_values: list[float] = []
    last_429: dict[str, datetime] = {}
    for row in rows:
        ts = _parse_ts(row.get("timestamp_start"))
        if ts is not None and ts.date() == today:
            runs_today += 1
            cost = row.get("estimated_cost_usd")
            if isinstance(cost, (int, float)):
                cost_values.append(float(cost))
        rate_ts = _parse_ts(row.get("last_429_at"))
        if rate_ts is not None:
            backend = str(row.get("backend") or "unknown")
            if backend not in last_429 or rate_ts > last_429[backend]:
                last_429[backend] = rate_ts

    context = current_context()
    preset = active_preset_name() or "custom"
    pipeline = str(context.get("pipeline_name") or "default")
    return StatusSummary(
        preset=preset,
        pipeline=pipeline,
        runs_today=runs_today,
        cost_today=sum(cost_values) if cost_values else None,
        last_429_claude=last_429.get("claude").isoformat().replace("+00:00", "Z") if "claude" in last_429 else None,
        last_429_codex=last_429.get("codex").isoformat().replace("+00:00", "Z") if "codex" in last_429 else None,
        latest_checkpoint=latest_checkpoint_event(data_dir),
        latest_observation=latest_observation(data_dir),
    )


def pid_is_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def pipeline_lens_rows(pipeline: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for stage in pipeline.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        fan = stage.get("fan_out")
        if not isinstance(fan, dict) or fan.get("variant") != "prompt_variants":
            continue
        role = str(fan.get("role") or "")
        for variant in fan.get("variants") or []:
            if not isinstance(variant, str):
                continue
            lens = lens_for_variant(role, variant)
            if lens is None:
                rows.append(
                    {
                        "stage": str(stage.get("id") or "<unknown>"),
                        "variant": variant,
                        "lens_id": "(untyped)",
                        "label": variant,
                        "mode": "prompt_variants",
                        "compatibility": f"{role} fan_out",
                        "contract": "variant file only; no catalog metadata",
                    }
                )
                continue
            rows.append(
                {
                    "stage": str(stage.get("id") or "<unknown>"),
                    "variant": variant,
                    "lens_id": lens.lens_id,
                    "label": lens.label,
                    "mode": lens.execution_mode,
                    "compatibility": f"{', '.join(lens.roles)} / {', '.join(lens.stage_kinds)}",
                    "contract": lens.output_contract.schema_rule,
                }
            )
    return rows


def pipeline_workbench_preview(pipeline: dict[str, Any]) -> str:
    lines = graph_lines(pipeline)
    lens_rows = pipeline_lens_rows(pipeline)
    if lens_rows:
        lines.extend(["", "lenses:"])
        for row in lens_rows:
            lines.append(
                "  - "
                f"{row['stage']}:{row['variant']} -> {row['lens_id']} "
                f"({row['label']}; {row['mode']}; {row['compatibility']})"
            )
            lines.append(f"    contract: {row['contract']}")
    return "\n".join(lines)
