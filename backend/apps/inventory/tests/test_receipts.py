"""Goods receipts (spec 5.7, ADR-041): drafts, packs, costs before GST, posting, cost pending and
complete costs."""

from decimal import Decimal

import pytest
from django.db import transaction

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.catalog.models import Product, Unit
from apps.inventory import receipts
from apps.inventory.models import StockInward, StockInwardLine, StockLevel, StockMovement
from apps.inventory.receipts import LineInput, NoPendingCosts, NotDraft, ReceiptInput
from apps.inventory.tests.helpers import check_invariants, make_product
from common.errors import InvalidFields
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def tenant(make_tenant):
    return make_tenant()


@pytest.fixture
def owner(tenant):
    return make_staff_in(tenant, "OWNER")


@pytest.fixture
def warehouse_staff(tenant):
    return make_staff_in(tenant, "WAREHOUSE")


def _boxed(tenant, code="BOX-1", **extra):
    with tenant_context(tenant.pk):
        box = Unit.objects.get(code="BOX")
    return make_product(tenant, code, pack_unit=box, pack_size=D("12"), **extra)


def _receipt(*lines, **header):
    return ReceiptInput(lines=list(lines), **header)


def _level(tenant, product):
    with tenant_context(tenant.pk):
        return StockLevel.objects.get(product=product)


def _cost(tenant, product):
    with tenant_context(tenant.pk):
        return Product.objects.get(pk=product.pk).cost_price


def test_post_receives_stock_with_numbered_movements(tenant, owner):
    a = make_product(tenant, "A")
    b = _boxed(tenant)
    with tenant_context(tenant.pk):
        draft = receipts.create_draft(
            _receipt(
                LineInput(a.pk, D("10"), entered_cost=D("5")),
                LineInput(b.pk, D("2"), "PACK", entered_cost=D("100")),
                supplier_name="  Acme Traders ",
                bill_number="B-77",
            ),
            by=owner,
        )
        assert draft.status == "DRAFT" and draft.number is None
        assert draft.total_cost == D("250.00")
        box_line = draft.lines.get(product=b)
        assert (box_line.quantity, box_line.unit_cost) == (D("24"), D("8.3333"))
        assert box_line.line_cost == D("200.00")  # as on the bill: 2 boxes x ₹100
        posted = receipts.post(draft.pk, by=owner)
        second = receipts.create_and_post(_receipt(LineInput(a.pk, D("1"))), by=owner)
    assert posted.status == "POSTED" and posted.supplier_name == "Acme Traders"
    assert posted.posted_at is not None
    year = posted.posted_at.year
    assert (posted.number, second.number) == (f"GRN-{year}-00001", f"GRN-{year}-00002")
    assert _level(tenant, a).quantity_on_hand == 11
    assert _level(tenant, b).quantity_on_hand == 24
    with tenant_context(tenant.pk):
        moves = StockMovement.objects.filter(reference_id=posted.pk)
        assert {m.reference_number for m in moves} == {posted.number}
        assert sorted(m.movement_type for m in moves) == ["INWARD", "INWARD"]
        assert AuditLog.objects.filter(action="stock.inward_posted").count() == 2
    check_invariants(tenant)


def test_cost_method_runs_on_posting(tenant, owner):
    product = make_product(tenant, cost_price=D("5.00"))
    with tenant_context(tenant.pk):
        receipts.create_and_post(
            _receipt(LineInput(product.pk, D("10"), entered_cost=D("5"))), by=owner
        )
        receipts.create_and_post(
            _receipt(LineInput(product.pk, D("10"), entered_cost=D("7"))), by=owner
        )
    assert _cost(tenant, product) == D("6.00")  # (10 x 5 + 10 x 7) / 20


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ({"entered_qty": D("0")}, "above 0"),
        ({"entered_qty": D("1.5")}, "whole numbers"),
        ({"entered_qty": D("1.0001")}, "3 decimals"),
        ({"entered_qty": D("1"), "entered_unit": "PACK"}, "no pack size"),
        ({"entered_qty": D("1"), "entered_cost": D("-1")}, "0 or more"),
    ],
)
def test_line_validation(tenant, owner, line, message):
    product = make_product(tenant)
    with tenant_context(tenant.pk), pytest.raises(InvalidFields) as exc:
        receipts.create_draft(_receipt(LineInput(product.pk, **line)), by=owner)
    assert message in str(exc.value.details)


def test_needs_lines_and_real_products(tenant, owner, make_tenant):
    other = make_product(make_tenant(), "OTHER")
    with tenant_context(tenant.pk):
        with pytest.raises(InvalidFields):
            receipts.create_draft(_receipt(), by=owner)
        with pytest.raises(InvalidFields) as exc:
            receipts.create_draft(_receipt(LineInput(other.pk, D("1"))), by=owner)
    assert "existing product" in str(exc.value.details)


def test_staff_without_costs_view_cannot_send_costs(tenant, warehouse_staff):
    product = make_product(tenant)
    with tenant_context(tenant.pk), pytest.raises(InvalidFields) as exc:
        receipts.create_draft(
            _receipt(LineInput(product.pk, D("1"), entered_cost=D("3"))), by=warehouse_staff
        )
    assert "can see costs" in str(exc.value.details)


def test_warehouse_edit_keeps_costs_it_cannot_see(tenant, owner, warehouse_staff):
    a, b = make_product(tenant, "A"), make_product(tenant, "B")
    with tenant_context(tenant.pk):
        draft = receipts.create_draft(
            _receipt(LineInput(a.pk, D("2"), entered_cost=D("4"))), by=owner
        )
        line = draft.lines.get()
        receipts.update_draft(
            draft.pk,
            _receipt(LineInput(a.pk, D("3"), id=line.pk), LineInput(b.pk, D("1"))),
            by=warehouse_staff,
        )
        kept = StockInward.objects.get(pk=draft.pk).lines.get(product=a)
    assert (kept.entered_qty, kept.entered_cost, kept.line_cost) == (D("3"), D("4"), D("12.00"))


