"""Offline payments (PLAN §4.6, ADR-017/022/046): modes, matching (chosen dues, then oldest
first), advances, cheques (credited on receipt or on clearance, bounces), reversals, salesman
collections and handover, reallocation."""

from datetime import timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.billing.models import Invoice
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.ledger import services as ledger
from apps.ledger.models import Allocation, LedgerEntry, RetailerAccount
from apps.ledger.tests.helpers import check_ledger
from apps.orders.tests.helpers import add_stock, make_shop, settings
from apps.payments import selectors, services
from apps.payments.models import Payment
from apps.payments.services import DueAmount, PaymentInput
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.errors import DomainError, InvalidFields, NotFound
from common.models import OutboxEvent
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    a = make_product(tenant_a, "A", base_price=D("123.45"))  # 5% GST
    add_stock(tenant_a, a, "100")
    return {"t": tenant_a, "owner": owner, "shop": shop, "a": a}


def _invoice(world, qty):
    """2 → ₹259.00, 1 → ₹130.00, 10 → ₹1,296.00."""
    return ship_invoice(world["t"], world["shop"], world["owner"], (world["a"], qty))


def _pay(world, amount, mode="CASH", *, by=None, collect=False, **extra):
    data = PaymentInput(
        retailer_id=extra.pop("retailer_id", world["shop"].pk),
        amount=D(amount),
        mode=mode,
        payment_date=extra.pop("payment_date", today_ist()),
        cheque_number="123456" if mode == "CHEQUE" else "",
        **extra,
    )
    with tenant_context(world["t"].pk):
        if collect:
            return services.collect_payment(data, by=by)
        return services.record_payment(data, by=by or world["owner"])


def _fresh(world, *rows):
    with tenant_context(world["t"].pk):
        for row in rows:
            row.refresh_from_db()
        return RetailerAccount.objects.get(retailer=world["shop"]).balance


def test_cash_pays_the_earliest_dues_first(world):
    first, second = _invoice(world, "2"), _invoice(world, "1")  # ₹259, ₹130
    payment = _pay(world, "300.00")
    assert payment.number.startswith("RCT/")
    assert (payment.status, payment.credited, payment.unapplied_amount) == (
        "RECEIVED",
        True,
        D("0.00"),
    )
    balance = _fresh(world, first, second)
    assert (first.balance_due, first.payment_status) == (D("0.00"), "PAID")
    assert (second.balance_due, second.payment_status) == (D("89.00"), "PARTIAL")
    assert balance == D("89.00")
    with tenant_context(world["t"].pk):
        entry = LedgerEntry.objects.get(entry_type="PAYMENT")
        assert (entry.credit, entry.reference_number) == (D("300.00"), payment.number)
        assert OutboxEvent.objects.filter(event_type="payment.received").count() == 1
    check_ledger(world["t"])


def test_chosen_dues_are_paid_first(world):
    first, second = _invoice(world, "2"), _invoice(world, "1")
    _pay(world, "150.00", pay_first=(DueAmount("INVOICE", second.pk, D("130.00")),))
    _fresh(world, first, second)
    assert (first.balance_due, second.balance_due) == (D("239.00"), D("0.00"))
    with tenant_context(world["t"].pk):
        assert list(
            Allocation.objects.order_by("created_at").values_list("automatic", "amount")
        ) == [(False, D("130.00")), (True, D("20.00"))]
    check_ledger(world["t"])


def test_an_advance_is_kept_and_used_for_the_next_invoice(world):
    payment = _pay(world, "500.00")
    assert payment.unapplied_amount == D("500.00")
    assert _fresh(world) == D("-500.00")
    invoice = _invoice(world, "2")
    _fresh(world, payment, invoice)
    assert (payment.unapplied_amount, invoice.payment_status) == (D("241.00"), "PAID")
    check_ledger(world["t"])


def test_with_advances_off_only_what_is_owed_can_be_paid(world):
    settings(world["t"], payments__hold_advances=False)
    _invoice(world, "2")
    with pytest.raises(DomainError) as refused:
        _pay(world, "259.01")
    assert refused.value.code == "PAYMENT_EXCEEDS_OUTSTANDING"
    assert refused.value.details == {"outstanding": "259.00"}
    _pay(world, "259.00")
    with pytest.raises(DomainError):
        _pay(world, "1.00")
    check_ledger(world["t"])


def test_input_is_checked(world):
    invoice = _invoice(world, "2")
    tomorrow = today_ist() + timedelta(days=1)
    bad: list[dict[str, Any]] = [
        {"amount": "0"},
        {"amount": "10.005"},
        {"amount": "10", "mode": "CARD"},
        {"amount": "10", "payment_date": tomorrow},
        {"amount": "10", "pay_first": (DueAmount("INVOICE", invoice.pk, D("11")),)},
        {
            "amount": "10",
            "pay_first": (
                DueAmount("INVOICE", invoice.pk, D("1")),
                DueAmount("INVOICE", invoice.pk, D("1")),
            ),
        },
    ]
    for kwargs in bad:
        with pytest.raises(InvalidFields):
            _pay(world, **kwargs)
    with tenant_context(world["t"].pk):
        with pytest.raises(InvalidFields):
            services.record_payment(
                PaymentInput(world["shop"].pk, D("10"), "CHEQUE", today_ist()), by=world["owner"]
            )
        assert not Payment.objects.exists()


