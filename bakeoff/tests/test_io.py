import json

import pytest

from bakeoff import io as io_module
from bakeoff.io import copy_file_atomic, write_json_atomic, write_text_atomic


def test_write_text_atomic_replaces_file(tmp_path):
    path = tmp_path / "artifact.txt"
    path.write_text("old\n", encoding="utf-8")

    write_text_atomic(path, "new\n")

    assert path.read_text(encoding="utf-8") == "new\n"
    assert list(tmp_path.glob(".artifact.txt.*.tmp")) == []


def test_atomic_helpers_create_parent_directories(tmp_path):
    text_path = tmp_path / "nested" / "artifact.txt"
    write_text_atomic(text_path, "new\n")

    source = tmp_path / "source.txt"
    source.write_text("source\n", encoding="utf-8")
    copied_path = tmp_path / "other" / "copied.txt"
    copy_file_atomic(source, copied_path)

    assert text_path.read_text(encoding="utf-8") == "new\n"
    assert copied_path.read_text(encoding="utf-8") == "source\n"


def test_write_json_atomic_formats_sorted_json(tmp_path):
    path = tmp_path / "artifact.json"

    write_json_atomic(path, {"b": 1, "a": 2})

    assert path.read_text(encoding="utf-8") == '{\n  "a": 2,\n  "b": 1\n}\n'
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 2, "b": 1}


def test_write_text_atomic_cleans_temp_after_replace_failure(tmp_path, monkeypatch):
    path = tmp_path / "artifact.txt"
    path.write_text("old\n", encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(io_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        write_text_atomic(path, "new\n")

    assert path.read_text(encoding="utf-8") == "old\n"
    assert list(tmp_path.glob(".artifact.txt.*.tmp")) == []
