from decimal import Decimal as D
from typing import Any

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.compliance.adapters.mock import MockGspClient
from apps.inventory.tests.helpers import make_product
from apps.notifications import quiet
from apps.notifications.adapters.whatsapp import MockWhatsAppClient
from apps.orders.tests.helpers import add_stock, client_for, make_shop
from apps.platform import selectors
from apps.platform.models import FeatureFlag, TenantFeature
from apps.platform.tests.factories import make_gstin
from apps.retailers.models import Retailer
from apps.retailers.services import AddressInput, create_retailer
from common.tenancy import tenant_context


@pytest.fixture(autouse=True)
def _fresh_mock_portal() -> Any:
    MockGspClient.reset()
    yield
    MockGspClient.reset()


def switch_on(tenant: Any, *codes: str) -> None:
    with tenant_context(tenant.pk):
        for code in codes:
            TenantFeature.objects.update_or_create(
                flag=FeatureFlag.objects.get(code=code), defaults={"enabled": True}
            )
    selectors.invalidate_tenant_features(tenant.pk)


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quiet, "current_hold", lambda now: None)
    MockWhatsAppClient.outbox.clear()


@pytest.fixture
def world(tenant_a: Any, tenant_b: Any, django_capture_on_commit_callbacks: Any) -> dict[str, Any]:
    """E-invoicing on with working credentials; a B2B shop in Karnataka and a local B2C shop."""
    from apps.compliance.tests.helpers import credentials

    switch_on(tenant_a, "einvoice", "whatsapp")
    credentials(tenant_a)
    owner = make_staff_in(tenant_a, "OWNER")
    product = make_product(tenant_a, "LAP-1", hsn_code="8471", base_price=D("30000"))
    add_stock(tenant_a, product, "100")
    with tenant_context(tenant_a.pk):
        b2b = create_retailer(
            shop_name="Kaveri Traders",
            phone="9876500081",
            email="kaveri@example.com",
            gstin=make_gstin(8101, "29"),
            billing=AddressInput("4 MG Road", "Bengaluru", "560001", "29"),
            send_welcome=False,
        )
        Retailer.objects.filter(pk=b2b.pk).update(whatsapp_opt_in=True)
    b2c = make_shop(tenant_a, "9876500082", shop_name="Ganesh Kirana")
    return {
        "t": tenant_a,
        "tb": tenant_b,
        "owner": owner,
        "product": product,
        "b2b": b2b,
        "b2c": b2c,
        "staff": client_for(tenant_a, owner),
        "sales": client_for(tenant_a, make_staff_in(tenant_a, "SALES")),
        "other": client_for(tenant_b, make_staff_in(tenant_b, "OWNER")),
        "run": lambda: django_capture_on_commit_callbacks(execute=True),
    }
