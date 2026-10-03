"""What an app notification says (ADR-061 item 7; owner, §10.2q answers 2 and 3).

A push shows on the phone's lock screen, so it is the in-app message in the recipient's
language, with two rules:

- **Never a code.** Sign-in codes are not notifications at all; the delivery code (proof of
  delivery) is left out of the words and shows on the order screen after a tap.
- **Amounts only when the shop already gets them by SMS or WhatsApp.** When the same message is
  actually going to that shop by SMS or WhatsApp too, the push carries the in-app words. Otherwise
  a title with an amount gives way to an amount-free title, and a body with an amount to "Open the
  app to see the details".

Every amount in a message is written with the rupee sign by the shared formatter
(``common.numbers``), so a text "has an amount" when it carries ₹, whoever wrote the text (the
platform or a distributor who edited it).
"""

from typing import Any

from django.utils import translation
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy

from apps.notifications.models import Audience, Channel
from apps.notifications.render import render
from common.numbers import fill

# Variables whose value is a code: never in a push.
CODE_VARIABLES = frozenset({"delivery_code"})
RUPEE = "₹"

# Titles for the events whose in-app title carries an amount.
AMOUNT_FREE_TITLES: dict[str, Promise] = {
    "invoice.issued": gettext_lazy("New bill %(invoice_number)s"),
    "credit_note.issued": gettext_lazy("Credit note %(credit_note_number)s"),
    "payment.received": gettext_lazy("Payment received"),
    "refund.recorded": gettext_lazy("Refund received"),
    "payment.reminder": gettext_lazy("Payment reminder"),
}
DETAILS = gettext_lazy("Open the app to see the details.")
FALLBACK_TITLE = gettext_lazy("New message from %(distributor)s")


def has_amount(text: str) -> bool:
    return RUPEE in text


def lock_screen_text(
    code: str, values: dict[str, Any], locale: str, *, amounts_allowed: bool
) -> dict[str, Any] | None:
    """The push's title and body, or None when the event has no in-app words for shops."""
    safe = {**values, **dict.fromkeys(CODE_VARIABLES, "")}
    text = render(code, Channel.IN_APP, safe, locale, Audience.SHOP)
    if text is None:
        return None
    title, body = text["title"], text["body"]
    if amounts_allowed:
        return {"title": title, "body": body, "whatsapp": None}
    with translation.override(locale):
        if has_amount(title):
            template = AMOUNT_FREE_TITLES.get(code)
            title = fill(template, values) if template is not None else ""
            if not title or has_amount(title):  # a distributor's own wording, or unknown
                distributor = values.get("distributor", "")
                title = fill(FALLBACK_TITLE, {"distributor": distributor})
        if has_amount(body):
            body = str(DETAILS)
    return {"title": title, "body": body, "whatsapp": None}