def test_posted_receipt_is_final(tenant, owner):
    product = make_product(tenant)
    with tenant_context(tenant.pk):
        posted = receipts.create_and_post(_receipt(LineInput(product.pk, D("1"))), by=owner)
        for action in (
            lambda: receipts.post(posted.pk, by=owner),
            lambda: receipts.update_draft(
                posted.pk, _receipt(LineInput(product.pk, D("5"))), by=owner
            ),
            lambda: receipts.delete_draft(posted.pk, by=owner),
        ):
            with pytest.raises(NotDraft):
                action()
    assert _level(tenant, product).quantity_on_hand == 1


def test_draft_can_be_deleted(tenant, owner):
    product = make_product(tenant)
    with tenant_context(tenant.pk):
        draft = receipts.create_draft(_receipt(LineInput(product.pk, D("1"))), by=owner)
        receipts.delete_draft(draft.pk, by=owner)
        assert not StockInward.objects.exists() and not StockInwardLine.objects.exists()


def test_failed_post_leaves_nothing(tenant, owner):
    product = make_product(tenant)
    with tenant_context(tenant.pk):
        draft = receipts.create_draft(_receipt(LineInput(product.pk, D("1"))), by=owner)
        Product.objects.filter(pk=product.pk).update(deleted_at="2026-01-01T00:00:00Z")
        with pytest.raises(InvalidFields):
            receipts.post(draft.pk, by=owner)
        assert StockInward.objects.get(pk=draft.pk).status == "DRAFT"
        assert not StockMovement.objects.exists()
        # The sequence rolled back too: the next posted receipt is number 1.
        Product.objects.filter(pk=product.pk).update(deleted_at=None)
        assert str(receipts.post(draft.pk, by=owner).number).endswith("-00001")


# --- Cost pending and complete costs -------------------------------------------------------------


def test_warehouse_posts_quantities_and_lines_wait_for_cost(tenant, warehouse_staff, owner):
    a = make_product(tenant, "A", cost_price=D("5.00"))
    b = _boxed(tenant)
    with tenant_context(tenant.pk):
        posted = receipts.create_and_post(
            _receipt(LineInput(a.pk, D("10")), LineInput(b.pk, D("1"), "PACK")),
            by=warehouse_staff,
        )
    assert posted.cost_pending_lines == 2 and posted.total_cost is None
    assert _level(tenant, a).quantity_on_hand == 10  # available at once
    assert _cost(tenant, a) == D("5.00")  # unchanged until the cost is known
    with tenant_context(tenant.pk):
        line_a = posted.lines.get(product=a)
        line_b = posted.lines.get(product=b)
        assert line_a.cost_status == "PENDING"
        done = receipts.complete_costs(posted.pk, {line_a.pk: D("7")}, by=owner)
        assert done.cost_pending_lines == 1 and done.total_cost == D("70.00")
        # Stock now 10 of which 10 came on this receipt: nothing else was in stock, so the bill
        # cost becomes the cost price.
        assert Product.objects.get(pk=a.pk).cost_price == D("7.00")
        done = receipts.complete_costs(posted.pk, {line_b.pk: D("120")}, by=owner)
        assert done.cost_pending_lines == 0 and done.total_cost == D("190.00")
        line_b.refresh_from_db()
        assert (line_b.unit_cost, line_b.cost_status) == (D("10.0000"), "SET")
        assert line_b.cost_completed_by_id == owner.pk
        assert AuditLog.objects.filter(action="stock.inward_costs_completed").count() == 2
        with pytest.raises(NoPendingCosts):
            receipts.complete_costs(posted.pk, {line_b.pk: D("1")}, by=owner)


def test_complete_costs_averages_with_other_stock_at_that_time(tenant, warehouse_staff, owner):
    product = make_product(tenant, cost_price=D("5.00"))
    with tenant_context(tenant.pk):
        receipts.create_and_post(
            _receipt(LineInput(product.pk, D("10"), entered_cost=D("5"))), by=owner
        )
        pending = receipts.create_and_post(
            _receipt(LineInput(product.pk, D("10"))), by=warehouse_staff
        )
        line = pending.lines.get()
        receipts.complete_costs(pending.pk, {line.pk: D("8")}, by=owner)
    # 20 on hand now, 10 from this receipt: (10 x 5 + 10 x 8) / 20
    assert _cost(tenant, product) == D("6.50")


def test_complete_costs_rules(tenant, warehouse_staff, owner, make_tenant):
    product = make_product(tenant)
    with tenant_context(tenant.pk):
        posted = receipts.create_and_post(
            _receipt(LineInput(product.pk, D("2"))), by=warehouse_staff
        )
        line = posted.lines.get()
        manager_without_pricing = make_staff_in(tenant, "ACCOUNTS")  # costs.view, not manage
        with pytest.raises(InvalidFields) as exc:
            receipts.complete_costs(posted.pk, {line.pk: D("1")}, by=manager_without_pricing)
        assert "manage costs" in str(exc.value.details)
        for costs in ({}, {line.pk: D("-1")}, {posted.pk: D("1")}):
            with pytest.raises(InvalidFields), transaction.atomic():
                receipts.complete_costs(posted.pk, costs, by=owner)
        draft = receipts.create_draft(_receipt(LineInput(product.pk, D("1"))), by=owner)
        with pytest.raises(NoPendingCosts):
            receipts.complete_costs(draft.pk, {draft.lines.get().pk: D("1")}, by=owner)
