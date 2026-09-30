"""Shops paying online (ADR-049 items 9 and 10; Phase 7 plan answers 5, 6 and 10).

Checkout
- A shop pays a bill (its full balance), everything it owes, or an amount it chooses (at least
  ₹1; with advances off, no more than it owes). No surcharge. The amount is worked out here.
- One active checkout per shop and target (a bill, "everything", "an amount") at a time: a
  second tap or tab gets the same one (the database refuses two). A stale one, or one for an
  amount that has changed and was never opened, expires first; a new one starts.
- The gateway order is created while the shop waits (it needs it to pay); a gateway that doesn't
  answer means no checkout, and the shop is told to try again.

Confirmation
- A payment counts only when the gateway's signed webhook (or our reconciliation, asking the
  gateway itself) says it was captured; what the shop's page says is noted, never trusted.
- Each gateway event is handled once (its id); each gateway payment is recorded once.
- It is recorded through the normal payment flow: a receipt, credited on the capture date, the
  chosen bill first, "Paid online by <login>". An amount other than the checkout's is recorded
  as paid and flagged for staff to review; with advances off, any excess is kept as credit.

Reconciliation (every 15 minutes): checkouts not confirmed after a few minutes are asked about;
captured payments whose webhook never came are recorded; stale checkouts expire.
"""

import hashlib
import logging
from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.billing.models import DocumentStatus, Invoice
from apps.ledger.models import RetailerAccount
from apps.notifications.context import distributor_name
from apps.payments import gateway_config
from apps.payments import services as payments
from apps.payments.gateway import get_gateway
from apps.payments.gateway.base import (
    GatewayError,
    GatewayEvent,
    GatewayPayment,
    SignatureInvalid,
)
from apps.payments.models import GatewayConfig, Payment, PaymentIntent, WebhookEvent
from apps.payments.services import DueAmount, OnlinePaymentInput
from apps.platform.models import Tenant
from apps.platform.selectors import get_setting
from apps.retailers.models import Retailer
from common.dates import to_ist
from common.error_codes import ErrorCode
from common.errors import DomainError, InvalidFields, NotFound
from common.tenancy import tenant_context, tenant_transaction

logger = logging.getLogger(__name__)

CHECKOUT_MINUTES = 30
MIN_AMOUNT = Decimal("1.00")
RECONCILE_AFTER = timedelta(minutes=3)  # not confirmed after this: ask the gateway
RECONCILE_EVERY = timedelta(minutes=15)
ST = PaymentIntent.Status
P = PaymentIntent.Purpose


class GatewayUnavailable(DomainError):
    status_code = 503
    code = ErrorCode.PAYMENT_GATEWAY_UNAVAILABLE
    default_message = "Payment service is busy, please try again in a minute."


def _paise(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value())


def owed(shop: Retailer) -> Decimal:
    account = RetailerAccount.objects.filter(retailer=shop).first()
    return max(Decimal(account.balance), Decimal("0")) if account else Decimal("0")


def amount_for(
    shop: Retailer, purpose: str, invoice: Invoice | None, custom: Decimal | None
) -> Decimal:
    if purpose == P.INVOICE:
        assert invoice is not None
        if invoice.status != DocumentStatus.ISSUED or invoice.balance_due <= 0:
            raise InvalidFields({"invoice_id": ["This bill has nothing left to pay."]})
        return Decimal(invoice.balance_due)
    if purpose == P.OUTSTANDING:
        total = owed(shop)
        if total <= 0:
            raise InvalidFields({"purpose": ["You have nothing to pay right now."]})
        return total
    if custom is None or custom < MIN_AMOUNT or custom != custom.quantize(Decimal("0.01")):
        raise InvalidFields({"amount": ["Enter at least ₹1, in rupees and paise."]})
    if not get_setting("payments.hold_advances", shop.tenant_id) and custom > owed(shop):
        raise InvalidFields({"amount": ["That's more than you owe right now."]})
    return custom


