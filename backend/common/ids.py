"""Time-ordered UUIDv7 primary keys (ADR-001): index-friendly and non-enumerable."""

import os
import time
import uuid

_UUID7 = getattr(uuid, "uuid7", None)  # stdlib from Python 3.14


def uuid7() -> uuid.UUID:
    """Return a RFC 9562 version-7 UUID (48-bit ms timestamp + 74 random bits)."""
    if _UUID7 is not None:
        value: uuid.UUID = _UUID7()
        return value
    ts_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")  # 80 random bits, 74 used
    rand_a = (rand >> 68) & 0xFFF
    rand_b = rand & ((1 << 62) - 1)
    as_int = (
        ((ts_ms & ((1 << 48) - 1)) << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    )
    return uuid.UUID(int=as_int)
