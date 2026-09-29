"""Dev only: a copy of every message the mock WhatsApp and SMS providers "send", as an email to
the local mail catcher (Mailpit), so what a shop would receive can be read in one place. Nothing
leaves the machine. Off unless ``MOCK_MESSAGES_TO_MAILPIT`` (dev settings) and mocks are allowed;
never raises (a copy must not fail a delivery)."""

import logging

from django.conf import settings
from django.core.mail import EmailMessage

logger = logging.getLogger(__name__)


def copy_to_mailpit(channel: str, to: str, text: str, details: dict[str, str]) -> None:
    if not (settings.MOCK_MESSAGES_TO_MAILPIT and settings.ALLOW_MOCK_INTEGRATIONS):
        return
    digits = "".join(ch for ch in to if ch.isdigit()) or "unknown"
    lines = [text, "", "—", f"Mock {channel} message (dev only; nothing was sent).", f"To: {to}"]
    lines += [f"{key}: {value}" for key, value in details.items() if value]
    try:
        EmailMessage(
            subject=f"[{channel} mock] to {to}: {text[:60]}",
            body="\n".join(lines),
            from_email=f"Mock {channel} <mock-{channel.lower()}@localhost>",
            to=[f"{digits}@{channel.lower()}.mock"],
        ).send(fail_silently=False)
    except Exception:
        logger.warning("could not copy a mock %s message to Mailpit", channel, exc_info=True)
