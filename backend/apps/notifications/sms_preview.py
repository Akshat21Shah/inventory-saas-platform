"""How the welcome SMS reads with the distributor's short name for SMS (owner, ADR-060): each of
its languages, the length the network counts and how many parts it takes (each is paid for). The
link is the shop's real sign-in link and is never shortened; a text over one part goes as more."""

from typing import Any

from django.utils.translation import gettext as _

from apps.notifications import sms_length
from apps.notifications.context import current_tenant, distributor_name
from apps.notifications.models import Audience, Channel
from apps.notifications.render import render
from apps.notifications.texts import SAMPLE
from common import languages
from common.errors import InvalidFields
from common.hosts import web_url

EVENT = "retailer.welcome"


def welcome_previews(name: str) -> list[dict[str, Any]]:
    """The welcome SMS in every language the distributor's shops may use, with ``name`` (blank:
    the business name) in place of the distributor's name."""
    if any(ch in name for ch in "\r\n\t") or len(name) > 30:
        raise InvalidFields({"name": [_("Write the short name on one line, up to 30 letters.")]})
    tenant = current_tenant()
    values = {
        "distributor": name.strip() or distributor_name(tenant),
        "shop": SAMPLE["shop"],  # the English text greets the shop by name
        "link": web_url("/shop/login", tenant_slug=tenant.slug),
    }
    found = []
    for code in languages.available_for_tenant(tenant.pk):
        text = render(EVENT, Channel.SMS, values, code, Audience.SHOP)
        language = languages.get(code)
        if text is None or language is None:
            continue
        body = text["body"]
        found.append(
            {
                "language": code,
                "native": language.native,
                "text": body,
                "length": sms_length.length(body),
                "single": 70 if sms_length.is_unicode(body) else 160,
                "parts": sms_length.parts(body),
            }
        )
    return found
