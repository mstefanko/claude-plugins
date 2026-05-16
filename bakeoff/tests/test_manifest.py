import json

from bakeoff.manifest import build_run_manifest


def test_manifest_does_not_infer_review_context_from_background_block(tmp_path):
    run_dir = tmp_path / "legacy-effective"
    run_dir.mkdir()
    (run_dir / "work-order.json").write_text(
        json.dumps(
            {
                "type": "gather",
                "background": "<generated_review_context>\nBase ref: main\n</generated_review_context>",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "decision.json").write_text(
        json.dumps({"decision_kind": "structured_union", "judge_ran": True}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "meta.json").write_text(
        json.dumps(
            {
                "type": "gather",
                "started_at": "2026-05-16T12:00:00+00:00",
                "finished_at": "2026-05-16T12:01:00+00:00",
                "resolved_models": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text("# report\n", encoding="utf-8")

    manifest = build_run_manifest(run_dir)

    assert manifest["review_context"] == {"present": False}
