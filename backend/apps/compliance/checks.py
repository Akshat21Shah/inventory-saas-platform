"""Deployment checks: no mock GST provider in a deployed environment."""

from typing import Any

from django.conf import settings
from django.core.checks import CheckMessage, Error, Tags, register


@register(Tags.security, deploy=True)
def gsp_provider_check(app_configs: Any, **kwargs: Any) -> list[CheckMessage]:
    if settings.GSP_PROVIDER == "mock" and not settings.ALLOW_MOCK_INTEGRATIONS:
        return [Error("GSP_PROVIDER is 'mock' in a deployed environment.", id="compliance.E001")]
    return []
