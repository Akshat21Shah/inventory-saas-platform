"""Database guarantees of the inventory tables (PLAN §2.7, ADR-041): checks, append-only rows,
posted receipts, one open alert, one default warehouse, and the stock level made with a product."""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.tests.factories import make_staff_in
from apps.catalog.models import Unit
from apps.catalog.services import create_product
from apps.inventory.models import (
    AdjustmentReason,
    StockAdjustment,
    StockAdjustmentLine,
    StockAlert,
    StockInward,
    StockInwardLine,
    StockLevel,
    StockMovement,
    Warehouse,
)
from apps.inventory.tests.helpers import make_product
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


def _level(tenant, product):
    return StockLevel.objects.get(product=product)


@pytest.mark.parametrize(
    ("on_hand", "reserved", "backordered"),
    [("-1", "0", "0"), ("1", "-1", "0"), ("1", "0", "-1"), ("1", "2", "0")],
)
def test_stock_level_checks(make_tenant, on_hand, reserved, backordered):
    tenant = make_tenant()
    product = make_product(tenant)
    with tenant_context(tenant.pk):
        level = _level(tenant, product)
        level.quantity_on_hand = Decimal(on_hand)
        level.quantity_reserved = Decimal(reserved)
        level.quantity_backordered = Decimal(backordered)
        with pytest.raises(IntegrityError), transaction.atomic():
            level.save()


def _movement(product, warehouse, **extra):
    fields = {
        "product": product,
        "warehouse": warehouse,
        "movement_type": "INWARD",
        "quantity": Decimal("1"),
        "delta_on_hand": Decimal("1"),
        "delta_reserved": Decimal("0"),
        "on_hand_after": Decimal("1"),
        "reserved_after": Decimal("0"),
        "reference_type": "INWARD",
        "reference_id": uuid4(),
        **extra,
    }
    return StockMovement.objects.create(**fields)


def test_movements_are_append_only(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant)
    with tenant_context(tenant.pk):
        movement = _movement(product, Warehouse.objects.get(is_default=True))
        movement.reason = "edited"
        with pytest.raises(IntegrityError, match="append-only"), transaction.atomic():
            movement.save()
        with pytest.raises(IntegrityError, match="append-only"), transaction.atomic():
            StockMovement.objects.filter(pk=movement.pk).delete()


def test_movement_types_are_not_a_database_list(make_tenant):
    """Manufacturing adds types later without a schema change (ADR-041)."""
    tenant = make_tenant()
    product = make_product(tenant)
    with tenant_context(tenant.pk):
        row = _movement(product, Warehouse.objects.get(is_default=True), movement_type="PRODUCE")
        assert StockMovement.objects.get(pk=row.pk).movement_type == "PRODUCE"


def test_adjustments_are_immutable(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant)
    with tenant_context(tenant.pk):
        adjustment = StockAdjustment.objects.create(
            number="ADJ-2026-00001",
            warehouse=Warehouse.objects.get(is_default=True),
            reason_code=AdjustmentReason.DAMAGE,
            note="Carton fell",
        )
        line = StockAdjustmentLine.objects.create(
            adjustment=adjustment,
            line_no=1,
            product=product,
            mode="REMOVE",
            entered_qty=Decimal("1"),
            quantity_change=Decimal("-1"),
            on_hand_before=Decimal("5"),
        )
        for row in (adjustment, line):
            with pytest.raises(IntegrityError, match="append-only"), transaction.atomic():
                row.save()
        with pytest.raises(IntegrityError), transaction.atomic():
            StockAdjustment.objects.create(
                number="ADJ-2026-00002",
                warehouse=Warehouse.objects.get(is_default=True),
                reason_code=AdjustmentReason.OTHER,
                note="",
            )