def _lock_checkouts(shop: Retailer) -> None:
    """One checkout decision per shop at a time (the unique index is the backstop)."""
    key = int(hashlib.sha256(f"checkout:{shop.pk}".encode()).hexdigest()[:15], 16)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])


def start_checkout(
    shop: Retailer,
    *,
    purpose: str,
    invoice_id: UUID | None,
    amount: Decimal | None,
    by: User,
) -> PaymentIntent:
    """The shop's active checkout for this target, or a new one (in the request transaction)."""
    config = gateway_config.ready(shop.tenant_id)
    if purpose not in P.values:
        raise InvalidFields({"purpose": ["Choose a bill, everything you owe or an amount."]})
    invoice = None
    if purpose == P.INVOICE:
        invoice = Invoice.objects.filter(pk=invoice_id, retailer=shop).first()
        if invoice is None:
            raise NotFound()
    _lock_checkouts(shop)
    now = timezone.now()
    active: PaymentIntent | None = PaymentIntent.objects.filter(
        retailer=shop, purpose=purpose, invoice=invoice, status__in=PaymentIntent.ACTIVE
    ).first()
    if active is not None and active.expires_at > now:
        if active.status == ST.ATTEMPTED:
            return active  # the shop may be paying it right now: never start a second one
        if active.amount == amount_for(shop, purpose, invoice, amount):
            return active  # a second tap or tab
    if active is not None:  # stale, or for an amount no longer right
        if not _reconcile_one(active, config):  # it may have been paid; not knowing, keep it
            raise GatewayUnavailable()
        active.refresh_from_db()
        if active.status == ST.PAID:
            return active
        if active.status in PaymentIntent.ACTIVE:
            active.status = ST.EXPIRED
            active.save(update_fields=["status", "updated_at"])
    total = amount_for(shop, purpose, invoice, amount)
    intent = PaymentIntent(
        retailer=shop,
        purpose=purpose,
        invoice=invoice,
        amount=total,
        provider=config.provider,
        expires_at=now + timedelta(minutes=CHECKOUT_MINUTES),
        created_by=by,
    )
    try:
        with transaction.atomic():
            intent.save()
    except IntegrityError:  # another tap won; use its checkout
        found: PaymentIntent | None = PaymentIntent.objects.filter(
            retailer=shop, purpose=purpose, invoice=invoice, status__in=PaymentIntent.ACTIVE
        ).first()
        if found is None:
            raise
        return found
    keys = gateway_config.keys_of(config)
    gateway = get_gateway(keys.provider)
    what = f"Bill {invoice.number}" if invoice else "Payment"
    try:
        order = gateway.create_order(
            keys,
            amount_paise=_paise(total),
            receipt=f"PAY-{intent.pk.hex[:12]}",
            notes={"intent": str(intent.pk), "shop": shop.code},
        )
    except GatewayError as exc:
        logger.warning("gateway order failed", extra={"code": exc.code})
        raise GatewayUnavailable() from exc
    tenant = Tenant.objects.get(pk=shop.tenant_id)
    intent.provider_order_id = order.order_id
    intent.checkout = gateway.checkout(
        keys,
        order,
        name=distributor_name(tenant),
        description=f"{what} · {shop.shop_name}",
        prefill={"name": shop.shop_name, "contact": shop.mobile, "email": shop.email},
    )
    intent.save(update_fields=["provider_order_id", "checkout", "updated_at"])
    return intent


def note_outcome(intent: PaymentIntent, outcome: str) -> PaymentIntent:
    """What the shop's page says happened (informational only: payment comes from the gateway)."""
    if outcome not in ("success", "failed", "dismissed"):
        raise InvalidFields({"outcome": ["Unknown outcome."]})
    intent.client_outcome = outcome
    if intent.status == ST.CREATED:
        intent.status = ST.ATTEMPTED
    intent.save(update_fields=["client_outcome", "status", "updated_at"])
    return intent


# --- The gateway's webhook ------------------------------------------------------------------------


