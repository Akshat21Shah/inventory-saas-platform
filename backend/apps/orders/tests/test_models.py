"""Database guarantees of the order tables (PLAN §2.8, ADR-006/044)."""

from decimal import Decimal as D

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.tests.factories import make_staff_in
from apps.inventory.tests.helpers import make_product
from apps.ledger.models import RetailerAccount
from apps.orders.models import Cart, Order, OrderLine, OrderStatusHistory
from apps.retailers.services import create_retailer
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop(tenant_a):
    with tenant_context(tenant_a.pk):
        return create_retailer(shop_name="Corner", phone="9876500031", send_welcome=False)


def _order(tenant, shop, user, **extra):
    with tenant_context(tenant.pk):
        return Order.objects.create(
            number=extra.pop("number", "ORD-2026-000001"),
            retailer=shop,
            placed_by=user,
            placed_via="STAFF",
            status="PLACED",
            place_of_supply_id="27",
            supply_type="INTRA",
            placed_at=timezone.now(),
            **extra,
        )


def _line(order, product, **qty):
    fields = {
        "order": order,
        "line_no": 1,
        "product": product,
        "product_code": product.code,
        "product_name": product.name,
        "hsn_code": "1905",
        "unit_code": "PCS",
        "base_price": D("10"),
        "unit_price": D("10"),
        "price_source": "BASE",
        "gst_rate": D("5"),
        **qty,
    }
    return OrderLine.objects.create(**fields)


def test_every_shop_gets_an_account(tenant_a, shop):
    with tenant_context(tenant_a.pk):
        assert RetailerAccount.objects.get(retailer=shop).balance == 0


def test_quantity_buckets_always_add_up(tenant_a, shop):
    user = make_staff_in(tenant_a, "OWNER")
    product = make_product(tenant_a)
    order = _order(tenant_a, shop, user)
    with tenant_context(tenant_a.pk):
        _line(order, product, qty_ordered=D("5"), qty_reserved=D("3"), qty_backordered=D("2"))
        for bad in (
            {"line_no": 2, "qty_ordered": D("5"), "qty_reserved": D("3")},  # 2 missing
            {
                "line_no": 3,
                "qty_ordered": D("1"),
                "qty_reserved": D("-1"),
                "qty_backordered": D("2"),
            },
            {"line_no": 4, "qty_ordered": D("0")},
            {
                "line_no": 5,
                "qty_ordered": D("2"),
                "qty_allocated": D("2"),
                "qty_dispatched": D("3"),
            },
        ):
            with pytest.raises(IntegrityError), transaction.atomic():
                _line(order, product, **bad)


def test_history_is_append_only(tenant_a, shop):
    user = make_staff_in(tenant_a, "OWNER")
    order = _order(tenant_a, shop, user)
    with tenant_context(tenant_a.pk):
        row = OrderStatusHistory.objects.create(
            order=order, to_status="PLACED", event="PLACE", actor_type="STAFF"
        )
        row.note = "edited"
        with pytest.raises(IntegrityError, match="append-only"), transaction.atomic():
            row.save()


def test_one_cart_per_shop_and_user(tenant_a, shop):
    staff = make_staff_in(tenant_a, "SALES")
    owner = make_staff_in(tenant_a, "OWNER")
    with tenant_context(tenant_a.pk):
        Cart.objects.create(retailer=shop, user=staff)
        Cart.objects.create(retailer=shop, user=owner)  # another staff member: own cart
        with pytest.raises(IntegrityError), transaction.atomic():
            Cart.objects.create(retailer=shop, user=staff)


def test_order_numbers_are_unique_per_tenant(tenant_a, tenant_b, shop):
    user = make_staff_in(tenant_a, "OWNER")
    _order(tenant_a, shop, user)
    with pytest.raises(IntegrityError), transaction.atomic():
        _order(tenant_a, shop, user)
