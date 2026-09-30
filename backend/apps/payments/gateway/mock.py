"""A mock payment gateway for dev and tests (ADR-049 item 11). It behaves like a gateway:

- Keys: a key id starting ``mock_`` and any secret, except the secret ``wrong``.
- Orders get ``order_mock_…`` ids and remember their amount; the checkout is a dev page
  (``/api/v1/dev/mock-gateway/<order>/``) where you choose "Pay" or "Fail".
- ``simulate`` pays (or fails) an order, optionally for another amount, and returns the webhook
  exactly as the gateway would send it: a JSON body signed with HMAC-SHA256 of the webhook
  secret (``X-Mock-Signature``) and an event id (``X-Mock-Event-Id``). Tests post it to our
  webhook; the dev page does too.
- ``order_payments`` answers reconciliation from what was simulated.
- ``script("DOWN")`` / ``script("TIMEOUT")`` makes the next call fail as if the gateway were
  unavailable / didn't answer in time.
The mock's own header and field names are ours; nothing here describes a real gateway.
"""

import hashlib
import hmac
import json
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from django.core.cache import cache
from django.utils import timezone

from apps.payments.gateway.base import (
    GatewayError,
    GatewayEvent,
    GatewayKeys,
    GatewayOrder,
    GatewayPayment,
    SignatureInvalid,
)

SIGNATURE, EVENT_ID = "X-Mock-Signature", "X-Mock-Event-Id"
_SCRIPT = "mockpay:script"


def _order_key(order_id: str) -> str:
    return f"mockpay:order:{order_id}"


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class MockGateway:
    @staticmethod
    def script(*outcomes: str) -> None:
        cache.set(_SCRIPT, [*(cache.get(_SCRIPT) or []), *outcomes], None)

    @staticmethod
    def _down() -> None:
        queue = cache.get(_SCRIPT) or []
        if queue:
            cache.set(_SCRIPT, queue[1:], None)
            if queue[0] == "DOWN":
                raise GatewayError("UNAVAILABLE", "The gateway is not available.", retryable=True)
            if queue[0] == "TIMEOUT":
                raise GatewayError("TIMEOUT", "The gateway didn't answer in time.", retryable=True)

    def verify(self, keys: GatewayKeys) -> None:
        self._down()
        if not keys.key_id.startswith("mock_") or not keys.key_secret:
            raise GatewayError("AUTH_FAILED", "The gateway refused these keys.")
        if keys.key_secret == "wrong":  # noqa: S105 - the mock's refused value, not a secret
            raise GatewayError("AUTH_FAILED", "The gateway refused these keys.")

    def create_order(
        self, keys: GatewayKeys, *, amount_paise: int, receipt: str, notes: dict[str, str]
    ) -> GatewayOrder:
        self.verify(keys)
        order_id = f"order_mock_{uuid.uuid4().hex[:14]}"
        stored = {"amount": amount_paise, "receipt": receipt, "notes": notes, "payments": []}
        cache.set(_order_key(order_id), stored, None)
        return GatewayOrder(order_id, amount_paise, {"mock": True, "id": order_id})

    def checkout(
        self,
        keys: GatewayKeys,
        order: GatewayOrder,
        *,
        name: str,
        description: str,
        prefill: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "provider": "MOCK",
            "key": keys.key_id,
            "order_id": order.order_id,
            "amount": order.amount_paise,
            "currency": "INR",
            "name": name,
            "description": description,
            "prefill": prefill,
            "checkout_url": f"/api/v1/dev/mock-gateway/{order.order_id}/",
        }

    def parse_webhook(
        self, keys: GatewayKeys, body: bytes, headers: Mapping[str, str]
    ) -> GatewayEvent:
        given = headers.get(SIGNATURE, "")
        if not given or not hmac.compare_digest(given, sign(keys.webhook_secret, body)):
            raise SignatureInvalid()
        data = json.loads(body)
        payment = _payment(data["payment"]) if data.get("payment") else None
        kind = {"payment.captured": "PAYMENT_CAPTURED", "payment.failed": "PAYMENT_FAILED"}
        return GatewayEvent(
            event_id=headers.get(EVENT_ID, ""),
            kind=kind.get(data.get("event", ""), "OTHER"),
            payment=payment,
            raw=data,
        )

    def order_payments(self, keys: GatewayKeys, order_id: str) -> list[GatewayPayment]:
        self.verify(keys)
        stored = cache.get(_order_key(order_id)) or {"payments": []}
        return [_payment(p) for p in stored["payments"]]

    # --- Dev and tests: what the gateway would do when the shop pays ------------------------

    @staticmethod
    def simulate(
        keys: GatewayKeys,
        order_id: str,
        *,
        outcome: str = "CAPTURED",
        amount_paise: int | None = None,
        event_id: str | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        """Pay (or fail) an order; returns the signed webhook body and headers."""
        stored = cache.get(_order_key(order_id))
        if stored is None:
            raise GatewayError("NOT_FOUND", "No such order.")
        payment = {
            "id": f"pay_mock_{uuid.uuid4().hex[:14]}",
            "order_id": order_id,
            "amount": amount_paise if amount_paise is not None else stored["amount"],
            "status": outcome,
            "method": "upi",
            "captured_at": timezone.now().isoformat() if outcome == "CAPTURED" else None,
            "error": "" if outcome == "CAPTURED" else "The payment was declined.",
        }
        stored["payments"].append(payment)
        cache.set(_order_key(order_id), stored, None)
        event = "payment.captured" if outcome == "CAPTURED" else "payment.failed"
        body = json.dumps({"event": event, "payment": payment}).encode()
        headers = {
            SIGNATURE: sign(keys.webhook_secret, body),
            EVENT_ID: event_id or f"evt_mock_{uuid.uuid4().hex[:14]}",
        }
        return body, headers


def _payment(data: dict[str, Any]) -> GatewayPayment:
    captured = data.get("captured_at")
    return GatewayPayment(
        payment_id=data["id"],
        order_id=data["order_id"],
        amount_paise=int(data["amount"]),
        status=data["status"],
        captured_at=datetime.fromisoformat(captured) if captured else None,
        method=data.get("method", ""),
        error=data.get("error", ""),
        raw=data,
    )
