"""What every channel adapter returns or raises (CLAUDE.md §4: integrations behind adapters)."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SendResult:
    provider: str
    message_id: str = ""
    response: dict[str, Any] = field(default_factory=dict)


class DeliveryError(Exception):
    """The provider failed; tried again with backoff."""


class PermanentDeliveryError(DeliveryError):
    """Trying again won't help (address refused, template rejected): failed at once."""
