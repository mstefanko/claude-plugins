import shutil
import stat

import pytest

from bakeoff.providers import (
    ScopeEnforcementError,
    build_scope_execution,
    scope_capabilities_from_help,
)


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


def test_scope_capabilities_from_help_does_not_match_option_substrings():
    caps = scope_capabilities_from_help("codex", "--no-config\n--disable-feature")

    assert caps["supports"]["config"] is False
    assert caps["supports"]["disable_feature"] is False


def test_advisory_scope_does_not_probe_capabilities(monkeypatch, tmp_path):
    participant = {"id": "codex", "backend": "codex", "model": "fake-codex", "scope": "codebase"}

    def fail_probe(_backend):
        raise AssertionError("advisory mode should not probe provider capabilities")

    monkeypatch.setattr("bakeoff.providers.detect_scope_capabilities", fail_probe)

    plan = build_scope_execution(
        participant,
        {"enforcement": "advisory"},
        workspace_cwd=tmp_path,
        run_dir=tmp_path / "runs" / "scope",
    )

    assert plan["metadata"]["enforcement_level"] == "advisory"
    assert plan["cleanup_paths"] == []


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

    try:
        assert plan["cwd"].exists()
        assert stat.S_IMODE(plan["cwd"].stat().st_mode) == 0o700
        assert plan["cwd"].name.startswith("bakeoff-scope-claude-")
        assert plan["cleanup_paths"] == [plan["cwd"]]
        assert "--allowedTools" in plan["argv"]
        assert "WebFetch" in plan["argv"]
        assert plan["metadata"]["effective_scope"] == "web"
        assert plan["metadata"]["temporary_cwd"] is True
        assert plan["metadata"]["mechanisms"] == ["isolated_cwd", "claude:allowedTools=WebFetch,WebSearch"]
    finally:
        shutil.rmtree(plan["cwd"], ignore_errors=True)


def test_required_scope_rejects_missing_controls(tmp_path):
    participant = {"id": "claude", "backend": "claude", "model": "fake-claude", "scope": "codebase"}

    with pytest.raises(ScopeEnforcementError, match="did not advertise --disallowedTools"):
        build_scope_execution(
            participant,
            {"enforcement": "required"},
            workspace_cwd=tmp_path,
            run_dir=tmp_path / "runs" / "scope",
            capabilities={"supports": {"disallowed_tools": False}},
        )
