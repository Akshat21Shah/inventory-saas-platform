"""Platform default templates from the catalogue (created once; the super admin's edits are
kept)."""

from typing import Any

from apps.notifications.catalog import DEFAULT_TEXTS, EVENTS, whatsapp_template_name


def sync_platform_templates(template_model: Any) -> int:
    """Create any missing platform template (English). Works with a historical model in
    migrations. Returns how many were created."""
    created = 0
    for code, texts in DEFAULT_TEXTS.items():
        event = EVENTS[code]
        for channel, text in texts.items():
            fields: dict[str, Any] = {"subject": text.subject, "body": text.body, "is_active": True}
            if channel == "WHATSAPP":
                fields.update(
                    whatsapp_template_name=whatsapp_template_name(code),
                    whatsapp_language="en",
                    whatsapp_category=event.category,
                    variables=list(text.variables),
                )
            _, made = template_model.objects.get_or_create(
                event_code=code, channel=channel, locale="en", defaults=fields
            )
            created += int(made)
    return created
