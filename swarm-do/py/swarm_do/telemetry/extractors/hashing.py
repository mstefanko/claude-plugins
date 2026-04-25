"""stable_finding_hash_v1 — byte-parity with the Phase 9b bash implementation.

Algorithm (pinned; do NOT change without bumping to _v2):

    line_bucket = line_start // 10
    payload     = f"{file_normalized}|{category_class}|{line_bucket}|{short_summary}"
    hash        = sha256(payload.encode("utf-8")).hexdigest()

Parity reference: the original Phase 9b bash block labeled
"stable_finding_hash_v1". That implementation used `shasum -a 256 | awk '{print $1}'`
(or `sha256sum` on Linux). Both emit identical lowercase hex for the same
UTF-8 byte input.

Phase 10a (mstefanko-plugins-utu) will introduce `_v2` with a tokenization
step; this module stays frozen.
"""

from __future__ import annotations

import hashlib


def stable_finding_hash_v1(
    file_normalized: str,
    category_class: str,
    line_start: int,
    short_summary: str,
) -> str:
    """Return 64-char lowercase sha256 hex of the pinned 4-field payload."""
    line_bucket = line_start // 10
    payload = f"{file_normalized}|{category_class}|{line_bucket}|{short_summary}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
