import asyncio
import sys

from bakeoff.runner import extract_final_json, run_provider


def test_extract_final_json_uses_last_block():
    payload = extract_final_json(
        '<final_json>{"first": true}</final_json>\nnoise\n<final_json>{"second": true}</final_json>'
    )

    assert payload == {"second": True}


def test_run_provider_reports_schema_error_for_missing_final_json():
    result = asyncio.run(
        run_provider(
            [sys.executable, "-c", "print('plain prose')"],
            "",
            {"wall_clock_seconds": 3, "max_output_bytes": 2000},
        )
    )

    assert result["status"] == "schema_error"


def test_run_provider_reports_output_cap():
    result = asyncio.run(
        run_provider(
            [sys.executable, "-c", "print('x' * 5000)"],
            "",
            {"wall_clock_seconds": 3, "max_output_bytes": 100},
        )
    )

    assert result["status"] == "output_cap"
    assert "[TRUNCATED at 100 bytes]" in result["stdout"]


def test_run_provider_reports_closed_stdin_diagnostic():
    result = asyncio.run(
        run_provider(
            [sys.executable, "-c", "import sys; sys.stdin.close(); sys.exit(7)"],
            "x" * 1_000_000,
            {"wall_clock_seconds": 3, "max_output_bytes": 2000},
        )
    )

    assert result["status"] == "exit_error"
    assert "provider closed stdin before reading prompt" in result["stderr"]


def test_run_provider_emits_heartbeat_ticks_for_quiet_process():
    payload = '<final_json>{"status":"complete"}</final_json>'
    ticks = []
    result = asyncio.run(
        run_provider(
            [
                sys.executable,
                "-c",
                f"import sys, time; sys.stdout.write({payload!r}); sys.stdout.flush(); time.sleep(5)",
            ],
            "",
            {"wall_clock_seconds": 3, "max_output_bytes": 2000, "heartbeat_seconds": 2},
            on_tick=ticks.append,
        )
    )

    assert result["status"] == "timeout"
    assert len(ticks) >= 2
    assert [tick["elapsed"] for tick in ticks] == sorted(tick["elapsed"] for tick in ticks)
    assert {tick["stdout_bytes"] for tick in ticks} == {len(payload.encode("utf-8"))}
    assert [tick["last_output_age"] for tick in ticks] == sorted(tick["last_output_age"] for tick in ticks)
    assert result["io"]["heartbeat_count"] == len(ticks)
    assert result["io"]["quiet_threshold_seconds"] == 4


def test_run_provider_heartbeat_does_not_contaminate_stdout():
    payload = 'hello\n<final_json>{"ok": true}</final_json>\n'
    ticks = []
    result = asyncio.run(
        run_provider(
            [
                sys.executable,
                "-c",
                f"import sys, time; sys.stdout.write({payload!r}); sys.stdout.flush(); time.sleep(1.2)",
            ],
            "",
            {"wall_clock_seconds": 5, "max_output_bytes": 2000, "heartbeat_seconds": 1},
            on_tick=ticks.append,
        )
    )

    assert result["status"] == "ok"
    assert ticks
    assert result["stdout"] == payload
