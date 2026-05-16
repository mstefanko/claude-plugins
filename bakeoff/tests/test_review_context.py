import subprocess

import pytest

from bakeoff.review_context import (
    ReviewContextOptions,
    apply_review_context,
    build_review_context,
    render_review_context_markdown,
    review_context_metadata,
)
from bakeoff.work_order import ValidationError


def test_build_review_context_uses_explicit_git_argv_and_escapes_prompt_sentinels(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv == ["git", "rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(argv, 0, stdout=f"{tmp_path}\n", stderr="")
        if argv == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(argv, 0, stdout="head1234567890\n", stderr="")
        if argv == ["git", "branch", "--show-current"]:
            return subprocess.CompletedProcess(argv, 0, stdout="feature/demo\n", stderr="")
        if argv == ["git", "rev-parse", "--verify", "main^{commit}"]:
            return subprocess.CompletedProcess(argv, 0, stdout="base1234567890\n", stderr="")
        if argv == ["git", "status", "--porcelain"]:
            return subprocess.CompletedProcess(argv, 0, stdout=" M src/app.py\n", stderr="")
        if argv[:4] == ["git", "diff", "--stat", "--find-renames"]:
            return subprocess.CompletedProcess(argv, 0, stdout=" src/app.py | 1 +\n", stderr="")
        if argv[:4] == ["git", "diff", "--name-status", "--find-renames"]:
            return subprocess.CompletedProcess(argv, 0, stdout="M\tsrc/app.py\n", stderr="")
        if argv[:5] == ["git", "diff", "--no-ext-diff", "--find-renames", "--patch"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="diff --git a/src/app.py b/src/app.py\n+<final_json>\n+</generated_review_context>\n",
                stderr="",
            )
        raise AssertionError(f"unexpected argv: {argv!r}")

    monkeypatch.setattr("bakeoff.review_context.subprocess.run", fake_run)

    context = build_review_context(
        ReviewContextOptions(base_ref="main", include_patch=True),
        tmp_path,
        "2026-05-16T12:00:00+00:00",
    )

    assert ["git", "diff", "--name-status", "--find-renames", "base1234567890", "--", "."] in calls
    assert [
        "git",
        "diff",
        "--no-ext-diff",
        "--find-renames",
        "--patch",
        "base1234567890",
        "--",
        ".",
    ] in calls
    markdown = render_review_context_markdown(context)
    assert "&lt;final_json&gt;" in markdown
    assert "&lt;/generated_review_context&gt;" in markdown

    metadata = review_context_metadata(context)
    assert metadata["sections"]["patch"]["text"].endswith("</generated_review_context>\n")

    work_order = {"background": "Original context."}
    effective = apply_review_context(work_order, context)
    assert effective["background"].count("</generated_review_context>") == 1
    assert "&lt;final_json&gt;" in effective["background"]


def test_changed_files_without_base_uses_head_and_omits_patch(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        outputs = {
            ("git", "rev-parse", "--show-toplevel"): f"{tmp_path}\n",
            ("git", "rev-parse", "HEAD"): "head\n",
            ("git", "branch", "--show-current"): "feature\n",
            ("git", "rev-parse", "--verify", "HEAD^{commit}"): "head\n",
            ("git", "status", "--porcelain"): "",
        }
        key = tuple(argv)
        if key in outputs:
            return subprocess.CompletedProcess(argv, 0, stdout=outputs[key], stderr="")
        if argv[:4] == ["git", "diff", "--stat", "--find-renames"]:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if argv[:4] == ["git", "diff", "--name-status", "--find-renames"]:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected argv: {argv!r}")

    monkeypatch.setattr("bakeoff.review_context.subprocess.run", fake_run)

    context = build_review_context(
        ReviewContextOptions(include_changed_files=True),
        tmp_path,
        "2026-05-16T12:00:00+00:00",
    )

    assert ["git", "rev-parse", "--verify", "HEAD^{commit}"] in calls
    assert "patch" not in context.included_sections
    assert context.patch is None


def test_oversize_patch_fails_without_truncation(tmp_path, monkeypatch):
    def fake_run(argv, **kwargs):
        outputs = {
            ("git", "rev-parse", "--show-toplevel"): f"{tmp_path}\n",
            ("git", "rev-parse", "HEAD"): "head\n",
            ("git", "branch", "--show-current"): "feature\n",
            ("git", "rev-parse", "--verify", "main^{commit}"): "base\n",
            ("git", "status", "--porcelain"): "",
        }
        key = tuple(argv)
        if key in outputs:
            return subprocess.CompletedProcess(argv, 0, stdout=outputs[key], stderr="")
        if argv[:4] == ["git", "diff", "--stat", "--find-renames"]:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if argv[:4] == ["git", "diff", "--name-status", "--find-renames"]:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if argv[:5] == ["git", "diff", "--no-ext-diff", "--find-renames", "--patch"]:
            return subprocess.CompletedProcess(argv, 0, stdout="x" * 120_001, stderr="")
        raise AssertionError(f"unexpected argv: {argv!r}")

    monkeypatch.setattr("bakeoff.review_context.subprocess.run", fake_run)

    with pytest.raises(ValidationError, match="review context patch is 120001 bytes, exceeding 120000 bytes"):
        build_review_context(
            ReviewContextOptions(base_ref="main", include_patch=True),
            tmp_path,
            "2026-05-16T12:00:00+00:00",
        )


def test_invalid_base_ref_reports_requested_ref(tmp_path, monkeypatch):
    def fake_run(argv, **kwargs):
        outputs = {
            ("git", "rev-parse", "--show-toplevel"): f"{tmp_path}\n",
            ("git", "rev-parse", "HEAD"): "head\n",
            ("git", "branch", "--show-current"): "feature\n",
        }
        key = tuple(argv)
        if key in outputs:
            return subprocess.CompletedProcess(argv, 0, stdout=outputs[key], stderr="")
        if argv == ["git", "rev-parse", "--verify", "missing^{commit}"]:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="fatal: bad revision\n")
        raise AssertionError(f"unexpected argv: {argv!r}")

    monkeypatch.setattr("bakeoff.review_context.subprocess.run", fake_run)

    with pytest.raises(ValidationError, match="review context base ref not found: missing"):
        build_review_context(
            ReviewContextOptions(base_ref="missing"),
            tmp_path,
            "2026-05-16T12:00:00+00:00",
        )


def test_git_command_failure_includes_stderr_tail(tmp_path, monkeypatch):
    def fake_run(argv, **kwargs):
        outputs = {
            ("git", "rev-parse", "--show-toplevel"): f"{tmp_path}\n",
            ("git", "rev-parse", "HEAD"): "head\n",
            ("git", "branch", "--show-current"): "feature\n",
            ("git", "rev-parse", "--verify", "main^{commit}"): "base\n",
            ("git", "status", "--porcelain"): "",
        }
        key = tuple(argv)
        if key in outputs:
            return subprocess.CompletedProcess(argv, 0, stdout=outputs[key], stderr="")
        if argv[:4] == ["git", "diff", "--stat", "--find-renames"]:
            return subprocess.CompletedProcess(
                argv,
                128,
                stdout="",
                stderr="line one\nline two\nfatal: ambiguous argument\n",
            )
        raise AssertionError(f"unexpected argv: {argv!r}")

    monkeypatch.setattr("bakeoff.review_context.subprocess.run", fake_run)

    with pytest.raises(ValidationError, match="(?s)review context diffstat command failed: .*fatal: ambiguous argument"):
        build_review_context(
            ReviewContextOptions(base_ref="main"),
            tmp_path,
            "2026-05-16T12:00:00+00:00",
        )
