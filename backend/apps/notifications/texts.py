"""Editing message texts (ADR-048 item 14), with a preview on sample values.

- A distributor overrides the in-app and email texts of any event, per language; removing its
  text brings back the platform's.
- WhatsApp and SMS texts must match what the provider approved (WhatsApp templates, DLT
  registration for SMS), so only the super admin edits them, together with the approved template
  name, language and category.

Texts may use only the event's variables, written ``{{ variable }}``; nothing else is evaluated
(``render.substitute``). Every change is audited."""

from dataclasses import dataclass
from typing import Any

from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.audit import services as audit
from apps.notifications import approval
from apps.notifications.catalog import EVENTS, whatsapp_template_name
from apps.notifications.models import (
    Audience,
    Channel,
    NotificationTemplate,
    PlatformTemplate,
    WhatsAppCategory,
)
from apps.notifications.render import VARIABLE, substitute, template_for
from common import languages
from common.errors import InvalidFields, NotFound
from common.numbers import fill

TENANT_CHANNELS = (Channel.IN_APP, Channel.EMAIL)
MAX_SUBJECT, MAX_BODY = 200, 2000
WHATSAPP_MAX_BODY = 1024  # TODO(verify): the provider's template body limit
SMS_MAX_BODY = 480  # three SMS parts; TODO(verify): the DLT template rules

# Plausible values for the preview (the distributor's own name is used for "distributor").
SAMPLE: dict[str, str] = {
    "shop": "Ganesh Kirana",
    "order_number": "ORD-2026-000123",
    "total": "₹12,450.00",
    "link": "https://example.com/…",
    "document_link": "https://example.com/d/…",
    "placed_by": "Priya (Sales)",
    "hold_reason": "Over the credit limit",
    "reason": "Out of stock",
    "changes": "Tata Salt 1 kg 10→8",
    "items": "Tata Salt 1 kg 2 short",
    "number": "RR-2026-000012",
    "decision": "These were bought more than 30 days ago.",
    "shipment": "ORD-2026-000123/1",
    "vehicle": " by vehicle MH12AB1234",
    "delivery_code": " Delivery code: 4821.",
    "transporter": "Shree Transport",
    "lr_number": "LR-5521",
    "product": "Tata Salt 1 kg",
    "quantity": "5",
    "price_increased": " The price has gone up since the order was placed.",
    "alert": "low stock",
    "invoice_number": "INV/26-27/000045",
    "due_date": "15-10-2026",
    "credit_note_number": "CN/26-27/000007",
    "receipt_number": "RCT/26-27/000031",
    "amount": "₹5,000.00",
    "mode": "UPI",
    "cheque_number": "004512",
    "bounce_charge": " A cheque bounce charge of ₹500.00 was added.",
    "refund_number": "RFD/26-27/000002",
    "overdue": "₹18,200.00",
    "bills": "3 bills",
    "oldest_due": "01-09-2026",
    "salesman": "Ravi",
    "count": "4",
    "oldest": "25-09-2026",
    "change_date": "01-11-2026",
    "products": "Tata Salt 1 kg, Aashirvaad Atta 5 kg",
    "title": "Diwali delivery timings",
    "message": "Orders placed after 2 PM will be delivered the next day.",
    "supplier": "Hindustan Traders",
    "po_number": "PO-2026-00012",
    "revision": " (revised 2)",
    "expected_date": "08-10-2026",
}


def variables_for(event_code: str, audience: str) -> tuple[str, ...]:
    """What a text may use. Secure document links go only to shops (ADR-048 item 8)."""
    names = EVENTS[event_code].variables
    return names if audience == Audience.SHOP else tuple(v for v in names if v != "document_link")


@dataclass(frozen=True)
class TextInput:
    event_code: str
    channel: str
    locale: str
    subject: str
    body: str
    audience: str = Audience.SHOP  # the shop's words, the office's or the supplier's letter


