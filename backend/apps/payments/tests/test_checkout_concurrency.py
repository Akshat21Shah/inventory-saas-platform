"""Two "Pay" taps at the same moment (ADR-049 item 10): real threads with their own connections
and transactions, released together. There is one checkout and one gateway order, and both taps
get it."""

from decimal import Decimal as D
from uuid import uuid4

import pytest
from django.core.cache import cache

from apps.accounts.tests.factories import make_staff_in
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import add_stock, make_shop, shop_client
from apps.orders.tests.test_concurrency import parallel
from apps.payments.models import PaymentIntent
from apps.payments.tests.test_online import connect
from common.tenancy import tenant_context

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.concurrency]


@pytest.mark.parametrize("purpose", ["INVOICE", "OUTSTANDING"])
def test_two_taps_at_once_make_one_checkout(make_tenant, purpose):
    tenant = make_tenant()
    connect(tenant)
    owner = make_staff_in(tenant, "OWNER")
    product = make_product(tenant, base_price=D("100"))
    add_stock(tenant, product, "10")
    shop = make_shop(tenant)
    bill = ship_invoice(tenant, shop, owner, (product, "2"))
    clients = [shop_client(tenant, shop) for _ in range(2)]
    body = {"purpose": purpose}
    if purpose == "INVOICE":
        body["invoice_id"] = str(bill.pk)
    orders_before = len([k for k in cache._cache if "mockpay:order" in str(k)])  # type: ignore[attr-defined]

    def tap(index: int) -> tuple[int, str, str]:
        answer = clients[index].post(
            "/api/v1/shop/payments/checkout/",
            body,
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"k{uuid4().hex}",  # two taps: two keys
        )
        data = answer.json()
        return answer.status_code, data["id"], data["checkout"]["order_id"]

    results, errors = parallel(2, tap)
    assert errors == []
    assert {status for status, _, _ in results} == {200}
    assert len({intent for _, intent, _ in results}) == 1
    assert len({order for _, _, order in results}) == 1
    with tenant_context(tenant.pk):
        assert PaymentIntent.objects.count() == 1
    orders_after = len([k for k in cache._cache if "mockpay:order" in str(k)])  # type: ignore[attr-defined]
    assert orders_after - orders_before == 1  # one gateway order
