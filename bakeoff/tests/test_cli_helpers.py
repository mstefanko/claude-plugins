import json

from bakeoff import cli as cli_module
from bakeoff.cli import main, merge_items


def test_merge_items_dedupes_normalized_duplicate_preserved_claims_from_same_source():
    items = merge_items(
        [
            {
                "claim": "Scope should be enforced when possible.",
                "source_provider": "claude",
            }
        ],
        [
            {
                "claim": "Scope should be enforced when possible!",
                "source_provider": "claude",
            }
        ],
    )

    assert len(items) == 1


def test_merge_items_keeps_near_duplicates_when_numbers_change():
    items = merge_items(
        [{"claim": "The change improves latency by 10%.", "source_provider": "claude"}],
        [{"claim": "The change improves latency by 100%.", "source_provider": "claude"}],
    )

    assert len(items) == 2


def test_merge_items_keeps_similar_claims_from_different_sources():
    items = merge_items(
        [{"claim": "Scope should be enforced when possible.", "source_provider": "claude"}],
        [{"claim": "Scope should be enforced when possible.", "source_provider": "codex"}],
    )

    assert len(items) == 2


def test_doctor_auth_probe_failure_is_warning_with_reason(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module.shutil, "which", lambda tool: f"/fake/{tool}")
    monkeypatch.setattr(cli_module, "tool_version", lambda tool: f"{tool} fake 1.0")
    monkeypatch.setattr(
        cli_module,
        "detect_scope_capabilities",
        lambda backend: {"backend": backend, "available": True, "supports": {}},
    )

    async def fake_run_provider(argv, prompt, budgets, on_tick=None):
        if argv[0] == "claude":
            return {
                "status": "exit_error",
                "exit_code": 1,
                "wall_seconds": 0,
                "output_bytes": 0,
                "stdout": "Not logged in - Please run /login\n",
                "stderr": "",
                "stdout_bytes": 35,
                "stderr_bytes": 0,
                "stdout_truncated": False,
                "stderr_truncated": False,
            }
        return {
            "status": "exit_error",
            "exit_code": 1,
            "wall_seconds": 0,
            "output_bytes": 0,
            "stdout": "",
            "stderr": "first line\nfinal codex reason\n",
            "stdout_bytes": 0,
            "stderr_bytes": 30,
            "stdout_truncated": False,
            "stderr_truncated": False,
        }

    monkeypatch.setattr(cli_module, "run_provider", fake_run_provider)

    assert main(["doctor", "--json", "--quiet"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok"
    assert report["warnings"] == [
        "claude auth probe failed with exit_error: Not logged in - Please run /login",
        "codex auth probe failed with exit_error: final codex reason",
    ]
    assert report["auth_probes"]["claude"]["reason"] == "Not logged in - Please run /login"
    assert report["auth_probes"]["codex"]["diagnostic_tail"] == "first line\nfinal codex reason"
