"""Sending notifications (ADR-048): one row at a time, never holding a transaction while a
provider is called, every try logged as a ``DeliveryAttempt``.

States: PENDING → SENDING (claimed by one worker) → SENT, or back to PENDING with ``send_after``
set for the next try (1, 2, 4, 8 and 16 minutes), or FAILED at once when the provider says trying
again won't help, or after the last try. ``send_due`` (every minute) sends what is due: retries,
messages held for quiet hours, and anything whose first enqueue was lost. A worker that died
mid-send leaves SENDING; after ``STALE_SENDING`` the row is tried again (at-least-once, like the
outbox).

In-app rows are delivered when created; the person's open sessions are told to refresh their
bell (``push_in_app``).

A shop's or supplier's email about a document also carries its PDF (ADR-054), besides the secure
link: while the PDF is still being printed the email waits (``PDF_RECHECK`` at a time, at most
``PDF_WAIT``, not counted as a try); a PDF that failed, is still not ready, can't be read or is
over ``MAX_ATTACHMENT_BYTES`` leaves the link alone. What happened is kept on the row and the
attempt (``attachment``)."""

import logging
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.notifications.adapters.base import DeliveryError, PermanentDeliveryError, SendResult
from apps.notifications.models import Channel, DeliveryAttempt, Notification
from common.tenancy import require_tenant_id, tenant_transaction

if TYPE_CHECKING:
    from apps.notifications.adapters.email import Attachment
    from apps.notifications.adapters.whatsapp import SenderIdentity
    from apps.notifications.links import Pdf

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 6  # the first try and five retries
RETRY_MINUTES = (1, 2, 4, 8, 16)
STALE_SENDING = timedelta(minutes=10)
LOST_AFTER = timedelta(minutes=2)  # PENDING, never tried: its enqueue was lost
BATCH = 500
PDF_RECHECK = timedelta(seconds=5)  # a PDF is usually printed within seconds
PDF_WAIT = timedelta(minutes=3)
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024  # bigger: the link alone
S = Notification.Status


def enqueue(ids: list[UUID]) -> None:
    """After the rows' transaction commits."""
    from apps.notifications.tasks import deliver

    tenant_id = str(require_tenant_id())

    def send() -> None:
        for pk in ids:
            deliver.apply_async(kwargs={"notification_id": str(pk), "tenant_id": tenant_id})

    if ids:
        transaction.on_commit(send)


def after_fan_out(event_id: UUID) -> None:
    """Queue the event's new external rows and ring the in-app bells (in the fan-out's
    transaction; both happen after it commits)."""
    rows = Notification.objects.filter(event_id=event_id)
    enqueue(
        list(rows.filter(status=S.PENDING, send_after__isnull=True).values_list("pk", flat=True))
    )
    users = list(
        rows.filter(channel=Channel.IN_APP, status=S.SENT)
        .values_list("recipient_id", flat=True)
        .distinct()
    )
    if users:
        tenant_id = require_tenant_id()
        transaction.on_commit(lambda: push_in_app(tenant_id, users))


def release_held_for_irn(document_kind: str, object_id: UUID) -> int:
    """The document's IRN arrived or failed: its bill messages held for it go now (ADR-049
    item 6). In the caller's transaction; sent after it commits."""
    now = timezone.now()
    rows = Notification.objects.filter(
        status=S.PENDING,
        send_after__gt=now,
        data__held_for_irn=True,
        data__document__kind=document_kind,
        data__document__id=str(object_id),
    )
    ids = list(rows.values_list("pk", flat=True))
    rows.update(send_after=now, updated_at=now)
    enqueue(ids)
    return len(ids)


def push_in_app(tenant_id: UUID, user_ids: list[UUID]) -> None:
    """Tell the people's open sessions to refetch their unread count (never fails the caller)."""
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    from common.live import user_group

    layer = get_channel_layer()
    if layer is None:
        return
    try:
        for user_id in user_ids:
            async_to_sync(layer.group_send)(
                user_group(tenant_id, user_id),
                {"type": "live.event", "data": {"type": "notification"}},
            )
    except Exception:  # the bell also refreshes on the next page load
        logger.warning("in-app push failed", exc_info=True)


