"""Razorpay, through its official Python SDK (ADR-049 item 11).

TODO(verify): every request field, event name, header and payload path below against Razorpay's
official documentation before going live (PROGRESS pre-production item 25): the Orders API fields
(amount in paise, currency, receipt, notes), the checkout options, the webhook events (payment
captured / failed), the signature and event id headers, the SDK's signature helper, payment status
names, the capture time field, and fetching an order's payments. Test keys only outside production
(``PAYMENTS_ALLOW_LIVE``).
"""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from apps.payments.gateway.base import (
    GatewayError,
    GatewayEvent,
    GatewayKeys,
    GatewayOrder,
    GatewayPayment,
    SignatureInvalid,
)

SIGNATURE_HEADER = "X-Razorpay-Signature"  # TODO(verify)
EVENT_ID_HEADER = "X-Razorpay-Event-Id"  # TODO(verify)
EVENTS = {"payment.captured": "PAYMENT_CAPTURED", "payment.failed": "PAYMENT_FAILED"}
STATUSES = {"captured": "CAPTURED", "failed": "FAILED"}  # TODO(verify); others: PENDING


def _client(keys: GatewayKeys) -> Any:
    import razorpay

    return razorpay.Client(auth=(keys.key_id, keys.key_secret))


def _error(exc: Exception) -> GatewayError:
    import razorpay

    if isinstance(exc, razorpay.errors.BadRequestError):
        return GatewayError("REFUSED", str(exc) or "Razorpay refused the request.")
    return GatewayError("UNAVAILABLE", "Razorpay could not be reached.", retryable=True)


def _header(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""


class RazorpayGateway:
    def verify(self, keys: GatewayKeys) -> None:
        try:
            _client(keys).order.all({"count": 1})  # TODO(verify): a cheap authenticated call
        except Exception as exc:
            error = _error(exc)
            if error.code == "REFUSED":
                raise GatewayError("AUTH_FAILED", "Razorpay refused these keys.") from exc
            raise error from exc

    def create_order(
        self, keys: GatewayKeys, *, amount_paise: int, receipt: str, notes: dict[str, str]
    ) -> GatewayOrder:
        body = {  # TODO(verify): field names
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt[:40],
            "notes": notes,
        }
        try:
            order = _client(keys).order.create(body)
        except Exception as exc:
            raise _error(exc) from exc
        return GatewayOrder(str(order["id"]), int(order["amount"]), dict(order))

    def checkout(
        self,
        keys: GatewayKeys,
        order: GatewayOrder,
        *,
        name: str,
        description: str,
        prefill: dict[str, str],
    ) -> dict[str, Any]:
        return {  # TODO(verify): checkout options
            "provider": "RAZORPAY",
            "key": keys.key_id,
            "order_id": order.order_id,
            "amount": order.amount_paise,
            "currency": "INR",
            "name": name,
            "description": description,
            "prefill": prefill,
        }

    def parse_webhook(
        self, keys: GatewayKeys, body: bytes, headers: Mapping[str, str]
    ) -> GatewayEvent:
        import razorpay

        signature = _header(headers, SIGNATURE_HEADER)
        if not signature:
            raise SignatureInvalid()
        try:
            _client(keys).utility.verify_webhook_signature(
                body.decode(), signature, keys.webhook_secret
            )
        except razorpay.errors.SignatureVerificationError as exc:
            raise SignatureInvalid() from exc
        data = json.loads(body)
        entity = ((data.get("payload") or {}).get("payment") or {}).get("entity")  # TODO(verify)
        return GatewayEvent(
            event_id=_header(headers, EVENT_ID_HEADER),
            kind=EVENTS.get(data.get("event", ""), "OTHER"),
            payment=_payment(entity) if entity else None,
            raw=data,
        )

    def order_payments(self, keys: GatewayKeys, order_id: str) -> list[GatewayPayment]:
        try:
            found = _client(keys).order.payments(order_id)  # TODO(verify)
        except Exception as exc:
            raise _error(exc) from exc
        return [_payment(item) for item in found.get("items", [])]


def _payment(entity: dict[str, Any]) -> GatewayPayment:
    status = STATUSES.get(str(entity.get("status", "")), "PENDING")
    created = entity.get("created_at")  # TODO(verify): the capture time field
    return GatewayPayment(
        payment_id=str(entity["id"]),
        order_id=str(entity.get("order_id") or ""),
        amount_paise=int(entity.get("amount") or 0),
        status=status,
        captured_at=datetime.fromtimestamp(int(created), tz=UTC)
        if created and status == "CAPTURED"
        else None,
        method=str(entity.get("method") or ""),
        error=str(entity.get("error_description") or ""),
        raw=entity,
    )
