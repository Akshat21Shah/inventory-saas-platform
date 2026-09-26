"""Stock adjustments and reorder levels (spec 5.7, ADR-041 items 10-11)."""

from decimal import Decimal

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.catalog.models import Product, Unit
from apps.catalog.services import update_product
from apps.inventory import adjustments, services
from apps.inventory.adjustments import AdjustmentInput, AdjustmentLineInput
from apps.inventory.models import StockAdjustment, StockAlert, StockLevel, StockMovement
from apps.inventory.services import InsufficientStock, StockReserved
from apps.inventory.tests.helpers import check_invariants, make_product
from common.errors import InvalidFields
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def tenant(make_tenant):
    return make_tenant()


@pytest.fixture
def staff(tenant):
    return make_staff_in(tenant, "WAREHOUSE")


def _adjust(tenant, by, *lines, reason="COUNT_CORRECTION", note="Shelf count"):
    with tenant_context(tenant.pk):
        return adjustments.create_adjustment(
            AdjustmentInput(
                reason_code=reason,
                note=note,
                lines=[AdjustmentLineInput(p.pk, mode, D(q)) for p, mode, q in lines],
            ),
            by=by,
        )


def _on_hand(tenant, product):
    with tenant_context(tenant.pk):
        return StockLevel.objects.get(product=product).quantity_on_hand


def test_add_remove_and_counted_lines(tenant, staff):
    a, b, c, d = (make_product(tenant, code) for code in "ABCD")
    _adjust(
        tenant, staff, (a, "ADD", "10"), (b, "ADD", "10"), (c, "ADD", "10"), reason="OPENING_STOCK"
    )
    result = _adjust(
        tenant, staff, (a, "ADD", "2"), (b, "REMOVE", "3"), (c, "COUNTED", "7"), (d, "COUNTED", "0")
    )
    assert result.unchanged == ["D"]  # counted 0, had 0: no line
    assert [_on_hand(tenant, p) for p in (a, b, c)] == [12, 7, 7]
    with tenant_context(tenant.pk):
        adjustment = StockAdjustment.objects.get(pk=result.adjustment.pk)
        lines = {line.product.code: line for line in adjustment.lines.select_related("product")}
        assert set(lines) == {"A", "B", "C"}
        assert (lines["C"].mode, lines["C"].entered_qty, lines["C"].on_hand_before) == (
            "COUNTED",
            D("7"),
            D("10"),
        )
        assert lines["C"].quantity_change == D("-3")
        moves = StockMovement.objects.filter(reference_id=adjustment.pk)
        assert sorted(m.movement_type for m in moves) == [
            "ADJUSTMENT_IN",
            "ADJUSTMENT_OUT",
            "ADJUSTMENT_OUT",
        ]
        assert {m.reason for m in moves} == {"Shelf count"}
        entry = AuditLog.objects.get(action="stock.adjusted", target_repr=adjustment.number)
        assert entry.metadata["unchanged"] == ["D"] and entry.metadata["note"] == "Shelf count"
    year = adjustment.created_at.year
    assert adjustment.number == f"ADJ-{year}-00002"
    check_invariants(tenant)


def test_damage_reason_writes_damage_movements(tenant, staff):
    product = make_product(tenant)
    _adjust(tenant, staff, (product, "ADD", "5"))
    result = _adjust(tenant, staff, (product, "REMOVE", "2"), reason="DAMAGE", note="Wet cartons")
    with tenant_context(tenant.pk):
        move = StockMovement.objects.get(reference_id=result.adjustment.pk)
    assert move.movement_type == "DAMAGE"


