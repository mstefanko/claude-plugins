"""Stdlib-only JSONL helpers.

`stream_read` yields parsed dicts one row at a time.
`atomic_write` writes an iterable of rows via a tempfile + fsync + os.replace,
so partial writes never land at the final path.

No third-party deps — Phase 1 bootstrap constraint.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Iterator, Mapping


def stream_read(path: str | os.PathLike) -> Iterator[dict]:
    """Yield each line of a JSONL file as a parsed dict.

    Blank lines are skipped. A missing file raises FileNotFoundError.
    JSON parse errors propagate to the caller (callers may wrap per-row to
    keep fail-open semantics where desired).
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            yield json.loads(stripped)


def atomic_write(path: str | os.PathLike, rows: Iterable[Mapping]) -> None:
    """Atomically write `rows` (an iterable of JSON-serializable mappings)
    to `path` as newline-delimited JSON.

    Writes to a NamedTemporaryFile in the destination directory, flushes +
    fsyncs, then os.replace() swaps it into place. Partial writes are never
    visible at the final path.
    """
    target = Path(path)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        for row in rows:
            tmp.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, target)
    except Exception:
        tmp.close()
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass
        raise