class TestCheques:
    def test_credited_on_receipt_and_reversed_when_it_bounces(self, world):
        invoice = _invoice(world, "2")
        cheque = _pay(world, "259.00", "CHEQUE")
        assert (cheque.status, cheque.credit_timing, cheque.credited) == (
            "RECEIVED",
            "ON_RECEIPT",
            True,
        )
        with tenant_context(world["t"].pk):
            bounced = services.bounce_cheque(cheque.pk, reason="Insufficient funds", by=None)
        balance = _fresh(world, invoice)
        assert (bounced.status, bounced.credited, bounced.unapplied_amount) == (
            "BOUNCED",
            False,
            D("0.00"),
        )
        assert (invoice.balance_due, invoice.payment_status, balance) == (
            D("259.00"),
            "UNPAID",
            D("259.00"),
        )
        with tenant_context(world["t"].pk):
            reversal = LedgerEntry.objects.get(entry_type="PAYMENT_REVERSAL")
            assert reversal.debit == D("259.00") and reversal.reverses.entry_type == "PAYMENT"
            assert AuditLog.objects.filter(action="payments.cheque_bounced").exists()
            assert OutboxEvent.objects.filter(event_type="payment.reversed").exists()
            with pytest.raises(DomainError):
                services.bounce_cheque(cheque.pk, reason="Again", by=None)
        check_ledger(world["t"])

    def test_credited_only_when_cleared(self, world):
        settings(world["t"], payments__cheque_credit_timing="ON_CLEARANCE")
        invoice = _invoice(world, "2")
        cheque = _pay(world, "259.00", "CHEQUE")
        assert (cheque.status, cheque.credited, _fresh(world)) == (
            "PENDING_CLEARANCE",
            False,
            D("259.00"),
        )
        with tenant_context(world["t"].pk):
            assert not LedgerEntry.objects.filter(entry_type="PAYMENT").exists()
            cleared = services.clear_cheque(cheque.pk, by=world["owner"])
        _fresh(world, invoice)
        assert (cleared.status, cleared.credited, invoice.payment_status) == (
            "CLEARED",
            True,
            "PAID",
        )
        check_ledger(world["t"])

    def test_a_bounce_before_clearance_has_no_ledger_effect(self, world):
        settings(world["t"], payments__cheque_credit_timing="ON_CLEARANCE")
        _invoice(world, "2")
        cheque = _pay(world, "259.00", "CHEQUE")
        with tenant_context(world["t"].pk):
            services.bounce_cheque(cheque.pk, reason="Signature mismatch", by=None)
            assert not LedgerEntry.objects.filter(entry_type__startswith="PAYMENT").exists()
            with pytest.raises(DomainError):
                services.clear_cheque(cheque.pk, by=None)
        assert _fresh(world) == D("259.00")
        check_ledger(world["t"])

    def test_dues_are_chosen_when_it_clears(self, world):
        settings(world["t"], payments__cheque_credit_timing="ON_CLEARANCE")
        invoice = _invoice(world, "2")
        with pytest.raises(InvalidFields):
            _pay(world, "10", "CHEQUE", pay_first=(DueAmount("INVOICE", invoice.pk, D("10")),))


def test_a_payment_entered_in_error_is_reversed_and_other_credit_steps_in(world):
    invoice = _invoice(world, "2")
    payment = _pay(world, "259.00")
    with tenant_context(world["t"].pk):
        ledger.post_adjustment(
            world["shop"].pk, "CREDIT", D("100.00"), on=today_ist(), narration="Scheme", by=None
        )
        with pytest.raises(InvalidFields):
            services.reverse_payment(payment.pk, reason=" ", by=world["owner"])
        services.reverse_payment(payment.pk, reason="Wrong shop", by=world["owner"])
    balance = _fresh(world, invoice, payment)
    assert (payment.status, payment.reversal_reason) == ("REVERSED", "Wrong shop")
    assert (invoice.balance_due, balance) == (D("159.00"), D("159.00"))  # the ₹100 credit used
    with tenant_context(world["t"].pk):
        assert AuditLog.objects.filter(action="payments.reversed").exists()
        with pytest.raises(DomainError):
            services.reverse_payment(payment.pk, reason="Again", by=world["owner"])
    check_ledger(world["t"])