def _check(data: TextInput, *, platform: bool) -> None:
    errors: dict[str, list[str]] = {}
    event = EVENTS.get(data.event_code)
    if event is None or (event.system and not platform):
        raise NotFound()
    if data.audience not in event.audiences:
        errors["audience"] = [
            _("This message only goes to the supplier.")
            if event.supplier_facing
            else _("This message only goes to staff.")
            if data.audience == Audience.SHOP
            else _("This message only goes to shops.")
        ]
    allowed_channels = tuple(Channel) if platform else TENANT_CHANNELS
    if data.channel not in allowed_channels:
        errors["channel"] = [
            _("WhatsApp and SMS texts are set by the platform (approved templates).")
        ]
    if not languages.is_known(data.locale):
        errors["locale"] = [
            fill(_("Choose one of: %(languages)s."), {"languages": ", ".join(languages.codes())})
        ]
    needs_subject = data.channel in TENANT_CHANNELS
    if needs_subject and not data.subject.strip():
        errors["subject"] = [_("Enter a title.")]
    if len(data.subject) > MAX_SUBJECT:
        errors["subject"] = [
            fill(_("Use at most %(max_subject)s characters."), {"max_subject": MAX_SUBJECT})
        ]
    limit = {Channel.WHATSAPP: WHATSAPP_MAX_BODY, Channel.SMS: SMS_MAX_BODY}.get(
        Channel(data.channel) if data.channel in Channel.values else Channel.IN_APP, MAX_BODY
    )
    if not data.body.strip():
        errors["body"] = [_("Enter the message.")]
    elif len(data.body) > limit:
        errors["body"] = [fill(_("Use at most %(limit)s characters."), {"limit": limit})]
    used = set(VARIABLE.findall(data.subject)) | set(VARIABLE.findall(data.body))
    allowed = variables_for(data.event_code, data.audience)
    unknown = sorted(used - set(allowed))
    if unknown:
        known = ", ".join(f"{{{{ {v} }}}}" for v in allowed)
        errors.setdefault("body", []).append(
            fill(
                _("Unknown: %(unknown)s. You can use %(known)s."),
                {"unknown": ", ".join(unknown), "known": known},
            )
        )
    if "{%" in data.subject + data.body:
        errors.setdefault("body", []).append(_("Only {{ variable }} placeholders are allowed."))
    if errors:
        raise InvalidFields(errors)


def save_tenant_text(data: TextInput) -> NotificationTemplate:
    """The distributor's own in-app or email text for an event (``notifications.manage``)."""
    _check(data, platform=False)
    key = {
        "event_code": data.event_code,
        "audience": data.audience,
        "channel": data.channel,
        "locale": data.locale,
    }
    row = NotificationTemplate.objects.filter(**key).first()
    before = {"subject": row.subject, "body": row.body} if row else None
    if row is None:
        row = NotificationTemplate(**key)
    row.subject, row.body, row.is_active = data.subject, data.body, True
    row.variables = list(EVENTS[data.event_code].variables)
    row.save()
    audit.record(
        "notifications.template_changed",
        target=row,
        target_repr=f"{data.event_code} {data.audience} {data.channel} {data.locale}",
        changes={
            "subject": [before["subject"] if before else None, row.subject],
            "body": [before["body"] if before else None, row.body],
        },
    )
    return row


def reset_tenant_text(
    event_code: str, channel: str, locale: str, audience: str = Audience.SHOP
) -> bool:
    """Back to the platform's text. False when there was no own text."""
    row = NotificationTemplate.objects.filter(
        event_code=event_code, audience=audience, channel=channel, locale=locale
    ).first()
    if row is None:
        return False
    audit.record(
        "notifications.template_reset",
        target=row,
        target_repr=f"{event_code} {audience} {channel} {locale}",
        changes={"subject": [row.subject, None], "body": [row.body, None]},
    )
    row.delete()
    return True


@dataclass(frozen=True)
class WhatsAppFields:
    template_name: str = ""
    language: str = ""
    category: str = ""


