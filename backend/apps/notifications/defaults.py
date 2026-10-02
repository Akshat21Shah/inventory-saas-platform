"""Platform default templates from the catalogue (created once; the super admin's edits are
kept). One per event, audience (the shop's words or the office's), channel and language: English
from the catalogue, other languages from ``catalog_texts/<code>.json`` (ADR-060).

These run inside data migrations with historical models. Migrations written before templates had
an audience (0002, 0004, 0005) call them with a model that has no ``audience`` field: they do
nothing then, and 0006 seeds every text once the field exists."""

from typing import Any

from apps.notifications.catalog import (
    DEFAULT_TEXTS,
    EVENTS,
    TEXTS_DIR,
    texts_in,
    whatsapp_template_name,
)


def _has_audience(template_model: Any) -> bool:
    return any(field.name == "audience" for field in template_model._meta.get_fields())


def _audiences(template_model: Any) -> set[str]:
    """The audiences the (historical) model knows: the supplier's texts wait for 0014."""
    return {value for value, _ in template_model._meta.get_field("audience").choices or ()}


def languages() -> list[str]:
    """English, then every language with a catalogue file."""
    return ["en", *sorted(path.stem for path in TEXTS_DIR.glob("*.json"))]


def _fields(code: str, audience: str, channel: str, locale: str = "en") -> dict[str, Any]:
    text = texts_in(locale)[code][audience][channel]
    fields: dict[str, Any] = {"subject": text.subject, "body": text.body, "is_active": True}
    if channel == "WHATSAPP":
        fields.update(
            # One template name; each language is its own translation of it with the provider.
            whatsapp_template_name=whatsapp_template_name(code, audience),
            whatsapp_language=locale,  # TODO(verify): the provider's codes for Hindi and Marathi
            whatsapp_category=EVENTS[code].category,
            variables=list(text.variables),
        )
    return fields


def refresh_platform_templates(template_model: Any, codes: list[str]) -> None:
    """Replace the English platform texts of ``codes`` with the catalogue's (a wording change
    shipped with the code, before any super admin could edit them)."""
    if not _has_audience(template_model):
        return
    known = _audiences(template_model)
    for code in codes:
        for audience, texts in DEFAULT_TEXTS[code].items():
            if audience not in known:
                continue
            for channel in texts:
                template_model.objects.update_or_create(
                    event_code=code,
                    audience=audience,
                    channel=channel,
                    locale="en",
                    defaults=_fields(code, audience, channel),
                )


def sync_platform_templates(template_model: Any) -> int:
    """Create any missing platform template, in every language. Returns how many were created."""
    if not _has_audience(template_model):
        return 0
    created = 0
    known = _audiences(template_model)
    for locale in languages():
        for code, audiences in texts_in(locale).items():
            if code not in EVENTS:
                continue
            for audience, texts in audiences.items():
                if audience not in known:
                    continue
                for channel in texts:
                    _, made = template_model.objects.get_or_create(
                        event_code=code,
                        audience=audience,
                        channel=channel,
                        locale=locale,
                        defaults=_fields(code, audience, channel, locale),
                    )
                    created += int(made)
    return created


TEXT_CHANGED = "The text changed after it was submitted; submit it again."


def refresh_translated_templates(
    template_model: Any, changed: list[tuple[str, str, str, str, str, str]]
) -> int:
    """Give the platform's copies of these translated texts the catalogue's new words, where they
    still hold the old ones (the super admin's own edits are kept). A WhatsApp text whose words
    change goes back to "not submitted". ``changed``: event, audience, channel, language, the old
    subject and body (texts_import, ADR-060 item 11). Returns how many changed."""
    from django.utils import timezone

    refreshed = 0
    for code, audience, channel, locale, old_subject, old_body in changed:
        row = template_model.objects.filter(
            event_code=code, audience=audience, channel=channel, locale=locale
        ).first()
        text = texts_in(locale).get(code, {}).get(audience, {}).get(channel)
        if row is None or text is None or (row.subject, row.body) != (old_subject, old_body):
            continue
        body_changed = row.body != text.body
        row.subject, row.body = text.subject, text.body
        if channel == "WHATSAPP":
            row.variables = list(text.variables)
            if body_changed and row.approval_status != "NOT_SUBMITTED":
                row.approval_status, row.approval_note = "NOT_SUBMITTED", TEXT_CHANGED
                row.approval_changed_at = timezone.now()
        row.save()
        refreshed += 1
    return refreshed
