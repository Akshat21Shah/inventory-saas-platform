"""SMS adapter for one-time sign-in codes (CLAUDE.md §4: every integration behind an adapter).

TODO(verify): a real provider (e.g. an Indian DLT-registered SMS gateway) must be implemented and
verified against its official API docs, including DLT sender ID and template registration. Until
then only the mock exists, and it is refused outside dev/test (ALLOW_MOCK_INTEGRATIONS).
"""

import logging
from dataclasses import dataclass
from typing import ClassVar, Protocol

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class SmsSender(Protocol):
    def send_otp(self, phone: str, code: str, *, sender_name: str) -> None: ...


@dataclass(frozen=True)
class SentSms:
    phone: str
    code: str
    sender_name: str


class MockSmsSender:
    """Records messages in memory (tests read ``outbox``) and logs a masked line (dev)."""

    outbox: ClassVar[list[SentSms]] = []

    def send_otp(self, phone: str, code: str, *, sender_name: str) -> None:
        self.outbox.append(SentSms(phone=phone, code=code, sender_name=sender_name))
        logger.info("mock SMS sent", extra={"phone_tail": phone[-4:], "sender": sender_name})


def get_sms_sender() -> SmsSender:
    provider: str = settings.SMS_PROVIDER
    if provider == "mock":
        if not settings.ALLOW_MOCK_INTEGRATIONS:
            raise ImproperlyConfigured("SMS_PROVIDER=mock is only allowed in dev and test")
        return MockSmsSender()
    raise ImproperlyConfigured(f"Unknown SMS_PROVIDER {provider!r}")
