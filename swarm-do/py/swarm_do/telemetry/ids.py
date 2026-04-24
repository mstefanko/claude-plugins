"""Crockford-base32 ULID generator.

`new_ulid()` returns a 26-character identifier matching the canonical ULID
spec: 48 bits of millisecond timestamp + 80 bits of cryptographic randomness,
Crockford base32 encoded. No third-party deps.

Validator regex: ^[0-9A-HJKMNP-TV-Z]{26}$
"""

from __future__ import annotations

import secrets
import time


_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    """Return a fresh ULID as a 26-character Crockford-base32 string."""
    # 48-bit millisecond timestamp
    ts_ms = time.time_ns() // 1_000_000
    ts_bytes = ts_ms.to_bytes(6, "big", signed=False)

    # 80 bits of cryptographic randomness
    rand_bytes = secrets.token_bytes(10)

    # 128 bits total -> encode to 26 Crockford-base32 characters
    value = int.from_bytes(ts_bytes + rand_bytes, "big", signed=False)

    chars = [""] * 26
    for i in range(25, -1, -1):
        chars[i] = _CROCKFORD[value & 0x1F]
        value >>= 5
    return "".join(chars)
