"""Credit control with the real ledger (ADR-013, ADR-046 items 8-9): exposure follows the money,
uncleared cheques don't reduce it, overdue shops are held or blocked like over-limit ones and
skipped for backorders (an approved hold covers its order); ageing, outstanding, summary."""

from datetime import timedelta
from decimal import Decimal as D

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.billing.tests.helpers import ship_invoice
from apps.inventory import receipts
from apps.inventory.availability import ShopStockRules
from apps.inventory.tests.helpers import make_product
from apps.ledger import selectors
from apps.ledger import services as ledger
from apps.orders import credit, transitions
from apps.orders.cart import live_rules
from apps.orders.models import BackorderAllocation, OrderLine
from apps.orders.quote import build_quote
from apps.orders.tests.helpers import add_stock, make_shop, place, settings
from apps.payments import services as payments
from apps.payments.services import PaymentInput
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.errors import DomainError
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
TODAY = today_ist()


@pytest.fixture
def world(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    a = make_product(tenant_a, "A", base_price=D("123.45"))  # 5% GST
    add_stock(tenant_a, a, "100")
    return {"t": tenant_a, "owner": owner, "shop": shop, "a": a}


def _exposure(world):
    with tenant_context(world["t"].pk):
        return credit.exposure(world["shop"].pk)


def _pay(world, amount, mode="CASH"):
    data = PaymentInput(
        world["shop"].pk,
        D(amount),
        mode,
        TODAY,
        cheque_number="000123" if mode == "CHEQUE" else "",
    )
    with tenant_context(world["t"].pk):
        return payments.record_payment(data, by=world["owner"])


def _limit(world, limit):
    with tenant_context(world["t"].pk):
        Retailer.objects.filter(pk=world["shop"].pk).update(credit_limit=limit)
        world["shop"].refresh_from_db()


def _opening_debt(world, amount="100.00", days_ago=20):
    """An opening balance is due at once: ``days_ago`` days overdue."""
    with tenant_context(world["t"].pk):
        ledger.post_adjustment(
            world["shop"].pk,
            "OPENING_DEBIT",
            D(amount),
            on=TODAY - timedelta(days=days_ago),
            narration="Old books",
            by=None,
        )


class TestExposure:
    def test_it_follows_the_money(self, world):
        place(world["t"], world["shop"], (world["a"], "10"))
        estimate = D("1296.22")  # the lines' value before rounding to the rupee, not invoiced
        assert _exposure(world) == estimate
        ship_invoice(world["t"], world["shop"], world["owner"], (world["a"], "2"))  # ₹259
        assert _exposure(world) == estimate + D("259.00")  # now in the ledger, not the orders
        _pay(world, "200.00")
        assert _exposure(world) == estimate + D("59.00")
        cheque = _pay(world, "59.00", "CHEQUE")  # credited on receipt, not yet cleared
        with tenant_context(world["t"].pk):
            assert credit.uncleared_cheques(world["shop"].pk) == D("59.00")
        assert _exposure(world) == estimate + D("59.00")
        with tenant_context(world["t"].pk):
            payments.clear_cheque(cheque.pk, by=None)
        assert _exposure(world) == estimate

    def test_invoicing_at_acceptance_moves_value_from_orders_to_the_ledger(self, world):
        settings(world["t"], invoicing__timing="ON_ACCEPTANCE")
        order = place(world["t"], world["shop"], (world["a"], "10"))
        before = _exposure(world)
        with tenant_context(world["t"].pk):
            transitions.accept_order(order.pk, by=world["owner"])
            assert credit.open_order_value(world["shop"].pk) == 0
        # ₹1,296.22 on the order, ₹1,296.00 on the invoice (rounded to the rupee)
        assert (before, _exposure(world)) == (D("1296.22"), D("1296.00"))

    def test_a_cheque_credited_on_clearance_changes_nothing_until_then(self, world):
        settings(world["t"], payments__cheque_credit_timing="ON_CLEARANCE")
        ship_invoice(world["t"], world["shop"], world["owner"], (world["a"], "2"))
        _pay(world, "259.00", "CHEQUE")
        assert _exposure(world) == D("259.00")


class TestOverdueBlocking:
    def test_more_than_n_days_late_counts_as_over_the_limit(self, world, monkeypatch):
        settings(world["t"], credit__block_overdue_after_days=10)
        ship_invoice(world["t"], world["shop"], world["owner"], (world["a"], "2"))  # due in 30
        with tenant_context(world["t"].pk):
            monkeypatch.setattr(credit, "today_ist", lambda: TODAY + timedelta(days=40))
            ok = credit.check(world["shop"], D("1"), breach_action="BLOCK")  # 10 days: not more
            monkeypatch.setattr(credit, "today_ist", lambda: TODAY + timedelta(days=41))
            late = credit.check(world["shop"], D("1"), breach_action="BLOCK")
        assert (ok.outcome, late.outcome, late.reason) == ("OK", "BLOCKED", "OVERDUE")
        assert late.oldest_due == TODAY + timedelta(days=30)
        assert late.limit is None  # whatever the limit

    def test_orders_are_held_with_the_reason_or_refused(self, world):
        settings(world["t"], credit__block_overdue_after_days=10)
        _opening_debt(world, days_ago=11)
        held = place(world["t"], world["shop"], (world["a"], "1"))
        assert (held.status, held.hold_reason) == ("ON_HOLD", "OVERDUE")
        settings(world["t"], credit__breach_action="BLOCK")
        with tenant_context(world["t"].pk):
            quote = build_quote(
                world["shop"],
                [(world["a"].pk, D("1"))],
                rules=live_rules(world["t"].pk),
                stock_rules=ShopStockRules.for_tenant(world["t"].pk),
            )
        assert [p.code for p in quote.blocking] == ["OVERDUE_INVOICES"]
        assert quote.blocking[0].details == {"oldest_due": str(TODAY - timedelta(days=11))}
        with pytest.raises(DomainError) as refused:
            place(world["t"], world["shop"], (world["a"], "1"))
        assert refused.value.code == "OVERDUE_INVOICES"

    def test_paying_or_turning_it_off_lifts_it(self, world):
        settings(world["t"], credit__block_overdue_after_days=10, credit__breach_action="BLOCK")
        _opening_debt(world, days_ago=30)
        with pytest.raises(DomainError):
            place(world["t"], world["shop"], (world["a"], "1"))
        settings(world["t"], credit__block_overdue_after_days=None)
        assert place(world["t"], world["shop"], (world["a"], "1")).status == "PLACED"
        settings(world["t"], credit__block_overdue_after_days=10)
        _pay(world, "100.00")
        assert place(world["t"], world["shop"], (world["a"], "1")).status == "PLACED"

    def test_the_limit_reason_when_only_the_limit_is_breached(self, world):
        settings(world["t"], credit__block_overdue_after_days=10)
        _limit(world, D("100"))
        held = place(world["t"], world["shop"], (world["a"], "1"))  # ₹130 > ₹100
        assert (held.status, held.hold_reason) == ("ON_HOLD", "CREDIT_LIMIT")


class TestBackordersOfOverdueShops:
    def _waiting_order(self, world, **extra):
        with tenant_context(world["t"].pk):
            from apps.inventory.models import StockLevel

            StockLevel.objects.filter(product=world["a"]).update(quantity_on_hand=0)
        return place(world["t"], world["shop"], (world["a"], "3"), **extra)

    def _receive(self, world):
        with tenant_context(world["t"].pk):
            receipts.create_and_post(
                receipts.ReceiptInput(lines=[receipts.LineInput(world["a"].pk, D("3"))]),
                by=world["owner"],
            )
            return list(BackorderAllocation.objects.values_list("status", flat=True))

    def test_an_overdue_shop_is_skipped(self, world):
        settings(world["t"], credit__block_overdue_after_days=10)
        order = self._waiting_order(world)
        with tenant_context(world["t"].pk):
            transitions.accept_order(order.pk, by=world["owner"])
        _opening_debt(world, days_ago=15)
        assert self._receive(world) == ["SKIPPED_CREDIT"]

    def test_an_approved_hold_is_covered(self, world):
        settings(world["t"], credit__block_overdue_after_days=10)
        _opening_debt(world, days_ago=15)
        order = self._waiting_order(world)
        assert order.hold_reason == "OVERDUE"
        with tenant_context(world["t"].pk):
            transitions.approve_hold(order.pk, by=world["owner"])
            transitions.accept_order(order.pk, by=world["owner"])
        assert self._receive(world) == ["PROPOSED"]
        with tenant_context(world["t"].pk):
            assert OrderLine.objects.get(order=order).qty_backordered == 0


class TestReceivables:
    @pytest.fixture
    def books(self, world):
        """Dues on one shop (30-day terms) and unused credit on another."""
        shop = world["shop"]
        with tenant_context(world["t"].pk):
            for kind, amount, days_ago in (
                ("OPENING_DEBIT", "100.00", 95),  # due at once: 95 days late
                ("DEBIT", "400.00", 70),  # due 40 days ago
                ("DEBIT", "200.00", 45),  # due 15 days ago
                ("DEBIT", "300.00", 10),  # due in 20 days
            ):
                ledger.post_adjustment(
                    shop.pk, kind, D(amount), on=TODAY - timedelta(days=days_ago),
                    narration=kind, by=None,
                )  # fmt: skip
            other = make_shop(world["t"], "9876500066")
            ledger.post_adjustment(
                other.pk, "CREDIT", D("50.00"), on=TODAY, narration="Adv", by=None
            )
        return shop, other

    def test_ageing_by_invoice_date_and_by_days_past_due(self, world, books):
        shop, other = books
        with tenant_context(world["t"].pk):
            basis, rows = selectors.ageing()
            _, by_due = selectors.ageing(basis="DUE_DATE")
        assert basis == "INVOICE_DATE"
        first, second = rows
        assert first.retailer_id == shop.pk and second.retailer_id == other.pk
        assert first.buckets == {
            "not_due": 0,
            "d0_30": D("300.00"),
            "d31_60": D("200.00"),
            "d61_90": D("400.00"),
            "d90_plus": D("100.00"),
        }
        assert by_due[0].buckets == {
            "not_due": D("300.00"),
            "d0_30": D("200.00"),
            "d31_60": D("400.00"),
            "d61_90": 0,
            "d90_plus": D("100.00"),
        }
        assert (first.owed, first.overdue, first.net) == (D("1000.00"), D("700.00"), D("1000.00"))
        assert (second.owed, second.unapplied_credit, second.net) == (
            D("0.00"),
            D("50.00"),
            D("-50.00"),
        )
        settings(world["t"], receivables__ageing_basis="DUE_DATE")
        with tenant_context(world["t"].pk):
            assert selectors.ageing()[0] == "DUE_DATE"
            assert selectors.ageing([other.pk])[1][0].retailer_id == other.pk

    def test_outstanding_and_summary(self, world, books):
        shop, _ = books
        with tenant_context(world["t"].pk):
            position = selectors.outstanding(shop.pk)
            summary = selectors.receivables_summary()
            later = selectors.receivables_summary(on=TODAY + timedelta(days=14))
        assert position.balance == position.owed == D("1000.00")
        assert (position.overdue, position.days_overdue) == (D("700.00"), 95)
        assert summary == {
            "owed": D("1000.00"),
            "overdue": D("700.00"),
            "shops_overdue": 1,
            "due_this_week": 0,
            "unapplied_credit": D("50.00"),
        }
        assert later["due_this_week"] == D("300.00")  # due in 20 days: within 7 of day 14
