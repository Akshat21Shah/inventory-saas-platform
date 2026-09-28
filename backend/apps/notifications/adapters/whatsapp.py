"""WhatsApp adapter (ADR-048 items 1 and 2).

Messages outside a conversation must use templates the provider has approved, so a message is a
template name, a language and its parameters in order; the rendered text is kept for the log.

Who sends: the distributor's own number when it has connected one (an active
``WhatsAppSender``), else the platform's number from the environment. Every template names the
distributor first, because one platform number sends for every distributor.

TODO(verify): no provider is chosen yet (Meta Cloud API directly or a BSP). Before production:
the provider's send API, template approval and categories, opt-in rules, delivery/read webhooks
(signature checked), whether one number may send for several businesses, and handling "STOP"
replies (PROGRESS pre-production item 8). Until then only the mock exists, refused outside dev
and test (ALLOW_MOCK_INTEGRATIONS).
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.notifications.adapters.base import SendResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WhatsAppMessage:
    to: str
    template: str
    language: str
    parameters: tuple[str, ...]
    category: str
    text: str  # the rendered body, for the log and the mock


@dataclass(frozen=True)
class SenderIdentity:
    provider: str
    phone_number: str
    display_name: str
    credentials: dict[str, Any] = field(default_factory=dict)
    own_number: bool = False  # the distributor's, not the platform's


class WhatsAppClient(Protocol):
    def send_template(self, message: WhatsAppMessage, sender: SenderIdentity) -> SendResult: ...


@dataclass(frozen=True)
class SentWhatsApp:
    message: WhatsAppMessage
    sender: SenderIdentity


class MockWhatsAppClient:
    """Records messages in memory (tests read ``outbox``) and logs a masked line (dev)."""

    outbox: ClassVar[list[SentWhatsApp]] = []

    def send_template(self, message: WhatsAppMessage, sender: SenderIdentity) -> SendResult:
        self.outbox.append(SentWhatsApp(message, sender))
        logger.info(
            "mock WhatsApp sent",
            extra={"phone_tail": message.to[-4:], "template": message.template},
        )
        return SendResult("whatsapp-mock", f"mock-{uuid4().hex[:12]}")


def platform_sender() -> SenderIdentity:
    return SenderIdentity(
        settings.WHATSAPP_PROVIDER,
        settings.WHATSAPP_PLATFORM_NUMBER,
        settings.WHATSAPP_PLATFORM_NAME,
    )


def tenant_sender() -> SenderIdentity:
    """The active tenant's own number if connected, else the platform's."""
    from apps.notifications.models import WhatsAppSender

    own = WhatsAppSender.objects.filter(is_active=True).first()
    if own is None:
        return platform_sender()
    credentials = json.loads(own.credentials) if own.credentials else {}
    return SenderIdentity(own.provider, own.phone_number, own.display_name, credentials, True)


def get_whatsapp_client(provider: str) -> WhatsAppClient:
    if provider == "mock":
        if not settings.ALLOW_MOCK_INTEGRATIONS:
            raise ImproperlyConfigured("WhatsApp provider 'mock' is only allowed in dev and test")
        return MockWhatsAppClient()
    raise ImproperlyConfigured(f"Unknown WhatsApp provider {provider!r}")  # TODO(verify)
