"""Stock primitives (PLAN §5.2, ADR-041): one write path, movement rows with balances, the
reserved-stock guard, and the cost method."""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import transaction

from apps.audit.models import AuditLog
from apps.catalog.models import Product
from apps.inventory import services
from apps.inventory.models import StockLevel, StockMovement
from apps.inventory.services import InsufficientStock, Ref, StockReserved
from apps.inventory.tests.helpers import check_invariants, make_product
from apps.platform.services import set_tenant_settings
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
D = Decimal


def _ref(number="GRN-2026-00001"):
    return Ref("INWARD", uuid4(), number)


def _run(tenant, product, action, qty, **kwargs):
    with tenant_context(tenant.pk), transaction.atomic():
        level = services.lock_levels([product.pk], services.default_warehouse())[product.pk]
        return action(level, D(qty), _ref(), by=None, **kwargs)


def _level(tenant, product):
    with tenant_context(tenant.pk):
        return StockLevel.objects.get(product=product)


def test_movement_records_balances_and_value(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant)
    movement = _run(tenant, product, services.receive, "12", unit_cost=D("8.3333"))
    assert (movement.delta_on_hand, movement.delta_reserved) == (12, 0)
    assert (movement.on_hand_after, movement.reserved_after) == (12, 0)
    assert movement.value == D("100.00")
    reserve = _run(tenant, product, services.reserve, "5")
    assert (reserve.on_hand_after, reserve.reserved_after) == (12, 5)
    release = _run(tenant, product, services.release, "2")
    assert (release.delta_reserved, release.reserved_after) == (-2, 3)
    sale = _run(tenant, product, services.consume_reserved, "3")
    assert (sale.delta_on_hand, sale.delta_reserved) == (-3, -3)
    level = _level(tenant, product)
    assert (level.quantity_on_hand, level.quantity_reserved) == (9, 0)
    check_invariants(tenant)


def test_cannot_remove_more_than_on_hand(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant)
    _run(tenant, product, services.add, "2")
    with pytest.raises(InsufficientStock) as exc:
        _run(tenant, product, services.remove, "3")
    assert exc.value.details["available"] == "2.000"
    assert _level(tenant, product).quantity_on_hand == 2
    check_invariants(tenant)


def test_cannot_remove_reserved_stock(make_tenant):
    """PLAN S4: adjust-out below reserved is blocked with STOCK_RESERVED."""
    tenant = make_tenant()
    product = make_product(tenant)
    _run(tenant, product, services.add, "5")
    _run(tenant, product, services.reserve, "4")
    with pytest.raises(StockReserved):
        _run(tenant, product, services.remove, "2", movement_type="DAMAGE")
    _run(tenant, product, services.remove, "1", movement_type="DAMAGE")  # the free unit
    check_invariants(tenant)


def test_cannot_reserve_more_than_available(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant)
    _run(tenant, product, services.add, "3")
    _run(tenant, product, services.reserve, "2")
    with pytest.raises(InsufficientStock):
        _run(tenant, product, services.reserve, "2")
    with pytest.raises(ValueError):
        _run(tenant, product, services.release, "3")


@pytest.mark.parametrize("qty", ["0", "-1"])
def test_quantity_must_be_positive(make_tenant, qty):
    tenant = make_tenant()
    product = make_product(tenant)
    with pytest.raises(ValueError):
        _run(tenant, product, services.add, qty)
    with tenant_context(tenant.pk):
        assert not StockMovement.objects.exists()


def test_remove_only_takes_unreserved_types(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant)
    _run(tenant, product, services.add, "3")
    with pytest.raises(ValueError):
        _run(tenant, product, services.remove, "1", movement_type="SALE")


def test_every_type_has_a_direction():
    from apps.inventory.models import MovementType

    assert set(services.MOVEMENT_KINDS) == set(MovementType.values)


def test_lock_levels_creates_missing_levels(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant)
    with tenant_context(tenant.pk):
        StockLevel.objects.all().delete()
        with transaction.atomic():
            levels = services.lock_levels([product.pk, product.pk], services.default_warehouse())
        assert list(levels) == [product.pk]


# --- Cost method -------------------------------------------------------------------------------


def _receive_with_cost(tenant, product, qty, cost):
    with tenant_context(tenant.pk), transaction.atomic():
        level = services.lock_levels([product.pk], services.default_warehouse())[product.pk]
        before = level.quantity_on_hand
        services.receive(level, D(qty), _ref(), by=None, unit_cost=D(cost))
        return services.apply_cost_method(
            product.pk,
            on_hand_before=before,
            received=D(qty),
            unit_cost=D(cost),
            source="GRN-2026-00007",
        )


def _cost(tenant, product):
    with tenant_context(tenant.pk):
        return Product.objects.get(pk=product.pk).cost_price


def _method(tenant, value):
    with tenant_context(tenant.pk):
        set_tenant_settings({"stock.cost_method": value}, user=None)


def test_weighted_average_is_the_default(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant, cost_price=D("5.00"))
    _run(tenant, product, services.add, "10")
    assert _receive_with_cost(tenant, product, "10", "7") == D("6.00")
    assert _cost(tenant, product) == D("6.00")
    with tenant_context(tenant.pk):
        entry = AuditLog.objects.get(action="catalog.product_price_changed")
    assert entry.changes == {"cost_price": ["5.00", "6.00"]}
    assert entry.metadata == {"updated_by": "GRN-2026-00007", "cost_method": "WEIGHTED_AVERAGE"}


def test_weighted_average_with_no_stock_or_no_cost_takes_the_bill(make_tenant):
    tenant = make_tenant()
    no_stock = make_product(tenant, "A", cost_price=D("5.00"))
    no_cost = make_product(tenant, "B")
    _run(tenant, no_cost, services.add, "10")
    assert _receive_with_cost(tenant, no_stock, "4", "8.3333") == D("8.33")
    assert _receive_with_cost(tenant, no_cost, "4", "8.125") == D("8.13")


def test_last_purchase_cost(make_tenant):
    tenant = make_tenant()
    _method(tenant, "LAST_PURCHASE")
    product = make_product(tenant, cost_price=D("5.00"))
    _run(tenant, product, services.add, "10")
    assert _receive_with_cost(tenant, product, "1", "9.995") == D("10.00")
    assert _cost(tenant, product) == D("10.00")


def test_manual_never_changes_the_cost_price(make_tenant):
    tenant = make_tenant()
    _method(tenant, "MANUAL")
    product = make_product(tenant, cost_price=D("5.00"))
    assert _receive_with_cost(tenant, product, "3", "9") is None
    assert _cost(tenant, product) == D("5.00")
    with tenant_context(tenant.pk):
        assert not AuditLog.objects.filter(action="catalog.product_price_changed").exists()


def test_unchanged_cost_is_not_audited(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant, cost_price=D("5.00"))
    _run(tenant, product, services.add, "10")
    _receive_with_cost(tenant, product, "5", "5")
    with tenant_context(tenant.pk):
        assert not AuditLog.objects.filter(action="catalog.product_price_changed").exists()
