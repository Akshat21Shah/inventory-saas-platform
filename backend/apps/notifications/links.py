"""Secure document links (ADR-048 item 8): a WhatsApp or email message carries a link that opens
one document without signing in.

The token is 32 random bytes; only its SHA-256 is stored, so the table alone can't open anything.
A link lives ⚙ ``notifications.document_link_days`` (default 30). Opening it counts the open and
redirects to a fresh 5-minute storage link to the document's *current* PDF, so a receipt printed
again as "Cheque bounced" or a voucher marked "Reversed" is what the shop sees. Staff who manage
the document can revoke its links (audited).

Links are served on the tenant's own address (``{slug}.<domain>/api/v1/public/documents/…``,
proxied by the web app); the tenant comes from the host and the token is looked up within it.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db.models import F
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.notifications.models import DocumentLink
from common.errors import NotFound
from common.hosts import web_url

K = DocumentLink.Kind


@dataclass(frozen=True)
class Source:
    model: str  # app_label.Model
    key: str
    status: str
    permission: str  # who may revoke its links


SOURCES: dict[str, Source] = {
    K.INVOICE: Source("billing.Invoice", "pdf_key", "pdf_status", "invoices.manage"),
    K.CREDIT_NOTE: Source("billing.CreditNote", "pdf_key", "pdf_status", "invoices.manage"),
    K.ORDER_CONFIRMATION: Source(
        "billing.OrderConfirmation", "pdf_key", "pdf_status", "orders.manage"
    ),
    K.RECEIPT: Source(
        "payments.Payment", "receipt_pdf_key", "receipt_pdf_status", "payments.record"
    ),
    K.REFUND_VOUCHER: Source(
        "payments.Refund", "voucher_pdf_key", "voucher_pdf_status", "payments.record"
    ),
}


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def link_days() -> int:
    from apps.platform.selectors import get_setting

    return int(get_setting("notifications.document_link_days"))


def create(kind: str, object_id: UUID, tenant_slug: str) -> str:
    """A new link for one document (the active tenant's); returns its URL."""
    token = secrets.token_urlsafe(32)
    DocumentLink.objects.create(
        token_hash=token_hash(token),
        kind=kind,
        object_id=object_id,
        expires_at=timezone.now() + timedelta(days=link_days()),
    )
    return web_url(f"/api/v1/public/documents/{token}/", tenant_slug=tenant_slug)


class LinkState:
    READY = "READY"  # redirect to the PDF
    PREPARING = "PREPARING"  # the PDF is being printed: try again shortly
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    UNKNOWN = "UNKNOWN"


def _document(kind: str, object_id: UUID) -> Any:
    from django.apps import apps

    source = SOURCES[kind]
    return apps.get_model(source.model).objects.filter(pk=object_id).first()


def open_link(token: str) -> tuple[str, str]:
    """(state, signed PDF URL when READY) for the active tenant. Counts every open of a live
    link, also while the PDF is still being printed."""
    from apps.billing.documents import LINK_SECONDS
    from common.storage import get_storage

    if not token or len(token) > 100:
        return LinkState.UNKNOWN, ""
    link = DocumentLink.objects.select_for_update().filter(token_hash=token_hash(token)).first()
    if link is None:
        return LinkState.UNKNOWN, ""
    if link.revoked_at is not None:
        return LinkState.REVOKED, ""
    now = timezone.now()
    if link.expires_at <= now:
        return LinkState.EXPIRED, ""
    DocumentLink.objects.filter(pk=link.pk).update(
        open_count=F("open_count") + 1, last_opened_at=now, updated_at=now
    )
    document = _document(link.kind, link.object_id)
    if document is None:
        return LinkState.UNKNOWN, ""
    source = SOURCES[link.kind]
    key, status = getattr(document, source.key), getattr(document, source.status)
    if status != "READY" or not key:
        return LinkState.PREPARING, ""
    return LinkState.READY, get_storage().presigned_get(key, LINK_SECONDS)


def revoke(kind: str, object_id: UUID, *, by: User) -> int:
    """Withdraw every live link to one document. Returns how many were withdrawn."""
    from rest_framework.exceptions import PermissionDenied

    if kind not in SOURCES:
        raise NotFound()
    if not by.has_permission_code(SOURCES[kind].permission):
        raise PermissionDenied()
    document = _document(kind, object_id)
    if document is None:
        raise NotFound()
    now = timezone.now()
    count = DocumentLink.objects.filter(
        kind=kind, object_id=object_id, revoked_at__isnull=True, expires_at__gt=now
    ).update(revoked_at=now, revoked_by=by, updated_at=now)
    audit.record(
        "notifications.document_links_revoked",
        target=document,
        target_repr=str(getattr(document, "number", "") or object_id),
        metadata={"kind": kind, "links": count},
    )
    return count


def links_for(kind: str, object_id: UUID) -> list[DocumentLink]:
    return list(DocumentLink.objects.filter(kind=kind, object_id=object_id).order_by("-created_at"))
