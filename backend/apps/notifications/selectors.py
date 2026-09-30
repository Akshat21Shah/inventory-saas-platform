"""Reads for the notification screens (ADR-048): a person's inbox, the delivery log, the rules
matrix with the WhatsApp estimate, and (super admin, audited alias) failures across tenants."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from apps.accounts.models import Permission, User
from apps.notifications import approval
from apps.notifications.catalog import DEFAULT_TEXTS, EVENTS, ONLY_FOR, RECIPIENT_CHANNELS
from apps.notifications.consent import opted_in_count
from apps.notifications.models import (
    ApprovalStatus,
    Channel,
    Notification,
    PlatformTemplate,
    Recipient,
)
from apps.notifications.rules import available, effective_rules
from common.platform_db import platform_db

ESTIMATE_DAYS = 30
SKIP = Notification.SkipReason
# WhatsApp rows that would be paid messages with the feature on (not blocked by consent etc.).
PAID = Q(status__in=["PENDING", "SENDING", "SENT", "FAILED"]) | Q(skip_reason=SKIP.FEATURE_OFF)


def inbox(user: User) -> QuerySet[Notification]:
    """The person's in-app messages in the active tenant, newest first."""
    return Notification.objects.filter(
        recipient=user, channel=Channel.IN_APP, status=Notification.Status.SENT
    ).order_by("-created_at", "-id")


def unread_count(user: User) -> int:
    return inbox(user).filter(read_at__isnull=True).count()


def mark_read(user: User, notification_id: UUID | None = None) -> int:
    """One message, or all of them."""
    rows = inbox(user).filter(read_at__isnull=True)
    if notification_id is not None:
        rows = rows.filter(pk=notification_id)
    return rows.update(read_at=timezone.now(), updated_at=timezone.now())


@dataclass(frozen=True)
class DeliveryFilters:
    status: str = ""
    channel: str = ""
    event: str = ""
    retailer_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    search: str = ""


def deliveries(filters: DeliveryFilters) -> QuerySet[Notification]:
    """The delivery log: every row with its outcome (in-app rows too, as the record)."""
    rows = Notification.objects.select_related("recipient", "retailer")
    if filters.status:
        rows = rows.filter(status=filters.status)
    if filters.channel:
        rows = rows.filter(channel=filters.channel)
    if filters.event:
        rows = rows.filter(event_code=filters.event)
    if filters.retailer_id:
        rows = rows.filter(retailer_id=filters.retailer_id)
    if filters.date_from:
        rows = rows.filter(created_at__date__gte=filters.date_from)
    if filters.date_to:
        rows = rows.filter(created_at__date__lte=filters.date_to)
    if filters.search:
        term = filters.search.strip()
        rows = rows.filter(
            Q(address__icontains=term)
            | Q(title__icontains=term)
            | Q(retailer__shop_name__icontains=term)
            | Q(recipient__full_name__icontains=term)
        )
    return rows.order_by("-created_at", "-id")


def delivery_counts(since: datetime | None = None) -> dict[str, int]:
    """Totals per status over the last 7 days (the log's header; failures stand out)."""
    moment = since or timezone.now() - timedelta(days=7)
    counts = (
        Notification.objects.filter(created_at__gte=moment)
        .exclude(channel=Channel.IN_APP)
        .values("status")
        .annotate(n=Count("id"))
    )
    found = {row["status"]: row["n"] for row in counts}
    return {status: found.get(status, 0) for status in Notification.Status.values}


# --- The rules matrix ---------------------------------------------------------------------------


def _prices() -> dict[str, Decimal | None]:
    from apps.platform.selectors import get_platform_setting

    prices: dict[str, Decimal | None] = {}
    for category in ("UTILITY", "MARKETING", "AUTHENTICATION"):
        raw = get_platform_setting(f"platform.whatsapp_price_{category.lower()}")
        prices[category] = Decimal(str(raw)) if raw not in (None, "") else None
    return prices


