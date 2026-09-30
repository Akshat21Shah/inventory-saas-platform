from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.payments.gateway.base import GatewayClient


def get_gateway(provider: str) -> GatewayClient:
    if provider == "MOCK":
        if not settings.ALLOW_MOCK_INTEGRATIONS:
            raise ImproperlyConfigured("The mock payment gateway is only allowed in dev and test")
        from apps.payments.gateway.mock import MockGateway

        return MockGateway()
    if provider == "RAZORPAY":
        from apps.payments.gateway.razorpay import RazorpayGateway

        return RazorpayGateway()
    raise ImproperlyConfigured(f"Unknown payment gateway {provider!r}")