def handle_webhook(
    provider: str, token: str, body: bytes, headers: Mapping[str, str]
) -> tuple[int, str]:
    """Public: the tenant from the webhook address's token, the signature checked with its secret,
    the event handled once. Returns (HTTP status, what happened)."""
    tenant = Tenant.objects.filter(webhook_token=token).first()
    if tenant is None:
        return 404, "unknown"
    with tenant_context(tenant.pk):
        config = GatewayConfig.objects.filter(provider=provider.upper()).first()
        if config is None:
            return 404, "unknown"
        keys = gateway_config.keys_of(config)
        try:
            event = get_gateway(keys.provider).parse_webhook(keys, body, headers)
        except SignatureInvalid:
            logger.warning("webhook signature invalid", extra={"provider": provider})
            return 400, "signature"
        event_id = event.event_id or hashlib.sha256(body).hexdigest()[:64]
        with transaction.atomic():
            row, created = WebhookEvent.objects.get_or_create(
                provider=keys.provider,
                event_id=event_id,
                defaults={"kind": event.kind, "payload": event.raw},
            )
            if not created and row.processed_at is not None:
                return 200, "duplicate"
            row = WebhookEvent.objects.select_for_update().get(pk=row.pk)
            if row.processed_at is not None:
                return 200, "duplicate"
            result = apply_event(event, keys.provider)
            row.result, row.processed_at = result, timezone.now()
            row.save(update_fields=["result", "processed_at", "updated_at"])
        return 200, result


def apply_event(event: GatewayEvent, provider: str) -> str:
    payment = event.payment
    if payment is None or event.kind == "OTHER":
        return "ignored"
    intent = (
        PaymentIntent.objects.select_for_update()
        .filter(provider=provider, provider_order_id=payment.order_id)
        .first()
    )
    if intent is None:
        return "unknown order"
    if event.kind == "PAYMENT_CAPTURED":
        return capture(intent, payment)
    if intent.status in PaymentIntent.ACTIVE:  # a failed try: the shop may try again
        intent.status, intent.last_error = ST.ATTEMPTED, payment.error[:300]
        intent.save(update_fields=["status", "last_error", "updated_at"])
    return "failed"


def capture(intent: PaymentIntent, paid: GatewayPayment) -> str:
    """Record a captured gateway payment (once) against its checkout."""
    if paid.status != "CAPTURED":
        return "not captured"
    if Payment.objects.filter(
        gateway_provider=intent.provider, gateway_payment_id=paid.payment_id
    ).exists():
        return "duplicate"
    amount = Decimal(paid.amount_paise) / 100
    review = ""
    if intent.status == ST.PAID:
        review = "A second payment on a checkout that was already paid."
    elif amount != intent.amount:
        review = f"Paid ₹{amount:,.2f}; the checkout was for ₹{intent.amount:,.2f}."
    pay_first: tuple[DueAmount, ...] = ()
    if intent.invoice_id:
        bill = Invoice.objects.filter(pk=intent.invoice_id, status=DocumentStatus.ISSUED).first()
        if bill is not None and bill.balance_due > 0:
            pay_first = (DueAmount("INVOICE", bill.pk, min(amount, Decimal(bill.balance_due))),)
    login = intent.created_by
    who = (login.full_name or login.phone or "the shop") if login else "the shop"
    captured = paid.captured_at or timezone.now()
    payment = payments.record_online_payment(
        OnlinePaymentInput(
            retailer_id=intent.retailer_id,
            amount=amount,
            payment_date=to_ist(captured).date(),
            provider=intent.provider,
            gateway_payment_id=paid.payment_id,
            intent_id=intent.pk,
            pay_first=pay_first,
            notes=f"Paid online by {who}",
            review_reason=review,
        ),
        by=login,
    )
    if intent.status != ST.PAID:
        intent.status, intent.payment, intent.paid_at = ST.PAID, payment, timezone.now()
        intent.save(update_fields=["status", "payment", "paid_at", "updated_at"])
    return "captured"


# --- Reconciliation -------------------------------------------------------------------------------


