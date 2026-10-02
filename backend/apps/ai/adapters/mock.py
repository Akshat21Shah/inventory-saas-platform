"""The mock embedding provider (ADR-058 item 1): local, deterministic and free, for dev and tests.

Each text becomes a unit vector of hashed features: its words, and the character trigrams of each
word (with a space either side), so "magi nodles" lands near "Maggi Noodles". It knows nothing of
meaning across languages; a real model does that.
"""

from __future__ import annotations

import hashlib
import math
import re

from apps.ai.adapters.base import DIMENSIONS, Embedded

_WORD = re.compile(r"\w+", re.UNICODE)
# Trigrams carry most of the weight: a misspelt word shares trigrams, not the word itself.
WORD_WEIGHT, TRIGRAM_WEIGHT = 0.3, 1.0


def _bucket(feature: str) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % DIMENSIONS, 1.0 if (value >> 32) & 1 else -1.0


def vector(text: str) -> list[float]:
    out = [0.0] * DIMENSIONS
    for word in _WORD.findall(text.lower()):
        index, sign = _bucket(f"w:{word}")
        out[index] += sign * WORD_WEIGHT
        padded = f" {word} "
        for i in range(len(padded) - 2):
            index, sign = _bucket(f"t:{padded[i : i + 3]}")
            out[index] += sign * TRIGRAM_WEIGHT
    norm = math.sqrt(sum(x * x for x in out))
    return [x / norm for x in out] if norm else out


class MockEmbeddings:
    name = "mock"

    def embed(self, texts: list[str], *, timeout: float) -> Embedded:
        return Embedded(
            vectors=[vector(text) for text in texts],
            units=sum(len(text) for text in texts),
            model="mock-trigram-256",
        )
