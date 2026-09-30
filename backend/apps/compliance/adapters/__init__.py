from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.compliance.adapters.base import GspClient


def get_gsp_client(provider: str) -> GspClient:
    if provider == "mock":
        if not settings.ALLOW_MOCK_INTEGRATIONS:
            raise ImproperlyConfigured("GSP provider 'mock' is only allowed in dev and test")
        from apps.compliance.adapters.mock import MockGspClient

        return MockGspClient()
    raise ImproperlyConfigured(f"Unknown GSP provider {provider!r}")  # TODO(verify): item 18