def _posted_inward(product, *, cost=None):
    inward = StockInward.objects.create(warehouse=Warehouse.objects.get(is_default=True))
    line = StockInwardLine.objects.create(
        inward=inward,
        line_no=1,
        product=product,
        entered_qty=Decimal("2"),
        quantity=Decimal("2"),
        unit_cost=cost,
        cost_status="SET" if cost is not None else "PENDING",
    )
    inward.status = StockInward.Status.POSTED
    inward.number = "GRN-2026-00001"
    inward.posted_at = timezone.now()
    inward.cost_pending_lines = 0 if cost is not None else 1
    inward.save()
    return inward, line


def test_posted_receipt_cannot_change(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant)
    with tenant_context(tenant.pk):
        inward, line = _posted_inward(product, cost=Decimal("4"))
        inward.supplier_name = "Changed"
        with pytest.raises(IntegrityError, match="cannot be changed"), transaction.atomic():
            inward.save()
        with pytest.raises(IntegrityError, match=r"cannot be"), transaction.atomic():
            StockInward.objects.filter(pk=inward.pk).delete()
        line.quantity = Decimal("3")
        with pytest.raises(IntegrityError, match="cannot be changed"), transaction.atomic():
            line.save()
        with pytest.raises(IntegrityError, match="cannot be changed"), transaction.atomic():
            StockInwardLine.objects.create(
                inward=inward, line_no=2, product=product, entered_qty=1, quantity=1
            )
        line.refresh_from_db()
        line.unit_cost = Decimal("5")  # a set cost is final
        with pytest.raises(IntegrityError, match="cannot be changed"), transaction.atomic():
            line.save()


def test_pending_cost_can_be_completed_once(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant)
    with tenant_context(tenant.pk):
        inward, line = _posted_inward(product)
        line.unit_cost = Decimal("4.5")
        line.line_cost = Decimal("9.00")
        line.cost_status = "SET"
        line.cost_completed_at = timezone.now()
        line.save()
        inward.cost_pending_lines = 0
        inward.total_cost = Decimal("9.00")
        inward.save()
        line.quantity = Decimal("5")
        with pytest.raises(IntegrityError), transaction.atomic():
            line.save()


def test_draft_receipt_is_editable(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant)
    with tenant_context(tenant.pk):
        inward = StockInward.objects.create(warehouse=Warehouse.objects.get(is_default=True))
        line = StockInwardLine.objects.create(
            inward=inward, line_no=1, product=product, entered_qty=1, quantity=1
        )
        line.quantity = Decimal("2")
        line.save()
        inward.delete()
        assert not StockInwardLine.objects.exists()


def test_one_open_alert_per_product_and_type(make_tenant):
    tenant = make_tenant()
    product = make_product(tenant)
    with tenant_context(tenant.pk):
        warehouse = Warehouse.objects.get(is_default=True)

        def alert(**extra):
            return StockAlert.objects.create(
                product=product,
                warehouse=warehouse,
                alert_type="LOW_STOCK",
                opened_at=timezone.now(),
                value_at_open=Decimal("1"),
                **extra,
            )

        first = alert()
        with pytest.raises(IntegrityError), transaction.atomic():
            alert()
        first.status = "RESOLVED"
        first.resolved_at = timezone.now()
        first.save()
        alert()  # a new one may open once the first is resolved
        assert StockAlert.objects.count() == 2


def test_one_default_warehouse(make_tenant):
    tenant = make_tenant()
    with tenant_context(tenant.pk):
        assert Warehouse.objects.filter(is_default=True).count() == 1
        with pytest.raises(IntegrityError), transaction.atomic():
            Warehouse.objects.create(code="SECOND", name="Second", is_default=True)


def test_create_product_makes_its_stock_level(make_tenant):
    tenant = make_tenant()
    owner = make_staff_in(tenant, "OWNER")
    with tenant_context(tenant.pk):
        product, _ = create_product(
            {
                "code": "NEW-1",
                "name": "New",
                "unit_id": Unit.objects.get(code="PCS").pk,
                "hsn_code": "1905",
                "base_price": Decimal("5"),
            },
            gst_rate=Decimal("5"),
            by=owner,
        )
        level = StockLevel.objects.get(product=product)
        assert (level.quantity_on_hand, level.quantity_reserved) == (0, 0)
