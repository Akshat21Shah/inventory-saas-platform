"""The AI providers' interfaces (ADR-058 item 1). Every implementation lives behind one of these;
the app never calls a provider directly."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

DIMENSIONS = 256  # the stored vector size; a real provider's vectors are fitted to it


class AiProviderError(Exception):
    """The provider failed, timed out or isn't configured: the caller falls back."""


@dataclass(frozen=True)
class Embedded:
    vectors: list[list[float]]
    units: int  # what the provider bills (tokens or characters), for usage
    model: str


class EmbeddingProvider(Protocol):
    name: str

    def embed(self, texts: list[str], *, timeout: float) -> Embedded: ...