def _captured(config: GatewayConfig, order_id: str) -> list[GatewayPayment] | None:
    """What the gateway captured for an order; None when it doesn't answer."""
    keys = gateway_config.keys_of(config)
    try:
        found = get_gateway(keys.provider).order_payments(keys, order_id)
    except GatewayError:
        return None
    return [paid for paid in found if paid.status == "CAPTURED"]


def _record_captured(intent_id: UUID, captured: list[GatewayPayment]) -> None:
    for paid in captured:
        capture(PaymentIntent.objects.select_for_update().get(pk=intent_id), paid)
    PaymentIntent.objects.filter(pk=intent_id).update(reconciled_at=timezone.now())


def _reconcile_one(intent: PaymentIntent, config: GatewayConfig) -> bool:
    """Before a checkout is replaced: ask the gateway whether it was paid after all. False when
    the gateway doesn't answer (then nothing may replace it: the shop could pay twice)."""
    if not intent.provider_order_id:
        return True
    captured = _captured(config, intent.provider_order_id)
    if captured is None:
        return False
    _record_captured(intent.pk, captured)
    return True


def reconcile(tenant_id: UUID) -> dict[str, int]:
    """Every 15 minutes: checkouts not confirmed are asked about; stale ones expire."""
    now = timezone.now()
    done = {"asked": 0, "captured": 0, "expired": 0}
    with tenant_transaction(tenant_id):
        config = GatewayConfig.objects.first()
        if config is None:
            return done
        ids = list(
            PaymentIntent.objects.filter(
                status__in=PaymentIntent.ACTIVE, created_at__lt=now - RECONCILE_AFTER
            )
            .exclude(reconciled_at__gt=now - RECONCILE_EVERY)
            .values_list("pk", flat=True)[:200]
        )
    for pk in ids:
        with tenant_transaction(tenant_id):
            found = PaymentIntent.objects.filter(pk=pk).values_list("provider_order_id", flat=True)
            order_id = found.first() or ""
        captured = _captured(config, order_id) if order_id else []  # no transaction held
        with tenant_transaction(tenant_id):
            intent = PaymentIntent.objects.select_for_update(skip_locked=True).filter(pk=pk).first()
            if intent is None or intent.status not in PaymentIntent.ACTIVE or captured is None:
                continue
            done["asked"] += 1
            _record_captured(intent.pk, captured)
            intent.refresh_from_db()
            if intent.status == ST.PAID:
                done["captured"] += 1
            elif intent.expires_at <= now:
                intent.status = ST.EXPIRED
                intent.save(update_fields=["status", "updated_at"])
                done["expired"] += 1
    return done


# --- Staff ---------------------------------------------------------------------------------------


def mark_reviewed(payment_id: UUID, *, note: str, by: User) -> Payment:
    payment: Payment | None = Payment.objects.select_for_update().filter(pk=payment_id).first()
    if payment is None:
        raise NotFound()
    if not payment.needs_review:
        raise InvalidFields({"payment": ["This payment doesn't need a review."]})
    payment.needs_review, payment.reviewed_at, payment.reviewed_by = False, timezone.now(), by
    payment.save(update_fields=["needs_review", "reviewed_at", "reviewed_by", "updated_at"])
    audit.record(
        "payments.online_reviewed",
        target=payment,
        target_repr=payment.number,
        metadata={"reason": payment.review_reason, "note": note.strip()[:300]},
    )
    return payment


def describe(intent: PaymentIntent) -> dict[str, Any]:
    payment = intent.payment
    return {
        "id": intent.pk,
        "purpose": intent.purpose,
        "invoice_id": intent.invoice_id,
        "invoice_number": intent.invoice.number if intent.invoice else "",
        "amount": intent.amount,
        "status": intent.status,
        "provider": intent.provider,
        "checkout": intent.checkout or None,
        "expires_at": intent.expires_at,
        "last_error": intent.last_error,
        "payment_id": payment.pk if payment else None,
        "receipt_number": payment.number if payment else "",
        "created_at": intent.created_at,
        "paid_at": intent.paid_at,
        "shop_name": intent.retailer.shop_name,
        "retailer_id": intent.retailer_id,
        "client_outcome": intent.client_outcome,
    }