def save_platform_text(data: TextInput, whatsapp: WhatsAppFields | None = None) -> PlatformTemplate:
    """The super admin's default text (any channel). A WhatsApp text keeps the approved
    template's name, language and category; its parameters are the variables in order."""
    _check(data, platform=True)
    wa = whatsapp or WhatsAppFields()
    if (
        data.channel == Channel.WHATSAPP
        and wa.category
        and wa.category not in WhatsAppCategory.values
    ):
        raise InvalidFields({"category": [_("Choose utility, marketing or authentication.")]})
    key = {
        "event_code": data.event_code,
        "audience": data.audience,
        "channel": data.channel,
        "locale": data.locale,
    }
    row = PlatformTemplate.objects.filter(**key).first()
    before = {"subject": row.subject, "body": row.body} if row else None
    if row is None:
        row = PlatformTemplate(**key)
    row.subject, row.body, row.is_active = data.subject, data.body, True
    if data.channel == Channel.WHATSAPP:
        row.whatsapp_template_name = (
            wa.template_name
            or row.whatsapp_template_name
            or (whatsapp_template_name(data.event_code, data.audience))
        )
        row.whatsapp_language = wa.language or row.whatsapp_language or data.locale
        row.whatsapp_category = (
            wa.category or row.whatsapp_category or (EVENTS[data.event_code].category)
        )
        row.variables = list(dict.fromkeys(VARIABLE.findall(data.body)))
    else:
        row.variables = list(EVENTS[data.event_code].variables)
    was = approval.reset_when_text_changes(row, before["body"] if before else None)
    row.save()
    changes = {
        "subject": [before["subject"] if before else None, row.subject],
        "body": [before["body"] if before else None, row.body],
    }
    if was is not None:
        changes["approval_status"] = [was, row.approval_status]
    audit.record(
        "notifications.platform_template_changed",
        target=row,
        target_repr=f"{data.event_code} {data.audience} {data.channel} {data.locale}",
        changes=changes,
        tenant_id=None,
    )
    return row


def preview(data: TextInput, distributor: str) -> dict[str, Any]:
    """What the text looks like with sample values (validated like a save; nothing stored). The
    sample's own words follow the text's language."""
    _check(data, platform=data.channel not in TENANT_CHANNELS)
    with translation.override(data.locale):
        values = {**SAMPLE, **{k: str(v) for k, v in _sample_phrases().items()}}
    values["distributor"] = distributor
    return {"subject": substitute(data.subject, values), "body": substitute(data.body, values)}


def _sample_phrases() -> dict[str, Any]:
    """The sample values that are words, in the active language."""
    return {
        "hold_reason": _("Over the credit limit"),
        "reason": _("Out of stock"),
        "vehicle": fill(_(" by vehicle %(number)s"), {"number": "MH12AB1234"}),
        "delivery_code": fill(_(" Delivery code: %(code)s."), {"code": "4821"}),
        "price_increased": _(" The price has gone up since the order was placed."),
        "alert": _("low stock"),
        "bounce_charge": fill(
            _(" A cheque bounce charge of %(amount)s was added."), {"amount": "₹500.00"}
        ),
        "bills": fill(ngettext("%(count)s bill", "%(count)s bills", 3), {"count": 3}),
        "items": fill(
            _("%(product)s %(quantity)s short"), {"product": "Tata Salt 1 kg", "quantity": 2}
        ),
    }


def texts_for(event_code: str, locale: str = "en") -> list[dict[str, Any]]:
    """Each audience's and channel's text in force for an event (the tenant's, else the
    platform's), for the templates screen: the shop's words first, then the office's. Each says
    which language it is written in (English when ``locale`` has none) and in which languages the
    distributor has its own text, so the editor can warn when only some were changed
    (ADR-060, owner)."""
    if event_code not in EVENTS:
        raise NotFound()
    edited: dict[tuple[str, str], list[str]] = {}
    for audience, channel, loc in NotificationTemplate.objects.filter(
        event_code=event_code, is_active=True
    ).values_list("audience", "channel", "locale"):
        edited.setdefault((audience, channel), []).append(loc)
    order = list(languages.codes())
    found = []
    for audience in EVENTS[event_code].audiences:
        for channel in Channel.values:
            resolved = template_for(event_code, channel, locale, audience)
            if resolved is None:
                continue
            found.append(
                {
                    "audience": audience,
                    "channel": channel,
                    "subject": resolved.subject,
                    "body": resolved.body,
                    "source": resolved.source,
                    "locale": resolved.locale,
                    "edited_locales": sorted(
                        edited.get((audience, channel), []),
                        key=lambda code: order.index(code) if code in order else len(order),
                    ),
                    "editable": channel in TENANT_CHANNELS,
                    "variables": list(variables_for(event_code, audience)),
                }
            )
    return found
