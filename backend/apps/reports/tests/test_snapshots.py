"""What Phase 8 records for reports (ADR-050 items 4 and 5): the shop's salesperson on each order
when placed, and the product's cost on each invoice line when issued (kept on a re-issue)."""

from decimal import Decimal as D

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.billing.models import InvoiceLine
from apps.billing.tests.helpers import ship_invoice
from apps.catalog.models import Product
from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import add_stock, make_shop, place
from apps.retailers.models import Retailer
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


def test_an_order_keeps_the_salesperson_it_was_placed_with(tenant_a):
    first, second = make_staff_in(tenant_a, "SALES"), make_staff_in(tenant_a, "SALES")
    shop = make_shop(tenant_a)
    product = make_product(tenant_a, base_price=D("100"))
    add_stock(tenant_a, product, "10")
    with tenant_context(tenant_a.pk):
        Retailer.objects.filter(pk=shop.pk).update(salesperson=first)
    before = place(tenant_a, shop, (product, "1"))
    with tenant_context(tenant_a.pk):
        Retailer.objects.filter(pk=shop.pk).update(salesperson=second)
    after = place(tenant_a, shop, (product, "1"))
    assert (before.salesperson_id, after.salesperson_id) == (first.pk, second.pk)
    unassigned = make_shop(tenant_a, "9876500099")
    assert place(tenant_a, unassigned, (product, "1")).salesperson_id is None


def test_an_invoice_line_keeps_the_cost_it_was_issued_with(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    costed = make_product(tenant_a, "P-1", base_price=D("100"), cost_price=D("62.50"))
    uncosted = make_product(tenant_a, "P-2", base_price=D("40"))
    add_stock(tenant_a, costed, "10")
    add_stock(tenant_a, uncosted, "10")
    invoice = ship_invoice(tenant_a, shop, owner, (costed, "2"), (uncosted, "1"))
    with tenant_context(tenant_a.pk):
        Product.objects.filter(pk=costed.pk).update(cost_price=D("70"))  # later: not the sale's
        costs = dict(
            InvoiceLine.objects.filter(invoice=invoice).values_list("product_id", "unit_cost")
        )
    assert costs == {costed.pk: D("62.5000"), uncosted.pk: None}