@dataclass(frozen=True)
class Claimed:
    row: Notification
    distributor: str
    reply_to: str
    whatsapp: "SenderIdentity | None"
    pdf: "Pdf | None" = None


def _pdf_for(row: Notification) -> "Pdf | None":
    from apps.notifications.links import pdf_of

    document = row.data.get("document") or {}
    if row.channel != Channel.EMAIL or not row.data.get("attach") or not document:
        return None
    return pdf_of(document.get("kind", ""), UUID(document["id"]))


def _wait_for_pdf(row: Notification, now: datetime) -> bool:
    """The PDF is being printed: hold the email for ``PDF_RECHECK`` (not a try), up to
    ``PDF_WAIT`` from the first time it was due."""
    since = row.data.get("pdf_wait_since")
    if since is not None and now - datetime.fromisoformat(since) >= PDF_WAIT:
        return False
    row.send_after = now + PDF_RECHECK
    row.data = {**row.data, "pdf_wait_since": since or now.isoformat()}
    row.save(update_fields=["send_after", "data", "updated_at"])
    from apps.notifications.tasks import deliver

    tenant_id, pk = str(require_tenant_id()), str(row.pk)
    transaction.on_commit(  # ``send_due`` would also pick it up
        lambda: deliver.apply_async(
            kwargs={"notification_id": pk, "tenant_id": tenant_id},
            countdown=int(PDF_RECHECK.total_seconds()),
        )
    )
    return True


def _claim(notification_id: UUID) -> Claimed | None:
    """Mark the row SENDING and read what sending needs (RLS: only inside the transaction)."""
    from apps.notifications.adapters.whatsapp import tenant_sender
    from apps.notifications.context import current_tenant, distributor_name

    now = timezone.now()
    with tenant_transaction(require_tenant_id()):
        row = (
            Notification.objects.select_for_update(skip_locked=True)
            .filter(pk=notification_id, status=S.PENDING)
            .first()
        )
        if row is None or (row.send_after is not None and row.send_after > now):
            return None
        pdf = _pdf_for(row)
        if pdf is not None and pdf.status not in ("READY", "FAILED") and _wait_for_pdf(row, now):
            return None
        row.status, row.attempts = S.SENDING, row.attempts + 1
        row.save(update_fields=["status", "attempts", "updated_at"])
        tenant = current_tenant()
        sender = tenant_sender() if row.channel == Channel.WHATSAPP else None
        return Claimed(row, distributor_name(tenant), tenant.email, sender, pdf)


def _send(claimed: Claimed) -> SendResult:
    row, name = claimed.row, claimed.distributor
    if row.channel == Channel.EMAIL:
        from apps.notifications.adapters.email import Email, get_email_sender

        attachments, note = _attachments(claimed.pdf)
        email = Email(row.address, row.title, row.body, name, claimed.reply_to, attachments)
        result = get_email_sender().send(email)
        return replace(result, response={**result.response, "attachment": note}) if note else result
    if row.channel == Channel.WHATSAPP and claimed.whatsapp is not None:
        from apps.notifications.adapters.whatsapp import WhatsAppMessage, get_whatsapp_client

        wa = row.data.get("whatsapp") or {}
        message = WhatsAppMessage(
            row.address,
            wa.get("template", ""),
            wa.get("language", "en"),
            tuple(wa.get("parameters", ())),
            wa.get("category", ""),
            row.body,
        )
        sender = claimed.whatsapp
        return get_whatsapp_client(sender.provider).send_template(message, sender)
    if row.channel == Channel.SMS:
        from django.conf import settings

        from apps.accounts.adapters.sms import get_sms_sender

        template = row.event_code.replace(".", "_")  # its DLT template, e.g. retailer_welcome
        get_sms_sender().send_text(row.address, row.body, sender_name=name, template=template)
        return SendResult(f"sms-{settings.SMS_PROVIDER}")
    raise PermanentDeliveryError(f"nothing sends {row.channel}")