class TestSalesmanCollections:
    @pytest.fixture
    def sales(self, world):
        salesman = make_staff_in(world["t"], "SALES")
        settings(world["t"], orders__sales_visibility="ASSIGNED_RETAILERS")
        with tenant_context(world["t"].pk):
            Retailer.objects.filter(pk=world["shop"].pk).update(salesperson=salesman)
        return salesman

    def test_collected_then_handed_over(self, world, sales):
        invoice = _invoice(world, "2")
        collected = _pay(world, "200.00", "UPI", by=sales, collect=True)
        assert (collected.handover_status, collected.collected_by_id) == ("WITH_SALESMAN", sales.pk)
        _fresh(world, invoice)
        assert invoice.balance_due == D("59.00")  # credited at once
        cheque = _pay(world, "59.00", "CHEQUE", by=sales, collect=True)
        office = _pay(world, "10.00")
        with tenant_context(world["t"].pk):
            [row] = selectors.collections_pending_handover()
            assert (row.salesman_id, row.count, row.amount) == (sales.pk, 2, D("259.00"))
            assert selectors.pending_handover_total() == D("259.00")
            with pytest.raises(InvalidFields):
                services.hand_over([collected.pk, office.pk], by=world["owner"])
            services.hand_over([collected.pk, cheque.pk], by=world["owner"])
            services.hand_over([collected.pk], by=world["owner"])  # again: nothing more
            assert selectors.collections_pending_handover() == []
            assert AuditLog.objects.filter(action="payments.handed_over").count() == 2
            collected.refresh_from_db()
        assert (collected.handover_status, collected.handed_over_by_id) == (
            "HANDED_OVER",
            world["owner"].pk,
        )
        check_ledger(world["t"])

    def test_only_own_shops_and_only_when_allowed(self, world, sales):
        other = make_shop(world["t"], "9876500077")
        with pytest.raises(NotFound):
            _pay(world, "10", by=sales, collect=True, retailer_id=other.pk)
        with pytest.raises(InvalidFields):
            _pay(
                world,
                "10",
                by=sales,
                collect=True,
                pay_first=(DueAmount("INVOICE", other.pk, D("1")),),
            )
        settings(world["t"], payments__sales_can_collect=False)
        with pytest.raises(DomainError) as refused:
            _pay(world, "10", by=sales, collect=True)
        assert refused.value.status_code == 403


class TestReallocation:
    def test_an_automatic_allocation_moves_to_another_invoice(self, world):
        first, second = _invoice(world, "2"), _invoice(world, "1")
        _pay(world, "130.00")  # automatically against the first
        with tenant_context(world["t"].pk):
            auto = Allocation.objects.get(invoice=first)
            undo, [moved] = services.reallocate(
                auto.pk,
                to=[DueAmount("INVOICE", second.pk, D("130.00"))],
                reason="Shop asked to clear the later bill",
                by=world["owner"],
            )
            assert AuditLog.objects.filter(action="payments.allocation_reversed").exists()
            with pytest.raises(InvalidFields):
                services.reallocate(auto.pk, to=[], reason="Again", by=world["owner"])
        _fresh(world, first, second)
        assert (undo.amount, moved.invoice_id, moved.automatic) == (D("-130.00"), second.pk, False)
        assert (first.balance_due, second.balance_due) == (D("259.00"), D("0.00"))
        check_ledger(world["t"])

    def test_undone_money_waits_and_can_be_allocated_by_hand(self, world):
        first = _invoice(world, "2")
        payment = _pay(world, "100.00")
        with tenant_context(world["t"].pk):
            auto = Allocation.objects.get()
            services.reallocate(auto.pk, to=[], reason="Hold for now", by=world["owner"])
            payment.refresh_from_db()
            assert payment.unapplied_amount == D("100.00")
            check_ledger(world["t"])
            services.allocate(
                world["shop"].pk,
                source_type="PAYMENT",
                source_id=payment.pk,
                to=[DueAmount("INVOICE", first.pk, D("60.00"))],
                by=world["owner"],
            )
            with pytest.raises(InvalidFields):  # more than the payment has left
                services.allocate(
                    world["shop"].pk,
                    source_type="PAYMENT",
                    source_id=payment.pk,
                    to=[DueAmount("INVOICE", first.pk, D("40.01"))],
                    by=world["owner"],
                )
            assert AuditLog.objects.filter(action="payments.allocated").count() == 1
        _fresh(world, first, payment)
        assert (first.balance_due, payment.unapplied_amount) == (D("199.00"), D("40.00"))
        check_ledger(world["t"])


def test_invoices_of_another_shop_cannot_be_chosen(world):
    other = make_shop(world["t"], "9876500088")
    theirs = ship_invoice(world["t"], other, world["owner"], (world["a"], "1"))
    with pytest.raises(InvalidFields):
        _pay(world, "10", pay_first=(DueAmount("INVOICE", theirs.pk, D("10")),))
    with tenant_context(world["t"].pk):
        assert Invoice.objects.get(pk=theirs.pk).balance_due == theirs.grand_total
