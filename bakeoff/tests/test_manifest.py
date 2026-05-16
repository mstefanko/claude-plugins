import json

from bakeoff import manifest as manifest_module
from bakeoff.manifest import build_run_manifest, write_run_manifest


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


def test_write_run_manifest_delegates_to_shared_atomic_io(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "work-order.json").write_text(json.dumps({"type": "gather"}) + "\n", encoding="utf-8")
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
    calls = []

    def fake_write_json_atomic(path, data, *, sort_keys=True):
        calls.append((path, data, sort_keys))
        path.write_text(json.dumps(data, indent=2, sort_keys=sort_keys) + "\n", encoding="utf-8")

    monkeypatch.setattr(manifest_module, "write_json_atomic", fake_write_json_atomic)

    manifest = write_run_manifest(run_dir)

    assert calls == [(run_dir / "manifest.json", manifest, True)]
    assert json.loads((run_dir / "manifest.json").read_text())["run_id"] == "run"