def _attachments(pdf: "Pdf | None") -> tuple[tuple["Attachment", ...], dict[str, str]]:
    """The PDF to attach and what happened: ``{"file": …}`` or ``{"skipped": reason}``."""
    from apps.notifications.adapters.email import Attachment
    from common.storage import get_storage

    if pdf is None:
        return (), {}
    if pdf.status != "READY" or not pdf.key:
        return (), {"skipped": "PDF_FAILED" if pdf.status == "FAILED" else "NOT_READY"}
    try:
        content = get_storage().get(pdf.key)
    except Exception:  # the link still opens it
        logger.warning("attachment unreadable", extra={"key": pdf.key}, exc_info=True)
        return (), {"skipped": "UNREADABLE"}
    if len(content) > MAX_ATTACHMENT_BYTES:
        return (), {"skipped": "TOO_LARGE"}
    return (Attachment(pdf.filename, content),), {"file": pdf.filename}


def deliver(notification_id: UUID) -> str:
    """Try once. Returns the row's status afterwards, or "" when it wasn't ours to send (sent,
    being sent, not due)."""
    claimed = _claim(notification_id)
    if claimed is None:
        return ""
    row = claimed.row
    started = time.monotonic()
    result: SendResult | None = None
    error, permanent = "", False
    try:
        result = _send(claimed)
    except PermanentDeliveryError as exc:
        error, permanent = str(exc) or type(exc).__name__, True
    except DeliveryError as exc:
        error = str(exc) or type(exc).__name__
    except Exception as exc:  # an adapter bug: logged, retried like a provider failure
        logger.exception("notification delivery crashed", extra={"notification": str(row.pk)})
        error = f"{type(exc).__name__}: {exc}"
    duration = int((time.monotonic() - started) * 1000)
    now = timezone.now()
    with tenant_transaction(require_tenant_id()):
        DeliveryAttempt.objects.create(
            notification_id=row.pk,
            attempt_no=row.attempts,
            provider=result.provider if result else "",
            status=S.SENT if result else S.FAILED,
            response=result.response if result else {},
            error=error[:500],
            duration_ms=duration,
        )
        fields: dict[str, Any] = {"updated_at": now}
        if result is not None:
            fields |= {
                "status": S.SENT,
                "sent_at": now,
                "provider": result.provider,
                "provider_message_id": result.message_id[:120],
                "last_error": "",
            }
            if "attachment" in result.response:
                fields["data"] = {**row.data, "attachment": result.response["attachment"]}
        elif permanent or row.attempts % MAX_ATTEMPTS == 0:  # a retry by hand: 6 more
            fields |= {"status": S.FAILED, "last_error": error[:500]}
        else:
            wait = RETRY_MINUTES[(row.attempts - 1) % MAX_ATTEMPTS]
            fields |= {
                "status": S.PENDING,
                "send_after": now + timedelta(minutes=wait),
                "last_error": error[:500],
            }
        Notification.objects.filter(pk=row.pk, status=S.SENDING).update(**fields)
    return str(fields.get("status", ""))


def due() -> list[UUID]:
    """What ``send_due`` sends now for the active tenant (and SENDING rows given up on)."""
    now = timezone.now()
    Notification.objects.filter(status=S.SENDING, updated_at__lt=now - STALE_SENDING).update(
        status=S.PENDING, send_after=now, updated_at=now
    )
    rows = Notification.objects.filter(status=S.PENDING).exclude(channel=Channel.IN_APP)
    ready = rows.filter(send_after__lte=now) | rows.filter(
        send_after__isnull=True, created_at__lt=now - LOST_AFTER
    )
    return list(ready.order_by("created_at").values_list("pk", flat=True)[:BATCH])


def retry(notification_id: UUID) -> bool:
    """Staff (or the super admin) try a failed message again, with a fresh round of tries (the
    attempt numbers carry on)."""
    failed = Notification.objects.filter(pk=notification_id, status=S.FAILED)
    attempts = failed.values_list("attempts", flat=True).first()
    if attempts is None:
        return False
    round_start = -(-attempts // MAX_ATTEMPTS) * MAX_ATTEMPTS  # up to a whole round
    updated = failed.update(
        status=S.PENDING, attempts=round_start, send_after=None, updated_at=timezone.now()
    )
    if updated:
        enqueue([notification_id])
    return bool(updated)
