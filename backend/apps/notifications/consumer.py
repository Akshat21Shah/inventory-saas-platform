"""Turns an event into notification rows (ADR-048): which notification it is, who gets it on which
channels (the tenant's rules), and what each message says. One row per person and channel, keyed
by (event, person, channel), so a redelivered event creates nothing new.

Rows that can't be sent are kept as SKIPPED with the reason (no WhatsApp consent, no address,
switched off, WhatsApp not enabled, template not approved), so the delivery log answers "why
didn't the shop get it?".
Delivery itself is ``apps.notifications.delivery`` (after this transaction commits)."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import Membership, User
from apps.accounts.permissions import OWNER_ROLE
from apps.notifications import approval, quiet
from apps.notifications import context as contexts
from apps.notifications.catalog import EVENTS
from apps.notifications.models import (
    Audience,
    Channel,
    Notification,
    NotificationPreference,
    Recipient,
)
from apps.notifications.render import render
from apps.notifications.rules import EffectiveRule, effective_rules
from apps.platform.models import Tenant
from apps.retailers.models import Retailer, RetailerUser
from common.hosts import web_url
from common.models import OutboxEvent

# Outbox events that notify someone. The rest (order_confirmation.created, stock.alert_resolved)
# are for PDFs and screens only.
HANDLED_EVENTS: tuple[str, ...] = (
    "order.placed",
    "order.on_hold",
    "order.hold_approved",
    "order.accepted",
    "order.rejected",
    "order.cancelled",
    "order.modified",
    "order.short_supplied",
    "order.dispatched",
    "order.delivered",
    "order.completed",
    "backorder.proposed",
    "backorder.allocated",
    "backorder.skipped_credit",
    "backorder.skipped_blocked",
    "backorder.cancelled",
    "backorder.repriced_cancelled",
    "stock.alert_opened",
    "invoice.issued",
    "invoice.cancelled",
    "credit_note.issued",
    "einvoice.failed",
    "report.ready",
    "report.failed",
    "ewaybill.failed",
    "payment.received",
    "payment.cleared",
    "payment.reversed",
    "payment.handed_over",
    "refund.recorded",
    "refund.reversed",
    "purchase_order.sent",
    "purchase_order.cancelled",
)
SKIP = Notification.SkipReason


def notification_code(event: OutboxEvent) -> str | None:
    """The catalogue event for an outbox event, split by context where the defaults differ."""
    kind, p = event.event_type, event.payload
    if kind == "order.placed":
        from apps.orders.models import Order

        via = Order.objects.filter(pk=p["order_id"]).values_list("placed_via", flat=True).first()
        return "order.placed_for_shop" if via == Order.PlacedVia.STAFF else kind
    if kind == "order.cancelled" and p.get("by") == "retailer":
        return "order.cancelled_by_shop"
    if kind == "order.dispatched" and _invoiced_before_dispatch(p):
        return "order.dispatched_after_invoice"
    if kind == "payment.reversed" and p.get("status") == "BOUNCED":
        return "payment.bounced"
    if kind == "backorder.repriced_cancelled" or (
        kind == "backorder.cancelled" and p.get("by") == "retailer"
    ):
        return "backorder.cancelled_by_shop"
    return kind if kind in EVENTS else None


def _invoiced_before_dispatch(payload: dict[str, Any]) -> bool:
    """The bill was issued at acceptance or allocation: the dispatch message is the news."""
    from apps.billing.models import Invoice

    trigger = (
        Invoice.objects.filter(
            order_id=payload["order_id"], fulfilment__number=payload.get("shipment", "")
        )
        .values_list("issued_trigger", flat=True)
        .first()
    )
    return trigger in (Invoice.Trigger.ON_ACCEPTANCE, Invoice.Trigger.ON_ALLOCATION)


def handle(event_id: UUID) -> int:
    """Outbox handler (tenant set, in a transaction). Returns the rows offered (existing ones are
    left as they are)."""
    event = OutboxEvent.objects.filter(pk=event_id).first()
    if event is None:
        return 0
    code = notification_code(event)
    if code is None or event.tenant_id is None:
        return 0
    tenant = Tenant.objects.get(pk=event.tenant_id)
    ctx = contexts.build(event, code, tenant)
    if ctx is None:
        return 0
    return fan_out(event.pk, ctx, tenant)


# --- Who gets it --------------------------------------------------------------------------------


@dataclass
class Target:
    user: User | None  # None for a supplier
    retailer: Retailer | None  # set for shop logins
    channels: set[str]
    compulsory: bool
    external: bool = True  # False: a shop's second login gets in-app only
    supplier: Any = None  # a supplier has no login: email only (ADR-053)


def _staff(filter_: Q) -> list[User]:
    user_ids = (
        Membership.objects.filter(filter_, is_active=True, user__is_active=True)
        .values_list("user_id", flat=True)
        .distinct()
    )
    return list(User.objects.filter(pk__in=user_ids).order_by("pk"))


def _people(rule: EffectiveRule, ctx: contexts.EventContext) -> list[tuple[User, bool]]:
    """(user, may receive external channels) for one rule."""
    if rule.recipient == Recipient.SHOP:
        if ctx.retailer is None:
            return []
        logins = list(
            RetailerUser.objects.filter(retailer=ctx.retailer, user__is_active=True)
            .select_related("user")
            .order_by("created_at")
        )
        # WhatsApp, SMS and email go to the shop's own number and address once, through the
        # login that signs in with the shop's number (else the first); in-app to every login.
        primary = next((x for x in logins if x.user.phone == ctx.retailer.mobile), None)
        primary = primary or (logins[0] if logins else None)
        return [(x.user, x is primary) for x in logins]
    if rule.recipient in (Recipient.SALESPERSON, Recipient.COLLECTOR):
        user_id = (
            ctx.salesperson_id if rule.recipient == Recipient.SALESPERSON else ctx.collector_id
        )
        if user_id is None:
            return []
        return [(u, True) for u in _staff(Q(user_id=user_id))]
    if rule.recipient == Recipient.STAFF_PERMISSION:
        return [(u, True) for u in _staff(Q(role__permissions__code=rule.permission))]
    if rule.recipient == Recipient.OWNERS:
        return [(u, True) for u in _staff(Q(role__code=OWNER_ROLE))]
    if rule.recipient == Recipient.DISPATCHER:
        dispatcher = ctx.extra.get("dispatcher_id")
        return [(u, True) for u in _staff(Q(user_id=dispatcher))] if dispatcher else []
    if rule.recipient == Recipient.REQUESTER:
        requester = ctx.extra.get("requester_id")
        return [(u, True) for u in _staff(Q(user_id=requester))] if requester else []
    return []


def targets(code: str, ctx: contexts.EventContext) -> list[Target]:
    """Everyone the enabled rules name, once each; a person named by several rules gets the
    union of their channels (compulsory if any rule is)."""
    found: dict[Any, Target] = {}
    for rule in effective_rules(code):
        if not rule.enabled or not rule.channels:
            continue
        if rule.recipient == Recipient.SUPPLIER:
            supplier = ctx.extra.get("supplier")
            if supplier is not None:
                target = found.setdefault(
                    ("supplier", supplier.pk), Target(None, None, set(), False, True, supplier)
                )
                target.channels |= set(rule.channels) & {Channel.EMAIL}
                target.compulsory = target.compulsory or rule.compulsory
            continue
        for user, external in _people(rule, ctx):
            person = found.get(user.pk)
            if person is None:
                shop = ctx.retailer if rule.recipient == Recipient.SHOP else None
                person = found[user.pk] = Target(user, shop, set(), False, external)
            target = person
            target.channels |= set(rule.channels)
            if rule.recipient == Recipient.SHOP:  # e.g. an announcement also sent by WhatsApp
                target.channels |= set(ctx.extra.get("add_channels", ()))
            target.compulsory = target.compulsory or rule.compulsory
    return list(found.values())


# --- What each row says -------------------------------------------------------------------------


def _address(target: Target, channel: str) -> str:
    if channel == Channel.IN_APP:
        return ""
    if target.supplier is not None:
        return str(target.supplier.email or "") if channel == Channel.EMAIL else ""
    if target.retailer is not None:
        shop = target.retailer
        return shop.email if channel == Channel.EMAIL else shop.mobile
    user = target.user
    if user is None:
        return ""
    return (user.email if channel == Channel.EMAIL else user.phone) or ""


def _skip_reason(
    target: Target,
    channel: str,
    address: str,
    *,
    whatsapp_on: bool,
    turned_off: set[tuple[UUID, str]],
    paused: bool,
) -> str:
    if paused:
        return SKIP.PAUSED  # payment reminders paused for the shop: every channel
    if channel == Channel.IN_APP:
        return ""  # never switched off (ADR-048 item 7)
    if channel == Channel.WHATSAPP and not whatsapp_on:
        return SKIP.FEATURE_OFF
    if channel == Channel.WHATSAPP and target.retailer and not target.retailer.whatsapp_opt_in:
        return SKIP.NO_WHATSAPP_OPT_IN  # compulsory events too: consent comes first
    if not address:
        return SKIP.NO_ADDRESS
    if (
        target.user is not None
        and not target.compulsory
        and (target.user.pk, channel) in turned_off
    ):
        return SKIP.TURNED_OFF
    return ""


def _irn_hold(ctx: contexts.EventContext, now: Any) -> Any:
    """Until when a bill's shop messages wait for its IRN (None: they don't)."""
    if ctx.code not in ("invoice.issued", "credit_note.issued") or ctx.document is None:
        return None
    from apps.compliance.einvoice import hold_until

    return hold_until(ctx.document[0], ctx.document[1], now)


def fan_out(event_id: UUID, ctx: contexts.EventContext, tenant: Tenant) -> int:
    """Create the event's notification rows. Scheduled jobs (reminders, announcements) call this
    with their own stable ``event_id``."""
    from apps.platform.selectors import is_feature_enabled

    event = EVENTS[ctx.code]
    if Notification.objects.filter(event_id=event_id).exists():
        return 0  # a redelivered event: nothing new (and no second document link)
    people = [t for t in targets(ctx.code, ctx) if t.external or Channel.IN_APP in t.channels]
    if not people:
        return 0
    turned_off = set(
        NotificationPreference.objects.filter(
            event_code=ctx.code,
            enabled=False,
            user__in=[t.user for t in people if t.user is not None],
        ).values_list("user_id", "channel")
    )
    whatsapp_on = is_feature_enabled("whatsapp", tenant.pk)
    paused = bool(ctx.extra.get("paused"))
    now = timezone.now()
    hold = None if event.urgent else quiet.current_hold(now)  # quiet hours (item 9)
    irn_hold = _irn_hold(ctx, now)
    rows: list[Notification] = []
    document_link = ""

    def link_for_shop() -> str:
        """One link per event, made only when a shop message will carry it."""
        nonlocal document_link
        if not document_link and ctx.document is not None:
            from apps.notifications import links

            document_link = links.create(ctx.document[0], ctx.document[1], tenant.slug)
        return document_link

    for target in people:
        shop = target.retailer is not None
        supplier = target.supplier is not None
        path = ctx.shop_path if shop else "" if supplier else ctx.staff_path
        url = web_url(path or "/", tenant_slug=tenant.slug)
        values = {**ctx.values, "link": url, "document_link": ""}
        locale = (
            (target.retailer.preferred_language if target.retailer else "")
            or (target.user.preferred_language if target.user else "")
            or "en"
        )
        for channel in sorted(target.channels):
            if channel != Channel.IN_APP and not target.external:
                continue
            address = _address(target, channel)
            reason = _skip_reason(
                target,
                channel,
                address,
                whatsapp_on=whatsapp_on,
                turned_off=turned_off,
                paused=paused,
            )
            audience = Audience.SHOP if shop else Audience.SUPPLIER if supplier else Audience.STAFF
            text_locale: str | None = locale
            if channel == Channel.WHATSAPP and not reason:
                # Only an approved template can be sent (ADR-049 item 12); the mock approves all.
                text_locale = approval.sendable_locale(ctx.code, locale, audience)
                reason = "" if text_locale else SKIP.NOT_APPROVED
            carries_link = (shop or supplier) and channel != Channel.IN_APP and not reason
            values["document_link"] = link_for_shop() if carries_link else ""
            text = render(ctx.code, channel, values, text_locale or locale, audience)
            if text is None:
                continue
            in_app = channel == Channel.IN_APP
            send_after = hold if not in_app and not reason else None
            held_for_irn = bool(irn_hold and shop and not in_app and not reason)
            if held_for_irn:  # the bill waits for its IRN, at most 10 minutes (ADR-049 item 6)
                send_after = max(send_after or now, irn_hold or now)
            rows.append(
                Notification(
                    tenant_id=tenant.pk,  # bulk_create skips save(), which fills it in
                    event_id=event_id,
                    event_code=ctx.code,
                    recipient=target.user,
                    supplier=target.supplier,
                    retailer=ctx.retailer,
                    channel=channel,
                    address=address,
                    title=text["title"],
                    body=text["body"],
                    data={
                        "path": path,
                        "url": url,
                        "whatsapp": text["whatsapp"],
                        "document": (
                            {"kind": ctx.document[0], "id": str(ctx.document[1])}
                            if ctx.document
                            else None
                        ),
                        "compulsory": target.compulsory,
                        **({"held_for_irn": True} if held_for_irn else {}),
                    },
                    urgent=event.urgent,
                    status=(
                        Notification.Status.SKIPPED
                        if reason
                        else Notification.Status.SENT
                        if in_app
                        else Notification.Status.PENDING
                    ),
                    skip_reason=reason,
                    sent_at=now if in_app else None,
                    send_after=send_after,
                    provider="in_app" if in_app else "",
                )
            )
    created = Notification.objects.bulk_create(rows, ignore_conflicts=True)
    return len(created)
