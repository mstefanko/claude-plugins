"""One-off helper for capturing redacted claude-print fixture envelopes."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .context_bundle import render_context_bundle
from .phase_pump import _allowed_tools_arg, _append_claude_print_contract
from .phase_sessions import init_phase_sessions, phase_handoff_path, phase_result_path, start_phase, claim_next_phase
from .tests.phase_session_fixtures import make_prepared_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", choices=["complete", "failed", "blocked", "needs_input"], default="complete")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--claude-path")
    args = parser.parse_args(argv)

    claude = args.claude_path or shutil.which("claude")
    if not claude:
        raise SystemExit("claude CLI not found on PATH")

    with tempfile.TemporaryDirectory() as td:
        repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
        init_phase_sessions(run_id, data_dir=data, repo_root=repo)
        claim = claim_next_phase(run_id, data_dir=data, repo_root=repo, lease_owner="capture-fixture")
        started = start_phase(
            run_id,
            "1",
            launcher="claude-print",
            data_dir=data,
            lease_owner=str(claim["lease_owner"]),
            session_name=f"swarmdaddy-{run_id}-1",
        )
        attempt = int(started["phase"]["attempt"])
        context = render_context_bundle(run_id=run_id, phase_id="1", role="dispatcher", data_dir=data, repo_root=repo)
        result_path = phase_result_path(run_id, "1", attempt, data_dir=data)
        handoff_path = phase_handoff_path(run_id, "1", attempt, data_dir=data)
        prompt = Path(context["prompt_path"]).read_text(encoding="utf-8")
        prompt = _append_claude_print_contract(
            prompt,
            result_path=result_path,
            handoff_path=handoff_path,
            status_values=["blocked", "complete", "failed", "needs_input"],
        )
        prompt += f"\nFor fixture capture, finish this tiny phase with status `{args.status}`.\n"
        proc = subprocess.run(
            [
                claude,
                "-p",
                "--output-format",
                "json",
                "--permission-mode",
                "dontAsk",
                "--allowedTools",
                *_allowed_tools_arg(),
            ],
            check=False,
            capture_output=True,
            text=True,
            input=prompt,
        )
        redacted = _redact(proc.stdout, data / "runs" / run_id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(redacted.rstrip() + "\n", encoding="utf-8")
        manifest = {
            "returncode": proc.returncode,
            "stderr_redacted": _redact(proc.stderr, data / "runs" / run_id),
            "result_exists": result_path.is_file(),
            "handoff_exists": handoff_path.is_file(),
        }
        args.output.with_suffix(args.output.suffix + ".manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


def _redact(text: str, run_dir: Path) -> str:
    return text.replace(str(run_dir), "<RUN_DIR>")


if __name__ == "__main__":
    raise SystemExit(main())
