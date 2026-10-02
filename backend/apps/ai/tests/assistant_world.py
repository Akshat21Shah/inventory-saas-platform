"""A small distributor for the assistant's tests and evaluation set: bills today for two shops
(one a salesperson's), a shop that last ordered 45 days ago, one that never ordered, a payment,
a product below its reorder level, and the ``ai`` module on."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D
from typing import Any

from django.core.cache import cache
from django.utils import timezone

from apps.accounts.tests.factories import make_staff_in
from apps.ai.tests.test_semantic_search import switch
from apps.billing.tests.helpers import ship_invoice
from apps.catalog.models import Category, Product
from apps.insights import services as insights
from apps.inventory.tests.helpers import make_product
from apps.orders.models import Order
from apps.orders.tests.helpers import add_stock, make_shop, place
from apps.payments import services as payments
from apps.payments.services import PaymentInput
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.tenancy import tenant_context


def build(tenant: Any, other: Any) -> dict[str, Any]:
    cache.clear()
    switch(tenant)
    owner = make_staff_in(tenant, "OWNER")
    sales = make_staff_in(tenant, "SALES")
    warehouse = make_staff_in(tenant, "WAREHOUSE")
    with tenant_context(tenant.pk):
        biscuits = Category.objects.create(name="Biscuits", slug="biscuits")
        drinks = Category.objects.create(name="Drinks", slug="drinks")
    glucose = make_product(
        tenant,
        "GLU",
        name="Glucose Biscuits 100g",
        base_price=D("100"),
        cost_price=D("60"),
        category=biscuits,
    )
    cola = make_product(
        tenant, "COLA", name="Cola 500ml", base_price=D("40"), cost_price=D("25"), category=drinks
    )
    salt = make_product(tenant, "SALT", name="Rock Salt 1kg", base_price=D("20"))
    add_stock(tenant, glucose, "50")
    add_stock(tenant, cola, "50")
    add_stock(tenant, salt, "3")
    with tenant_context(tenant.pk):
        Product.objects.filter(pk=salt.pk).update(reorder_level=D("10"))
    anand = make_shop(tenant, "9876500171", shop_name="Anand Stores")
    balaji = make_shop(tenant, "9876500172", shop_name="Balaji Mart")
    durga = make_shop(tenant, "9876500173", shop_name="Durga Traders")
    make_shop(tenant, "9876500174", shop_name="Chamunda Kirana")  # never ordered
    with tenant_context(tenant.pk):
        Retailer.objects.filter(pk=anand.pk).update(salesperson=sales)
    ship_invoice(tenant, anand, owner, (glucose, "3"), (cola, "2"))  # ₹380 before tax
    ship_invoice(tenant, balaji, owner, (cola, "1"))
    old = place(tenant, durga, (cola, "1"))
    with tenant_context(tenant.pk):
        Order.objects.filter(pk=old.pk).update(placed_at=timezone.now() - timedelta(days=45))
        payments.record_payment(
            PaymentInput(balaji.pk, D("30"), "UPI", today_ist(), reference_no="UTR998877"),
            by=owner,
        )
        insights.refresh_activity()
    make_shop(other, "9876500175", shop_name="Elsewhere Stores")
    return {
        "t": tenant,
        "b": other,
        "owner": owner,
        "sales": sales,
        "warehouse": warehouse,
        "glucose": glucose,
        "salt": salt,
        "anand": anand,
    }