def _estimates(since: datetime) -> dict[str, int]:
    """Per event, messages the last 30 days would have cost on WhatsApp. Events already on
    WhatsApp count their WhatsApp rows; the others count the shops their in-app messages
    reached, scaled by the share of shops that agreed to WhatsApp."""
    recent = Notification.objects.filter(created_at__gte=since)
    on_whatsapp = dict(
        recent.filter(PAID, channel=Channel.WHATSAPP)
        .values_list("event_code")
        .annotate(n=Count("id"))
    )
    shop_messages = dict(
        recent.filter(
            channel=Channel.IN_APP, retailer__isnull=False, recipient__user_type="RETAILER"
        )
        .values_list("event_code")
        .annotate(n=Count("event_id", distinct=True))
    )
    shares = opted_in_count()
    share = Decimal(shares["opted_in"]) / shares["shops"] if shares["shops"] else Decimal(0)
    estimates = {code: int(n) for code, n in on_whatsapp.items()}
    for code, n in shop_messages.items():
        estimates.setdefault(code, int((Decimal(n) * share).to_integral_value()))
    return estimates


def rules_matrix() -> dict[str, Any]:
    """Every event with its rules in force, what the tenant changed, and the WhatsApp cost."""
    from apps.platform.selectors import is_feature_enabled
    from common.tenancy import require_tenant_id

    by_event: dict[str, list[dict[str, Any]]] = {}
    for rule in effective_rules():
        by_event.setdefault(rule.event, []).append(
            {
                "recipient": rule.recipient,
                "permission": rule.permission,
                "channels": list(rule.channels),
                "enabled": rule.enabled,
                "compulsory": rule.compulsory,
                "is_default": rule.is_default,
            }
        )
    prices = _prices()
    estimates = _estimates(timezone.now() - timedelta(days=ESTIMATE_DAYS))
    required = approval.approvals_required()
    statuses = {
        (row["event_code"], row["audience"]): row["approval_status"]
        for row in PlatformTemplate.objects.filter(
            channel=Channel.WHATSAPP, locale="en", is_active=True
        ).values("event_code", "audience", "approval_status")
    }
    events = []
    total_cost: Decimal | None = Decimal("0")
    for code, event in EVENTS.items():
        if event.feature and not available(code):
            continue
        rules = by_event.get(code, [])
        uses_whatsapp = any(r["enabled"] and Channel.WHATSAPP in r["channels"] for r in rules)
        messages = estimates.get(code, 0) if event.shop_facing or uses_whatsapp else 0
        price = prices.get(event.category)
        cost = (price * messages).quantize(Decimal("0.01")) if price is not None else None
        if uses_whatsapp:
            total_cost = None if cost is None or total_cost is None else total_cost + cost
        events.append(
            {
                "code": code,
                "label": event.label,
                "group": event.group,
                "urgent": event.urgent,
                "category": event.category,
                "shop_facing": event.shop_facing,
                "rules": rules,
                "customised": any(not r["is_default"] for r in rules),
                "whatsapp": {
                    "enabled": uses_whatsapp,
                    "messages_30_days": messages,
                    "price": price,
                    "cost_30_days": cost,
                    "templates": [
                        {
                            "audience": audience,
                            "status": (
                                status := statuses.get(
                                    (code, audience), ApprovalStatus.NOT_SUBMITTED
                                )
                            ),
                            "ready": not required or status == ApprovalStatus.APPROVED,
                        }
                        for audience, texts in DEFAULT_TEXTS.get(code, {}).items()
                        if Channel.WHATSAPP in texts
                    ],
                },
            }
        )
    return {
        "events": events,
        "recipients": {
            k: list(v)
            for k, v in RECIPIENT_CHANNELS.items()
            if k not in ONLY_FOR or is_feature_enabled(ONLY_FOR[k][1], require_tenant_id())
        },
        "whatsapp_feature_enabled": is_feature_enabled("whatsapp", require_tenant_id()),
        "whatsapp_approval_required": required,
        "prices_set": all(p is not None for p in prices.values()),
        "whatsapp_cost_30_days": total_cost,
        "shops": opted_in_count(),
        "permissions": list(
            Permission.objects.exclude(code__startswith="platform.")
            .order_by("code")
            .values("code", "description")
        ),
    }


# --- Super admin ---------------------------------------------------------------------------------


def failures_everywhere(tenant_id: UUID | None = None) -> QuerySet[Notification]:
    """Failed messages across tenants, newest first (audited platform alias)."""
    rows = (
        Notification.objects.unscoped()
        .using(platform_db("notifications.failures_everywhere"))
        .filter(status=Notification.Status.FAILED)
        .select_related("tenant", "retailer")
    )
    if tenant_id is not None:
        rows = rows.filter(tenant_id=tenant_id)
    return rows.order_by("-updated_at", "-id")


RECIPIENT_LABELS = dict(Recipient.choices)
