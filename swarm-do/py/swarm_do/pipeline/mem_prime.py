"""Prompt rendering adapter for dispatcher-produced mem-prime artifacts."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

from .paths import resolve_data_dir


@dataclass(frozen=True)
class DispatchResult:
    schema_version: int
    unit_id: str
    axis: str
    obs_types: list[str]
    hits: list[dict[str, Any]]
    stats: dict[str, Any] = field(default_factory=dict)
    skipped_reason: str | None = None


@dataclass(frozen=True)
class PrimeResult:
    rendered_section_md: str | None
    stats: dict[str, Any]


class MemPrimeAdapter(Protocol):
    def read_dispatch_output(self, run_id: str, unit_id: str) -> DispatchResult:
        ...

    def render_prompt_section(self, result: DispatchResult, *, max_tokens: int = 500) -> str | None:
        ...


class DispatchFileAdapter:
    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else resolve_data_dir()

    def read_dispatch_output(self, run_id: str, unit_id: str) -> DispatchResult:
        path = self.data_dir / "runs" / run_id / "mem_prime" / f"{unit_id}.json"
        if not path.is_file():
            return DispatchResult(1, unit_id, "none", [], [], {}, "no_match")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return DispatchResult(1, unit_id, "none", [], [], {}, "no_match")
        return _dispatch_result_from_mapping(value, unit_id)

    def render_prompt_section(self, result: DispatchResult, *, max_tokens: int = 500) -> str | None:
        return render_prompt_section(result, max_tokens=max_tokens)


class LocalSqliteAdapter:
    """Fixture adapter used by tests; not used for live claude-mem lookup."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def read_dispatch_output(self, run_id: str, unit_id: str) -> DispatchResult:
        del run_id
        hits: list[dict[str, Any]] = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            for row in conn.execute(
                "select id, title, date, type, body from observations where unit_id = ? order by date desc limit 3",
                (unit_id,),
            ):
                hits.append(dict(row))
        return DispatchResult(
            schema_version=1,
            unit_id=unit_id,
            axis="topic" if hits else "none",
            obs_types=sorted({str(hit.get("type")) for hit in hits if hit.get("type")}),
            hits=hits,
            stats={"hit_count": len(hits), "title_only": False, "tokens": 0},
            skipped_reason=None if hits else "no_match",
        )

    def render_prompt_section(self, result: DispatchResult, *, max_tokens: int = 500) -> str | None:
        return render_prompt_section(result, max_tokens=max_tokens)


def prime_for_unit(
    unit: Mapping[str, Any],
    run_id: str,
    *,
    adapter: MemPrimeAdapter | None = None,
    max_tokens: int = 500,
) -> PrimeResult:
    unit_id = unit.get("id")
    if not isinstance(unit_id, str) or not unit_id:
        raise ValueError("unit requires id")
    if unit.get("mem_prime") is False:
        return PrimeResult(None, {"mem_prime_attempted": False, "mem_prime_skipped_reason": "unit_override"})
    actual_adapter = adapter or DispatchFileAdapter()
    result = actual_adapter.read_dispatch_output(run_id, unit_id)
    rendered = actual_adapter.render_prompt_section(result, max_tokens=max_tokens)
    stats = {
        "mem_prime_attempted": result.skipped_reason not in {"preset_off", "unit_override"},
        "mem_prime_axis": result.axis,
        "mem_prime_obs_types": result.obs_types,
        "mem_prime_hit_count": len(result.hits),
        "mem_prime_title_only": bool(result.stats.get("title_only")),
        "mem_prime_tokens": _token_count(rendered or ""),
        "mem_prime_skipped_reason": result.skipped_reason,
    }
    return PrimeResult(rendered, stats)


def render_prompt_section(result: DispatchResult, *, max_tokens: int = 500) -> str | None:
    if result.skipped_reason or not result.hits:
        return None
    header = [
        "### Prior context (claude-mem)",
        "",
        "Scoped to this unit's goal and files (last 90 days; types: discovery/bugfix/decision). Already retrieved; treat as advisory.",
        "",
    ]
    lines: list[str] = []
    remaining = max_tokens
    for hit in result.hits[:3]:
        title = str(hit.get("title") or "Untitled").strip()
        date = str(hit.get("date") or "unknown").strip()
        obs_type = str(hit.get("type") or "observation").strip()
        body = hit.get("body")
        entry = f"- **{title}** ({date}, {obs_type})"
        entry_tokens = _token_count(entry)
        if entry_tokens > remaining:
            break
        lines.append(entry)
        remaining -= entry_tokens
        if isinstance(body, str) and body.strip() and remaining > 0:
            body_text = _truncate_tokens(body.strip(), remaining)
            lines.append(f"  {body_text}")
            remaining -= _token_count(body_text)
    if not lines:
        return None
    return "\n".join(header + lines)


def _dispatch_result_from_mapping(value: Mapping[str, Any], fallback_unit_id: str) -> DispatchResult:
    hits = value.get("hits") if isinstance(value.get("hits"), list) else []
    return DispatchResult(
        schema_version=value.get("schema_version") if isinstance(value.get("schema_version"), int) else 1,
        unit_id=value.get("unit_id") if isinstance(value.get("unit_id"), str) else fallback_unit_id,
        axis=value.get("axis") if value.get("axis") in {"topic", "file", "none"} else "none",
        obs_types=[item for item in value.get("obs_types", []) if isinstance(item, str)] if isinstance(value.get("obs_types"), list) else [],
        hits=[dict(hit) for hit in hits if isinstance(hit, Mapping)],
        stats=dict(value.get("stats")) if isinstance(value.get("stats"), Mapping) else {},
        skipped_reason=value.get("skipped_reason") if isinstance(value.get("skipped_reason"), str) else None,
    )


def _token_count(text: str) -> int:
    return len(text.split())


def _truncate_tokens(text: str, max_tokens: int) -> str:
    words = text.split()
    if len(words) <= max_tokens:
        return text
    if max_tokens <= 1:
        return "[truncated]"
    return " ".join(words[: max_tokens - 1]) + " [truncated]"
