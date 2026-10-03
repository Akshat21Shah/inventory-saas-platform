"""Deployment checks: no mock or local-only notification channels in a deployed environment."""

from typing import Any

from django.conf import settings
from django.core.checks import CheckMessage, Error, Tags, register

LOCAL_EMAIL_BACKENDS = ("locmem", "console", "filebased", "dummy")


@register(Tags.security, deploy=True)
def notification_channels_check(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    errors: list[CheckMessage] = []
    if settings.WHATSAPP_PROVIDER == "mock" and not settings.ALLOW_MOCK_INTEGRATIONS:
        errors.append(
            Error("WHATSAPP_PROVIDER is 'mock' in a deployed environment.", id="notifications.E001")
        )
    if settings.PUSH_PROVIDER == "mock" and not settings.ALLOW_MOCK_INTEGRATIONS:
        errors.append(
            Error("PUSH_PROVIDER is 'mock' in a deployed environment.", id="notifications.E003")
        )
    if settings.PUSH_PROVIDER == "fcm" and not settings.FCM_SERVICE_ACCOUNT_JSON:
        errors.append(
            Error(
                "PUSH_PROVIDER is 'fcm' without FCM_SERVICE_ACCOUNT_JSON.", id="notifications.E004"
            )
        )
    if settings.EMAIL_PROVIDER == "django" and any(
        name in settings.EMAIL_BACKEND for name in LOCAL_EMAIL_BACKENDS
    ):
        errors.append(
            Error(
                "Email would not leave the server: EMAIL_PROVIDER 'django' with a local backend.",
                id="notifications.E002",
            )
        )
    return errors
