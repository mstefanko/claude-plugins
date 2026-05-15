import tempfile
from pathlib import Path

import pytest

from bakeoff.providers import build_scope_execution, scope_capabilities_from_help


def test_scope_capabilities_from_help_detects_claude_controls():
    caps = scope_capabilities_from_help(
        "claude",
        "--allowedTools --disallowedTools --tools --permission-mode",
    )

    assert caps["supports"]["allowed_tools"] is True
    assert caps["supports"]["disallowed_tools"] is True
    assert caps["supports"]["tools"] is True
    assert caps["supports"]["permission_mode"] is True


def test_scope_capabilities_from_help_detects_codex_controls():
    caps = scope_capabilities_from_help(
        "codex",
        "--sandbox <SANDBOX_MODE>\n--disable <FEATURE>\n--profile <CONFIG_PROFILE>\n-c, --config <key=value>",
    )

    assert caps["supports"]["sandbox"] is True
    assert caps["supports"]["disable_feature"] is True
    assert caps["supports"]["profile"] is True
    assert caps["supports"]["config"] is True


def test_codex_codebase_scope_adds_readonly_sandbox_and_disables_web_search(tmp_path):
    participant = {"id": "codex", "backend": "codex", "model": "fake-codex", "scope": "codebase"}
    plan = build_scope_execution(
        participant,
        {"enforcement": "best_effort"},
        workspace_cwd=tmp_path,
        run_dir=tmp_path / "runs" / "scope",
        capabilities={"supports": {"sandbox": True, "disable_feature": True}},
    )

    assert "--sandbox" in plan["argv"]
    assert "read-only" in plan["argv"]
    assert "--disable" in plan["argv"]
    assert "web_search" in plan["argv"]
    assert plan["cwd"] == tmp_path
    assert plan["metadata"]["enforcement_level"] == "partial"
    assert plan["metadata"]["fallback_reason"] is None


def test_claude_web_scope_uses_isolated_cwd_and_web_tool_allowlist(tmp_path):
    participant = {"id": "claude", "backend": "claude", "model": "fake-claude", "scope": "web"}
    run_dir = tmp_path / "runs" / "scope"
    plan = build_scope_execution(
        participant,
        {"enforcement": "best_effort"},
        workspace_cwd=tmp_path,
        run_dir=run_dir,
        capabilities={"supports": {"allowed_tools": True}},
    )

    assert plan["cwd"] == Path(tempfile.gettempdir()) / "bakeoff-scope-workspaces" / "scope" / "claude"
    assert "--allowedTools" in plan["argv"]
    assert "WebFetch" in plan["argv"]
    assert plan["metadata"]["effective_scope"] == "web"
    assert plan["metadata"]["mechanisms"] == ["isolated_cwd", "claude:allowedTools=WebFetch,WebSearch"]


def test_required_scope_rejects_missing_controls(tmp_path):
    participant = {"id": "claude", "backend": "claude", "model": "fake-claude", "scope": "codebase"}

    with pytest.raises(ValueError, match="did not advertise --disallowedTools"):
        build_scope_execution(
            participant,
            {"enforcement": "required"},
            workspace_cwd=tmp_path,
            run_dir=tmp_path / "runs" / "scope",
            capabilities={"supports": {"disallowed_tools": False}},
        )
