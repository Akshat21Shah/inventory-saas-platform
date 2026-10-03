"""WhatsApp template approval (ADR-049 item 12, the Phase 6 carry-over).

A real provider sends only templates it has approved, so each platform WhatsApp template records
where it stands (not submitted, submitted, approved, rejected), set by the super admin as the
provider answers. When approval is required (a real provider;
``WHATSAPP_REQUIRE_APPROVED_TEMPLATES``):

- a message goes in the person's language if that template is approved, else in English if that
  one is, else it is kept as "Not sent: template not approved" (in-app and email still go);
- the rules editor offers WhatsApp only where the template is approved, and warns about rules
  already using an unapproved one.

The mock treats every template as approved, so dev and tests send as before.
"""

from uuid import UUID

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.notifications.models import ApprovalStatus, Audience, Channel, PlatformTemplate
from common.errors import InvalidFields, NotFound

# Kept when the text changes: the provider approved the old words, not the new ones.
TEXT_CHANGED_NOTE = "The text changed after it was submitted; submit it again."


def approvals_required() -> bool:
    return bool(settings.WHATSAPP_REQUIRE_APPROVED_TEMPLATES)


def _template(event_code: str, audience: str, locale: str) -> PlatformTemplate | None:
    return PlatformTemplate.objects.filter(
        event_code=event_code,
        audience=audience,
        channel=Channel.WHATSAPP,
        locale=locale,
        is_active=True,
    ).first()


def status_of(event_code: str, audience: str, locale: str = "en") -> str:
    row = _template(event_code, audience, locale)
    return row.approval_status if row else ApprovalStatus.NOT_SUBMITTED


def is_ready(event_code: str, audience: str, locale: str = "en") -> bool:
    """Can this template be sent now?"""
    return not approvals_required() or status_of(event_code, audience, locale) == (
        ApprovalStatus.APPROVED
    )


def sendable_locale(event_code: str, locale: str, audience: str = Audience.SHOP) -> str | None:
    """The language to send a WhatsApp message in: the person's when its template is approved,
    else English's; None when neither may be sent."""
    if not approvals_required():
        return locale
    for loc in dict.fromkeys((locale, "en")):
        if status_of(event_code, audience, loc) == ApprovalStatus.APPROVED:
            return loc
    return None


def set_approval(template_id: UUID, status: str, note: str = "") -> PlatformTemplate:
    """The super admin records the provider's answer for one WhatsApp template. Audited."""
    row = PlatformTemplate.objects.filter(pk=template_id).first()
    if row is None:
        raise NotFound()
    if row.channel != Channel.WHATSAPP:
        raise InvalidFields(
            {"status": [_("Only WhatsApp templates are approved by the provider.")]}
        )
    if status not in ApprovalStatus.values:
        raise InvalidFields(
            {"status": [_("Choose not submitted, submitted, approved or rejected.")]}
        )
    note = note.strip()
    if status == ApprovalStatus.REJECTED and not note:
        raise InvalidFields({"note": [_("Say why the provider rejected it.")]})
    before = row.approval_status
    row.approval_status, row.approval_note = status, note[:300]
    row.approval_changed_at = timezone.now()
    row.save(update_fields=["approval_status", "approval_note", "approval_changed_at"])
    audit.record(
        "notifications.template_approval_changed",
        target=row,
        target_repr=f"{row.whatsapp_template_name} {row.locale}",
        changes={"approval_status": [before, status]},
        metadata={"note": row.approval_note} if row.approval_note else {},
        tenant_id=None,
    )
    return row


def reset_when_text_changes(row: PlatformTemplate, body_before: str | None) -> str | None:
    """A submitted or approved template whose words change goes back to "not submitted".
    Returns the status it had, or None when nothing changed."""
    if row.channel != Channel.WHATSAPP or body_before is None or body_before == row.body:
        return None
    if row.approval_status == ApprovalStatus.NOT_SUBMITTED:
        return None
    before = row.approval_status
    row.approval_status, row.approval_note = ApprovalStatus.NOT_SUBMITTED, TEXT_CHANGED_NOTE
    row.approval_changed_at = timezone.now()
    return before
