"""Deployment checks: refuse mock integrations in a deployed environment."""

from typing import Any

from django.conf import settings
from django.core.checks import CheckMessage, Error, Tags, register


@register(Tags.security, deploy=True)
def mock_integrations_check(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    errors: list[CheckMessage] = []
    if settings.SMS_PROVIDER == "mock" and not settings.ALLOW_MOCK_INTEGRATIONS:
        errors.append(
            Error("SMS_PROVIDER is 'mock' in a deployed environment.", id="accounts.E001")
        )
    if settings.OTP_FIXED_CODE:
        errors.append(
            Error("OTP_FIXED_CODE must not be set in a deployed environment.", id="accounts.E002")
        )
    return errors
