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
