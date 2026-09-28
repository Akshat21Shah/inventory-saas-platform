"""Posting, adjustments and allocations on the shop's account (PLAN §4.5, ADR-017/046)."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from django.db import transaction

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.ledger import allocation, services
from apps.ledger.models import Allocation, LedgerAdjustment, LedgerEntry, RetailerAccount
from apps.ledger.tests.helpers import check_ledger
from apps.orders.tests.helpers import make_shop
from common.errors import InvalidFields, NotFound
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
DAY = date(2026, 9, 28)


@pytest.fixture
def world(tenant_a):
    return {"t": tenant_a, "owner": make_staff_in(tenant_a, "OWNER"), "shop": make_shop(tenant_a)}


def _adjust(world, kind, amount, narration="Carried over", **extra):
    with tenant_context(world["t"].pk):
        return services.post_adjustment(
            world["shop"].pk,
            kind,
            D(amount),
            on=extra.pop("on", DAY),
            narration=narration,
            by=world["owner"],
            **extra,
        )


def _account(world):
    with tenant_context(world["t"].pk):
        return RetailerAccount.objects.get(retailer=world["shop"])


def test_old_bills_carry_their_dates_and_an_advance_is_once(world):
    """Opening bills (ADR-047): several per shop, each dated on the old bill and due after the
    shop's terms unless a due date is given; a bill number is imported once; one advance."""
    first = _adjust(world, "OPENING_DEBIT", "1000.00", bill_number="SD/25-26/0412")
    assert (first.balance_due, first.due_date) == (D("1000.00"), DAY + timedelta(days=30))
    second = _adjust(
        world,
        "OPENING_DEBIT",
        "250.00",
        on=DAY - timedelta(days=60),
        due_date=DAY - timedelta(days=45),
    )
    assert (second.adjustment_date, second.due_date) == (
        DAY - timedelta(days=60),
        DAY - timedelta(days=45),
    )
    with pytest.raises(InvalidFields):  # the same old bill twice
        _adjust(world, "OPENING_DEBIT", "1.00", bill_number="SD/25-26/0412")
    with pytest.raises(InvalidFields):  # due before the bill date
        _adjust(world, "OPENING_DEBIT", "1.00", due_date=DAY - timedelta(days=1))
    _adjust(world, "OPENING_CREDIT", "5.00")
    with pytest.raises(InvalidFields):
        _adjust(world, "OPENING_CREDIT", "5.00")
    account = _account(world)
    assert (account.balance, account.total_debits) == (D("1245.00"), D("1250.00"))
    with tenant_context(world["t"].pk):
        entry = LedgerEntry.objects.order_by("created_at").first()
        assert entry is not None
        assert (entry.entry_type, entry.reference_number) == (
            "OPENING_BALANCE",
            "Opening balance (owed) SD/25-26/0412",
        )
        assert AuditLog.objects.filter(action="ledger.adjustment_posted").count() == 3
    check_ledger(world["t"])


def test_credit_meets_what_is_owed_oldest_first(world):
    _adjust(world, "OPENING_DEBIT", "1000.00")
    later = _adjust(world, "DEBIT", "200.00", "Freight charged")
    assert later.due_date == date(2026, 10, 28)  # the shop's 30-day terms
    credit = _adjust(world, "CREDIT", "1100.00", "Rate difference")
    with tenant_context(world["t"].pk):
        opening = LedgerAdjustment.objects.get(kind="OPENING_DEBIT")
        later.refresh_from_db()
        credit.refresh_from_db()
    assert (opening.balance_due, later.balance_due, credit.unapplied_amount) == (
        D("0.00"),
        D("100.00"),
        D("0.00"),
    )
    assert _account(world).balance == D("100.00")
    check_ledger(world["t"])


def test_unused_credit_waits_for_the_next_due(world):
    _adjust(world, "OPENING_CREDIT", "500.00")
    account = _account(world)
    assert (account.balance, account.unapplied_credit) == (D("-500.00"), D("500.00"))
    _adjust(world, "DEBIT", "300.00", "Old dues found")
    account = _account(world)
    assert (account.balance, account.unapplied_credit) == (D("-200.00"), D("200.00"))
    check_ledger(world["t"])


def test_an_allocation_can_be_undone_and_redone(world):
    _adjust(world, "OPENING_DEBIT", "1000.00")
    _adjust(world, "CREDIT", "300.00")
    with tenant_context(world["t"].pk), transaction.atomic():
        account = services.lock_account(world["shop"].pk)
        first = Allocation.objects.get()
        undo = allocation.reverse(account, first, by=world["owner"], reason="Wrong due")
        assert undo.amount == D("-300.00") and undo.reverses == first
        with pytest.raises(InvalidFields):
            allocation.reverse(account, first, by=world["owner"], reason="Twice")
    assert _account(world).unapplied_credit == D("300.00")
    check_ledger(world["t"])
    with tenant_context(world["t"].pk), transaction.atomic():
        account = services.lock_account(world["shop"].pk)
        allocation.settle(account, by=world["owner"])
    assert _account(world).unapplied_credit == D("0.00")
    check_ledger(world["t"])


def test_adjustments_need_a_real_amount_and_a_narration(world):
    for amount, narration in (("0", "x"), ("-5", "x"), ("1.005", "x"), ("5", " ")):
        with pytest.raises(InvalidFields):
            _adjust(world, "DEBIT", amount, narration)
    with pytest.raises(InvalidFields):
        _adjust(world, "BONUS", "5")


def test_another_tenants_shop_is_not_found(world, tenant_b):
    with tenant_context(tenant_b.pk), pytest.raises(NotFound):
        services.post_adjustment(
            world["shop"].pk, "DEBIT", D("5"), on=DAY, narration="x", by=world["owner"]
        )


def test_posting_rules(world):
    with tenant_context(world["t"].pk), transaction.atomic():
        account = services.lock_account(world["shop"].pk)
        ref = services.Reference("ADJUSTMENT", world["shop"].pk)
        with pytest.raises(ValueError):
            services.post(
                account,
                "DEBIT_ADJUSTMENT",
                debit=D("1"),
                credit=D("1"),
                entry_date=DAY,
                ref=ref,
                by=None,
            )
        with pytest.raises(ValueError):
            services.post(account, "DEBIT_ADJUSTMENT", entry_date=DAY, ref=ref, by=None)
    with tenant_context(world["t"].pk), pytest.raises(RuntimeError):
        # outside a transaction (the test wraps one, so check the guard directly)
        from unittest import mock

        with mock.patch("django.db.transaction.get_connection") as conn:
            conn.return_value.in_atomic_block = False
            services.lock_account(world["shop"].pk)
