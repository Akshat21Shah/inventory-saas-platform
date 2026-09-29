"""The payment gateway adapter interface (ADR-049 items 9 and 11).

Each distributor connects its own account; money settles to it. We create a gateway order for
the amount, the shop pays on the gateway's checkout, and the payment counts only when the
gateway's signed webhook (or our reconciliation asking the gateway) says it was captured, never
on the shop's screen alone. Amounts are in paise between us and the adapter.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


class GatewayError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


class SignatureInvalid(Exception):
    """A webhook whose signature doesn't match: ignored (and logged), never trusted."""


@dataclass(frozen=True)
class GatewayKeys:
    provider: str
    mode: str
    key_id: str
    key_secret: str
    webhook_secret: str


@dataclass(frozen=True)
class GatewayOrder:
    order_id: str
    amount_paise: int
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GatewayPayment:
    payment_id: str
    order_id: str
    amount_paise: int
    status: str  # CAPTURED, FAILED, PENDING
    captured_at: datetime | None = None
    method: str = ""
    error: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GatewayEvent:
    event_id: str
    kind: str  # PAYMENT_CAPTURED, PAYMENT_FAILED, OTHER
    payment: GatewayPayment | None
    raw: dict[str, Any] = field(default_factory=dict)


class GatewayClient(Protocol):
    def verify(self, keys: GatewayKeys) -> None:
        """Sign in with the keys; raises GatewayError when they don't work."""

    def create_order(
        self, keys: GatewayKeys, *, amount_paise: int, receipt: str, notes: dict[str, str]
    ) -> GatewayOrder: ...

    def checkout(
        self,
        keys: GatewayKeys,
        order: GatewayOrder,
        *,
        name: str,
        description: str,
        prefill: dict[str, str],
    ) -> dict[str, Any]:
        """What the shop's page needs to open the gateway's checkout (no secrets)."""

    def parse_webhook(
        self, keys: GatewayKeys, body: bytes, headers: Mapping[str, str]
    ) -> GatewayEvent:
        """Check the signature (raises SignatureInvalid) and read the event."""

    def order_payments(self, keys: GatewayKeys, order_id: str) -> list[GatewayPayment]:
        """The payments made against an order (reconciliation)."""
