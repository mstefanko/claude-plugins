"""Gated live probe for Claude Code Task dispatch under coordinator settings."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .phase_pump import _allowed_tools_arg


def run_capability_probe() -> dict[str, Any]:
    claude = os.environ.get("CLAUDE_BIN")
    if not claude:
        return {"status": "skip", "reason": "CLAUDE_BIN is unset"}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        settings_path = root / "coordinator-settings.json"
        settings = {"permissions": {"allow": _allowed_tools_arg("dispatcher"), "deny": []}}
        settings_path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        prompt = 'Call Task(subagent_type="general-purpose", prompt="echo OK") once, then stop.'
        argv = [
            claude,
            "-p",
            "--disable-slash-commands",
            "--settings",
            str(settings_path),
            "--output-format",
            "json",
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            *_allowed_tools_arg("dispatcher"),
        ]
        try:
            proc = subprocess.run(
                argv,
                input=prompt,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "status": "fail",
                "reason": "claude capability probe timed out",
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
            }
        combined = "\n".join([proc.stdout or "", proc.stderr or ""])
        return {
            "status": "pass" if proc.returncode == 0 and "Task" in combined else "fail",
            "returncode": proc.returncode,
            "task_invocation_observed": "Task" in combined,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }


__all__ = ["run_capability_probe"]
