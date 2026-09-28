"""Platform default templates from the catalogue (created once; the super admin's edits are
kept)."""

from typing import Any

from apps.notifications.catalog import DEFAULT_TEXTS, EVENTS, whatsapp_template_name


def _fields(code: str, channel: str) -> dict[str, Any]:
    text = DEFAULT_TEXTS[code][channel]
    fields: dict[str, Any] = {"subject": text.subject, "body": text.body, "is_active": True}
    if channel == "WHATSAPP":
        fields.update(
            whatsapp_template_name=whatsapp_template_name(code),
            whatsapp_language="en",
            whatsapp_category=EVENTS[code].category,
            variables=list(text.variables),
        )
    return fields


def refresh_platform_templates(template_model: Any, codes: list[str]) -> None:
    """Replace the English platform texts of ``codes`` with the catalogue's (a wording change
    shipped with the code, before any super admin could edit them)."""
    for code in codes:
        for channel in DEFAULT_TEXTS[code]:
            template_model.objects.update_or_create(
                event_code=code, channel=channel, locale="en", defaults=_fields(code, channel)
            )


def sync_platform_templates(template_model: Any) -> int:
    """Create any missing platform template (English). Works with a historical model in
    migrations. Returns how many were created."""
    created = 0
    for code, texts in DEFAULT_TEXTS.items():
        for channel in texts:
            _, made = template_model.objects.get_or_create(
                event_code=code, channel=channel, locale="en", defaults=_fields(code, channel)
            )
            created += int(made)
    return created
