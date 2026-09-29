"""Platform default templates from the catalogue (created once; the super admin's edits are
kept). One per event, audience (the shop's words or the office's) and channel, in English.

These run inside data migrations with historical models. Migrations written before templates had
an audience (0002, 0004, 0005) call them with a model that has no ``audience`` field: they do
nothing then, and 0006 seeds every text once the field exists."""

from typing import Any

from apps.notifications.catalog import DEFAULT_TEXTS, EVENTS, whatsapp_template_name


def _has_audience(template_model: Any) -> bool:
    return any(field.name == "audience" for field in template_model._meta.get_fields())


def _fields(code: str, audience: str, channel: str) -> dict[str, Any]:
    text = DEFAULT_TEXTS[code][audience][channel]
    fields: dict[str, Any] = {"subject": text.subject, "body": text.body, "is_active": True}
    if channel == "WHATSAPP":
        fields.update(
            whatsapp_template_name=whatsapp_template_name(code, audience),
            whatsapp_language="en",
            whatsapp_category=EVENTS[code].category,
            variables=list(text.variables),
        )
    return fields


def refresh_platform_templates(template_model: Any, codes: list[str]) -> None:
    """Replace the English platform texts of ``codes`` with the catalogue's (a wording change
    shipped with the code, before any super admin could edit them)."""
    if not _has_audience(template_model):
        return
    for code in codes:
        for audience, texts in DEFAULT_TEXTS[code].items():
            for channel in texts:
                template_model.objects.update_or_create(
                    event_code=code,
                    audience=audience,
                    channel=channel,
                    locale="en",
                    defaults=_fields(code, audience, channel),
                )


def sync_platform_templates(template_model: Any) -> int:
    """Create any missing platform template (English). Returns how many were created."""
    if not _has_audience(template_model):
        return 0
    created = 0
    for code, audiences in DEFAULT_TEXTS.items():
        for audience, texts in audiences.items():
            for channel in texts:
                _, made = template_model.objects.get_or_create(
                    event_code=code,
                    audience=audience,
                    channel=channel,
                    locale="en",
                    defaults=_fields(code, audience, channel),
                )
                created += int(made)
    return created
