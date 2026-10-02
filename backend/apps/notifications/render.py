"""Sandboxed template rendering (ADR-048 item 14): ``{{ variable }}`` is replaced by the event's
value for it, and nothing else is evaluated, so a template edited by a distributor can't run code
or read anything beyond the event's variables."""

import re
from dataclasses import dataclass
from typing import Any

from apps.notifications.catalog import default_text
from apps.notifications.models import Audience, NotificationTemplate, PlatformTemplate

VARIABLE = re.compile(r"{{\s*(\w+)\s*}}")


def substitute(text: str, values: dict[str, Any]) -> str:
    return VARIABLE.sub(lambda m: str(values.get(m.group(1), "")), text)


@dataclass(frozen=True)
class Resolved:
    subject: str
    body: str
    whatsapp_template_name: str = ""
    whatsapp_language: str = ""
    whatsapp_category: str = ""
    variables: tuple[str, ...] = ()
    source: str = "platform"  # tenant, platform, catalogue
    locale: str = "en"  # the language the text is written in


def template_for(
    event_code: str, channel: str, locale: str = "en", audience: str = Audience.SHOP
) -> Resolved | None:
    """The text to send, for the audience (the shop's words or the office's; never the other
    audience's). In the person's language: the distributor's own text, else the super admin's,
    else the standard one; only then the same in English (ADR-060, owner: a language the
    distributor hasn't edited uses the standard translation, not its English edit)."""
    for loc in dict.fromkeys((locale, "en")):
        for model, source in ((NotificationTemplate, "tenant"), (PlatformTemplate, "platform")):
            row = model.objects.filter(
                event_code=event_code,
                audience=audience,
                channel=channel,
                locale=loc,
                is_active=True,
            ).first()
            if row is not None:
                return Resolved(
                    row.subject,
                    row.body,
                    row.whatsapp_template_name,
                    row.whatsapp_language,
                    row.whatsapp_category,
                    tuple(row.variables or ()),
                    source,
                    loc,
                )
        text = default_text(event_code, audience, channel, loc)
        if text is not None:
            return Resolved(
                text.subject, text.body, variables=text.variables, source="catalogue", locale=loc
            )
    return None


def render(
    event_code: str,
    channel: str,
    values: dict[str, Any],
    locale: str = "en",
    audience: str = Audience.SHOP,
) -> dict[str, Any] | None:
    """Title, body and (for WhatsApp) the approved template's name and parameters."""
    resolved = template_for(event_code, channel, locale, audience)
    if resolved is None:
        return None
    title = substitute(resolved.subject, values)
    if not title:  # WhatsApp and SMS have no subject: use the in-app title for lists
        in_app = template_for(event_code, "IN_APP", locale, audience)
        title = substitute(in_app.subject, values) if in_app else event_code
    return {
        "title": title[:200],
        "body": substitute(resolved.body, values),
        "whatsapp": {
            "template": resolved.whatsapp_template_name,
            "language": resolved.whatsapp_language or resolved.locale,
            "category": resolved.whatsapp_category,
            "parameters": [str(values.get(name, "")) for name in resolved.variables],
        }
        if channel == "WHATSAPP"
        else None,
    }
