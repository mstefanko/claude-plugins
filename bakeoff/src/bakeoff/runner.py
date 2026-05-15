from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from bakeoff.work_order import ValidationError

FINAL_JSON_RE = re.compile(r"<final_json>\s*(.*?)\s*</final_json>", re.DOTALL)


def extract_final_json(text: str) -> dict[str, Any]:
    matches = FINAL_JSON_RE.findall(text)
    if not matches:
        raise ValidationError("stdout is missing a <final_json>...</final_json> block")
    try:
        payload = json.loads(matches[-1])
    except json.JSONDecodeError as exc:
        raise ValidationError(f"last <final_json> block is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValidationError("last <final_json> block must decode to a JSON object")
    return payload


async def run_provider(
    argv: Sequence[str],
    prompt: str,
    budgets: dict[str, Any],
    *,
    cwd: str | Path | None = None,
    validator: Callable[[Any], dict[str, Any]] | None = None,
    on_tick: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run one provider subprocess under wall-clock and stdout caps."""
    started = time.monotonic()
    wall_seconds = int(budgets.get("wall_clock_seconds", budgets.get("wall_seconds", 900)))
    max_output_bytes = int(budgets.get("max_output_bytes", 60000))
    heartbeat_seconds = max(0, int(budgets.get("heartbeat_seconds", 60)))
    quiet_threshold_seconds = heartbeat_seconds * 2 if heartbeat_seconds > 0 else 0
    stdout_total_bytes = 0
    stderr_total_bytes = 0
    last_stdout_at: float | None = None
    last_stderr_at: float | None = None
    heartbeat_count = 0
    quiet_tick_count = 0

    def current_io(now: float | None = None) -> dict[str, Any]:
        actual_now = time.monotonic() if now is None else now
        last_output_at = max(
            (stamp for stamp in (last_stdout_at, last_stderr_at) if stamp is not None),
            default=None,
        )
        return {
            "stdout_bytes": stdout_total_bytes,
            "stderr_bytes": stderr_total_bytes,
            "last_stdout_age": round(actual_now - last_stdout_at, 3) if last_stdout_at is not None else None,
            "last_stderr_age": round(actual_now - last_stderr_at, 3) if last_stderr_at is not None else None,
            "last_output_age": round(actual_now - last_output_at, 3) if last_output_at is not None else round(actual_now - started, 3),
            "heartbeat_count": heartbeat_count,
            "quiet_tick_count": quiet_tick_count,
            "quiet_threshold_seconds": quiet_threshold_seconds,
        }

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd is not None else None,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        return _status(
            "missing_provider",
            started,
            exit_code=None,
            stdout="",
            stderr=str(exc),
            final_json=None,
            io=current_io(),
        )

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    output_cap_hit = False
    stdin_error: str | None = None

    async def feed_prompt() -> None:
        nonlocal stdin_error
        assert process.stdin is not None
        try:
            process.stdin.write(prompt.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()
        except (BrokenPipeError, ConnectionResetError, RuntimeError) as exc:
            stdin_error = f"provider closed stdin before reading prompt: {exc.__class__.__name__}"

    async def read_stdout() -> None:
        nonlocal last_stdout_at, output_cap_hit, stdout_total_bytes
        assert process.stdout is not None
        total = 0
        while True:
            chunk = await process.stdout.read(4096)
            if not chunk:
                break
            now = time.monotonic()
            if total + len(chunk) > max_output_bytes:
                keep = max(0, max_output_bytes - total)
                if keep:
                    stdout_chunks.append(chunk[:keep])
                    total += keep
                    stdout_total_bytes += keep
                marker = f"\n[TRUNCATED at {max_output_bytes} bytes]\n".encode("utf-8")
                stdout_chunks.append(marker)
                stdout_total_bytes += len(marker)
                last_stdout_at = now
                output_cap_hit = True
                _terminate_process_group(process)
                break
            stdout_chunks.append(chunk)
            total += len(chunk)
            stdout_total_bytes += len(chunk)
            last_stdout_at = now

    async def read_stderr() -> None:
        nonlocal last_stderr_at, stderr_total_bytes
        assert process.stderr is not None
        total = 0
        while True:
            chunk = await process.stderr.read(4096)
            if not chunk:
                break
            if total < max_output_bytes:
                keep = min(len(chunk), max_output_bytes - total)
                stderr_chunks.append(chunk[:keep])
                total += keep
                stderr_total_bytes += keep
                last_stderr_at = time.monotonic()

    def emit_tick(now: float) -> None:
        nonlocal heartbeat_count, quiet_tick_count
        heartbeat_count += 1
        io = current_io(now)
        phase = "quiet" if io["last_output_age"] >= quiet_threshold_seconds else "running"
        if phase == "quiet":
            quiet_tick_count += 1
        _safe_on_tick(
            on_tick,
            {
                "elapsed": round(now - started, 3),
                "stdout_bytes": stdout_total_bytes,
                "stderr_bytes": stderr_total_bytes,
                "total_bytes": stdout_total_bytes + stderr_total_bytes,
                "last_stdout_age": io["last_stdout_age"],
                "last_stderr_age": io["last_stderr_age"],
                "last_output_age": io["last_output_age"],
                "wall_seconds": wall_seconds,
                "phase": phase,
                "quiet_threshold_seconds": quiet_threshold_seconds,
            },
        )

    async def tick() -> None:
        while True:
            await asyncio.sleep(heartbeat_seconds)
            if process.returncode is not None:
                return
            emit_tick(time.monotonic())

    tasks = [asyncio.create_task(coro()) for coro in (feed_prompt, read_stdout, read_stderr)]
    if heartbeat_seconds > 0:
        tasks.append(asyncio.create_task(tick()))
    try:
        await asyncio.wait_for(process.wait(), timeout=wall_seconds)
    except asyncio.TimeoutError:
        _terminate_process_group(process)
        await _wait_or_kill(process)
        await _settle_tasks(tasks)
        if heartbeat_seconds > 0:
            emit_tick(time.monotonic())
        stdout = _decode(stdout_chunks)
        stderr = _append_diagnostic(_decode(stderr_chunks), stdin_error)
        if output_cap_hit:
            return _status(
                "output_cap",
                started,
                exit_code=process.returncode,
                stdout=stdout,
                stderr=stderr,
                final_json=None,
                io=current_io(),
            )
        return _status(
            "timeout",
            started,
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            final_json=None,
            io=current_io(),
        )
    except asyncio.CancelledError:
        _terminate_process_group(process)
        await _wait_or_kill(process)
        await _settle_tasks(tasks)
        return _status(
            "cancelled",
            started,
            exit_code=process.returncode,
            stdout=_decode(stdout_chunks),
            stderr=_append_diagnostic(_decode(stderr_chunks), stdin_error),
            final_json=None,
            io=current_io(),
        )

    await _settle_tasks(tasks)
    stdout = _decode(stdout_chunks)
    stderr = _append_diagnostic(_decode(stderr_chunks), stdin_error)

    if output_cap_hit:
        return _status("output_cap", started, exit_code=process.returncode, stdout=stdout, stderr=stderr, final_json=None, io=current_io())
    if process.returncode != 0:
        return _status("exit_error", started, exit_code=process.returncode, stdout=stdout, stderr=stderr, final_json=None, io=current_io())

    try:
        final_json = extract_final_json(stdout)
        if validator is not None:
            final_json = validator(final_json)
    except ValidationError as exc:
        stderr = f"{stderr}\n{exc}".strip()
        return _status("schema_error", started, exit_code=process.returncode, stdout=stdout, stderr=stderr, final_json=None, io=current_io())

    return _status("ok", started, exit_code=process.returncode, stdout=stdout, stderr=stderr, final_json=final_json, io=current_io())


def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        process.terminate()


async def _wait_or_kill(process: asyncio.subprocess.Process) -> None:
    try:
        await asyncio.wait_for(process.wait(), timeout=1)
    except asyncio.TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            process.kill()
        await process.wait()


async def _settle_tasks(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def _decode(chunks: list[bytes]) -> str:
    return b"".join(chunks).decode("utf-8", errors="replace")


def _append_diagnostic(stderr: str, diagnostic: str | None) -> str:
    if not diagnostic:
        return stderr
    return f"{stderr}\n{diagnostic}".strip()


def _safe_on_tick(on_tick: Callable[[dict[str, Any]], None] | None, payload: dict[str, Any]) -> None:
    if on_tick is None:
        return
    try:
        on_tick(payload)
    except Exception as exc:  # pragma: no cover - defensive callback boundary
        print(f"bakeoff heartbeat callback failed: {exc}", file=sys.stderr)


def _status(
    status: str,
    started: float,
    *,
    exit_code: int | None,
    stdout: str,
    stderr: str,
    final_json: dict[str, Any] | None,
    io: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": status,
        "exit_code": exit_code,
        "wall_seconds": round(time.monotonic() - started, 3),
        "output_bytes": len(stdout.encode("utf-8")),
        "io": io,
        "stdout": stdout,
        "stderr": stderr,
        "final_json": final_json,
    }
