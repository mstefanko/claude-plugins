from __future__ import annotations

import asyncio
import json
import os
import re
import signal
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
) -> dict[str, Any]:
    """Run one provider subprocess under wall-clock and stdout caps."""
    started = time.monotonic()
    wall_seconds = int(budgets.get("wall_clock_seconds", budgets.get("wall_seconds", 900)))
    max_output_bytes = int(budgets.get("max_output_bytes", 60000))

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
        nonlocal output_cap_hit
        assert process.stdout is not None
        total = 0
        while True:
            chunk = await process.stdout.read(4096)
            if not chunk:
                break
            if total + len(chunk) > max_output_bytes:
                keep = max(0, max_output_bytes - total)
                if keep:
                    stdout_chunks.append(chunk[:keep])
                    total += keep
                stdout_chunks.append(f"\n[TRUNCATED at {max_output_bytes} bytes]\n".encode("utf-8"))
                output_cap_hit = True
                _terminate_process_group(process)
                break
            stdout_chunks.append(chunk)
            total += len(chunk)

    async def read_stderr() -> None:
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

    tasks = [asyncio.create_task(coro()) for coro in (feed_prompt, read_stdout, read_stderr)]
    try:
        await asyncio.wait_for(process.wait(), timeout=wall_seconds)
    except asyncio.TimeoutError:
        _terminate_process_group(process)
        await _wait_or_kill(process)
        await _settle_tasks(tasks)
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
            )
        return _status(
            "timeout",
            started,
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            final_json=None,
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
        )

    await _settle_tasks(tasks)
    stdout = _decode(stdout_chunks)
    stderr = _append_diagnostic(_decode(stderr_chunks), stdin_error)

    if output_cap_hit:
        return _status("output_cap", started, exit_code=process.returncode, stdout=stdout, stderr=stderr, final_json=None)
    if process.returncode != 0:
        return _status("exit_error", started, exit_code=process.returncode, stdout=stdout, stderr=stderr, final_json=None)

    try:
        final_json = extract_final_json(stdout)
        if validator is not None:
            final_json = validator(final_json)
    except ValidationError as exc:
        stderr = f"{stderr}\n{exc}".strip()
        return _status("schema_error", started, exit_code=process.returncode, stdout=stdout, stderr=stderr, final_json=None)

    return _status("ok", started, exit_code=process.returncode, stdout=stdout, stderr=stderr, final_json=final_json)


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


def _status(
    status: str,
    started: float,
    *,
    exit_code: int | None,
    stdout: str,
    stderr: str,
    final_json: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "exit_code": exit_code,
        "wall_seconds": round(time.monotonic() - started, 3),
        "output_bytes": len(stdout.encode("utf-8")),
        "stdout": stdout,
        "stderr": stderr,
        "final_json": final_json,
    }
