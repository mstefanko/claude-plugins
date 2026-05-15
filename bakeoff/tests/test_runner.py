import asyncio
import sys

from bakeoff.runner import extract_final_json, run_provider, run_provider_with_format_retry
from bakeoff.work_order import ValidationError


def test_extract_final_json_uses_last_block():
    payload = extract_final_json(
        '<final_json>{"first": true}</final_json>\nnoise\n<final_json>{"second": true}</final_json>'
    )

    assert payload == {"second": True}


def test_extract_final_json_allows_tag_text_inside_json_strings():
    payload = extract_final_json(
        '<final_json>{"claim": "The extractor accepts literal <final_json>{}</final_json> text inside strings.", "ok": true}</final_json>'
    )

    assert payload == {
        "claim": "The extractor accepts literal <final_json>{}</final_json> text inside strings.",
        "ok": True,
    }


def test_run_provider_reports_schema_error_for_missing_final_json():
    result = asyncio.run(
        run_provider(
            [sys.executable, "-c", "print('plain prose')"],
            "",
            {"wall_clock_seconds": 3, "max_output_bytes": 2000},
        )
    )

    assert result["status"] == "schema_error"


def test_run_provider_format_retry_recovers_zero_exit_schema_error(tmp_path):
    script = tmp_path / "provider.py"
    script.write_text(
        """
import sys

prompt = sys.stdin.read()
if "BAKEOFF_FORMAT_RETRY_V1" in prompt:
    print('<final_json>{"ok": true}</final_json>')
else:
    print('<final_json>{"ok": false}</final_json>')
""",
        encoding="utf-8",
    )

    def validator(data):
        if data.get("ok") is not True:
            raise ValidationError("ok must be true")
        return data

    result = asyncio.run(
        run_provider_with_format_retry(
            [sys.executable, str(script)],
            "Return ok=true.",
            {"wall_clock_seconds": 3, "max_output_bytes": 2000},
            validator=validator,
        )
    )

    assert result["status"] == "ok_after_format_retry"
    assert result["final_json"] == {"ok": True}
    assert result["format_retry"]["initial_status"]["status"] == "schema_error"
    assert result["format_retry"]["retry_status"]["status"] == "ok"
    assert "BAKEOFF_FORMAT_RETRY_V1" in result["repair_artifacts"]["prompt"]
    assert result["repair_artifacts"]["status"]["status"] == "ok"


def test_run_provider_format_retry_preserves_schema_error_when_retry_fails(tmp_path):
    script = tmp_path / "provider.py"
    script.write_text(
        """
print('<final_json>{"ok": false}</final_json>')
""",
        encoding="utf-8",
    )

    def validator(data):
        if data.get("ok") is not True:
            raise ValidationError("ok must be true")
        return data

    result = asyncio.run(
        run_provider_with_format_retry(
            [sys.executable, str(script)],
            "Return ok=true.",
            {"wall_clock_seconds": 3, "max_output_bytes": 2000},
            validator=validator,
        )
    )

    assert result["status"] == "schema_error"
    assert result["final_json"] is None
    assert result["format_retry"]["initial_status"]["status"] == "schema_error"
    assert result["format_retry"]["retry_status"]["status"] == "schema_error"
    assert result["format_retry"]["reason"] == "ok must be true"
    assert result["repair_artifacts"]["status"]["status"] == "schema_error"


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
    assert result["stdout_truncated"] is True
    assert result["stdout_bytes"] <= 100


def test_run_provider_reports_stderr_truncation_without_failing_success():
    result = asyncio.run(
        run_provider(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('e' * 5000); print('<final_json>{\"ok\": true}</final_json>')",
            ],
            "",
            {"wall_clock_seconds": 3, "max_output_bytes": 100},
        )
    )

    assert result["status"] == "ok"
    assert result["stderr_truncated"] is True
    assert "[STDERR TRUNCATED at 100 bytes]" in result["stderr"]
    assert result["stderr_bytes"] <= 100


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