def test_reserved_stock_cannot_be_removed(tenant, staff):
    product = make_product(tenant)
    other = make_product(tenant, "OTHER")
    _adjust(tenant, staff, (product, "ADD", "5"), (other, "ADD", "5"))
    with tenant_context(tenant.pk):
        from uuid import uuid4

        from django.db import transaction

        with transaction.atomic():
            level = services.lock_levels([product.pk], services.default_warehouse())[product.pk]
            services.reserve(level, D("4"), services.Ref("ORDER", uuid4()), by=None)
    with pytest.raises(StockReserved) as exc:
        _adjust(tenant, staff, (other, "REMOVE", "1"), (product, "COUNTED", "2"))
    assert "only 1 can be removed" in exc.value.message
    assert exc.value.details["product_code"] == product.code
    assert (_on_hand(tenant, product), _on_hand(tenant, other)) == (5, 5)  # all or nothing
    with pytest.raises(InsufficientStock):
        _adjust(tenant, staff, (other, "REMOVE", "6"))


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"reason": "NOPE"}, "reason_code"),
        ({"note": "   "}, "note"),
        ({"lines": []}, "lines"),
        ({"lines": [("ADD", "0")]}, "lines.1"),
        ({"lines": [("COUNTED", "-1")]}, "lines.1"),
        ({"lines": [("ADD", "1.5")]}, "lines.1"),  # PCS is whole numbers
        ({"lines": [("SET", "1")]}, "lines.1"),
        ({"lines": [("ADD", "1"), ("REMOVE", "1")]}, "lines.2"),  # same product twice
    ],
)
def test_validation(tenant, staff, changes, field):
    product = make_product(tenant)
    lines = [(product, mode, q) for mode, q in changes.get("lines", [("ADD", "1")])]
    with tenant_context(tenant.pk), pytest.raises(InvalidFields) as exc:
        adjustments.create_adjustment(
            AdjustmentInput(
                reason_code=changes.get("reason", "OTHER"),
                note=changes.get("note", "x"),
                lines=[AdjustmentLineInput(p.pk, mode, D(q)) for p, mode, q in lines],
            ),
            by=staff,
        )
    assert field in exc.value.details["fields"]


def test_decimal_units_accept_decimals(tenant, staff):
    with tenant_context(tenant.pk):
        kg = Unit.objects.get(code="KG")
    product = make_product(tenant, unit=kg)
    _adjust(tenant, staff, (product, "ADD", "2.5"))
    assert _on_hand(tenant, product) == D("2.5")


def test_counts_that_all_match_change_nothing(tenant, staff):
    product = make_product(tenant)
    with pytest.raises(InvalidFields, match="Some fields"):
        _adjust(tenant, staff, (product, "COUNTED", "0"))
    with tenant_context(tenant.pk):
        assert not StockAdjustment.objects.exists()


# --- Reorder level ---------------------------------------------------------------------------


def test_reorder_level_is_audited_and_opens_alerts(tenant, staff):
    product = make_product(tenant)
    _adjust(tenant, staff, (product, "ADD", "4"))
    with tenant_context(tenant.pk):
        adjustments.set_reorder_level(product.pk, D("10"), by=staff)
        assert Product.objects.get(pk=product.pk).reorder_level == 10
        assert StockAlert.objects.get(status="OPEN").alert_type == "LOW_STOCK"
        entry = AuditLog.objects.get(action="stock.reorder_level_changed")
        assert entry.changes == {"reorder_level": ["0.000", "10.000"]}
        adjustments.set_reorder_level(product.pk, D("10"), by=staff)  # unchanged: not audited
        assert AuditLog.objects.filter(action="stock.reorder_level_changed").count() == 1
        adjustments.set_reorder_level(product.pk, D("2"), by=staff)
        assert not StockAlert.objects.filter(status="OPEN").exists()
        for bad in ("-1", "1.5"):
            with pytest.raises(InvalidFields):
                adjustments.set_reorder_level(product.pk, D(bad), by=staff)


def test_product_edit_of_reorder_level_re_checks_alerts(tenant, staff):
    owner = make_staff_in(tenant, "OWNER")
    product = make_product(tenant)
    _adjust(tenant, staff, (product, "ADD", "3"))
    with tenant_context(tenant.pk):
        update_product(product.pk, {"reorder_level": D("5")}, by=owner)
        assert StockAlert.objects.get(status="OPEN").alert_type == "LOW_STOCK"
