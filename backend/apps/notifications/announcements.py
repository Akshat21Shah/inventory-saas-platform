"""Announcements (ADR-048 item 16): notices a distributor shows on every shop's home between two
dates, sent once to each shop in-app when they start, and by WhatsApp too when asked (marketing
category, and only to shops that agreed to WhatsApp). Audited."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.notifications.models import Announcement, Channel
from apps.retailers.models import Retailer
from common.errors import InvalidFields, NotFound

MAX_TITLE, MAX_BODY = 120, 1000


@dataclass(frozen=True)
class AnnouncementInput:
    title: str
    body: str
    starts_at: datetime
    ends_at: datetime | None = None
    is_active: bool = True
    send_whatsapp: bool = False


def _check(data: AnnouncementInput) -> None:
    errors: dict[str, list[str]] = {}
    if not data.title.strip():
        errors["title"] = ["Enter a title."]
    elif len(data.title) > MAX_TITLE:
        errors["title"] = [f"Use at most {MAX_TITLE} characters."]
    if not data.body.strip():
        errors["body"] = ["Enter the message."]
    elif len(data.body) > MAX_BODY:
        errors["body"] = [f"Use at most {MAX_BODY} characters."]
    if data.ends_at is not None and data.ends_at <= data.starts_at:
        errors["ends_at"] = ["The end must be after the start."]
    if errors:
        raise InvalidFields(errors)


def save(data: AnnouncementInput, *, by: User, announcement_id: UUID | None = None) -> Announcement:
    """Create or change one (``notifications.manage``). Once sent, changing it doesn't send it
    again; the shop home shows the new text."""
    _check(data)
    if announcement_id is None:
        row = Announcement()
        before: dict[str, Any] = {}
    else:
        found = Announcement.objects.select_for_update().filter(pk=announcement_id).first()
        if found is None:
            raise NotFound()
        row = found
        before = {"title": row.title, "body": row.body, "is_active": row.is_active}
    row.title, row.body = data.title.strip(), data.body.strip()
    row.starts_at, row.ends_at = data.starts_at, data.ends_at
    row.is_active = data.is_active
    if row.published_at is None:
        row.send_whatsapp = data.send_whatsapp
    row.save()
    after = {"title": row.title, "body": row.body, "is_active": row.is_active}
    audit.record(
        "notifications.announcement_saved",
        target=row,
        target_repr=row.title,
        changes={k: [before.get(k), v] for k, v in after.items() if before.get(k) != v},
        metadata={"send_whatsapp": row.send_whatsapp},
    )
    return row


def showing(now: datetime | None = None) -> QuerySet[Announcement]:
    """What shops see on their home now."""
    moment = now or timezone.now()
    return Announcement.objects.filter(is_active=True, starts_at__lte=moment).filter(
        Q(ends_at__isnull=True) | Q(ends_at__gt=moment)
    )


def publish_due(now: datetime | None = None) -> int:
    """Send each announcement that has started once to every shop (from ``send_due``)."""
    from apps.notifications.context import EventContext
    from apps.notifications.jobs import job_event_id, notify

    moment = now or timezone.now()
    due = list(showing(moment).filter(published_at__isnull=True))
    shops = list(Retailer.objects.filter(deleted_at__isnull=True, status=Retailer.Status.ACTIVE))
    for announcement in due:
        for shop in shops:
            ctx = EventContext(
                "announcement.published",
                {"shop": shop.shop_name, "title": announcement.title, "message": announcement.body},
                retailer=shop,
                shop_path="/shop",
                extra={"add_channels": {Channel.WHATSAPP} if announcement.send_whatsapp else set()},
            )
            notify(job_event_id(announcement.pk, shop.pk), ctx)
        Announcement.objects.filter(pk=announcement.pk).update(published_at=moment)
    return len(due)
