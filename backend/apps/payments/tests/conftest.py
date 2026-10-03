"""What the payment tests share: a distributor taking online payments through the test gateway,
a shop with a ₹210 bill, and API clients (ADR-049 items 9 and 10)."""

from decimal import Decimal as D
from typing import Any

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.notifications import quiet
from apps.orders.tests.helpers import add_stock, client_for, make_shop, shop_client
from apps.payments.gateway.base import GatewayKeys
from apps.payments.models import GatewayConfig
from apps.payments.tests.test_gateway import payments_on
from common.tenancy import tenant_context

KEYS = GatewayKeys("MOCK", "TEST", "mock_key_1", "secret-1", "hook-1")


def connect(tenant: Any, keys: GatewayKeys = KEYS, status: str = "VERIFIED") -> None:
    payments_on(tenant)
    with tenant_context(tenant.pk):
        GatewayConfig.objects.update_or_create(
            defaults={
                "provider": keys.provider,
                "mode": keys.mode,
                "key_id": keys.key_id,
                "key_secret": keys.key_secret,
                "webhook_secret": keys.webhook_secret,
                "status": status,
            }
        )


@pytest.fixture
def daytime(monkeypatch):
    """No quiet hours: notifications go at once (the online payment tests use it)."""
    monkeypatch.setattr(quiet, "current_hold", lambda now: None)


@pytest.fixture
def world(tenant_a, tenant_b, django_capture_on_commit_callbacks):
    connect(tenant_a)
    owner = make_staff_in(tenant_a, "OWNER")
    product = make_product(tenant_a, "P-1", base_price=D("100"))
    add_stock(tenant_a, product, "100")
    shop = make_shop(tenant_a, email="shop@example.com")
    run = django_capture_on_commit_callbacks
    with run(execute=True):
        bill = ship_invoice(tenant_a, shop, owner, (product, "2"))  # ₹210
    return {
        "t": tenant_a,
        "tb": tenant_b,
        "owner": owner,
        "product": product,
        "shop": shop,
        "bill": bill,
        "shop_api": shop_client(tenant_a, shop),
        "staff": client_for(tenant_a, owner),
        "sales": client_for(tenant_a, make_staff_in(tenant_a, "SALES")),
        "run": lambda: run(execute=True),
    }
