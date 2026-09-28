"""Credit notes (PLAN §4.4, §6.5, ADR-046 items 4-5): returns with what happened to the goods,
price adjustments, automatic short-supply and cancellation notes with ON_ACCEPTANCE invoicing,
exact remainders, and credit beyond the invoice used for the shop's next dues."""

from decimal import Decimal as D

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.billing import credit_notes
from apps.billing.credit_notes import ReturnLine
from apps.billing.models import CreditNote, Invoice
from apps.inventory import receipts
from apps.inventory.models import StockLevel, StockMovement
from apps.inventory.tests.helpers import make_product
from apps.ledger import services as ledger
from apps.ledger.models import RetailerAccount
from apps.ledger.tests.helpers import check_ledger
from apps.orders import backorders, fulfilment, transitions
from apps.orders.fulfilment import Transport
from apps.orders.models import Fulfilment, FulfilmentLine, Order, OrderLine
from apps.orders.tests.helpers import add_stock, check_order_invariants, make_shop, place, settings
from common.dates import today_ist
from common.errors import InvalidFields
from common.models import OutboxEvent
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
NO_TRANSPORT = Transport("", "", "")


@pytest.fixture
def world(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    a = make_product(tenant_a, "A", base_price=D("123.45"))  # 5% GST
    b = make_product(tenant_a, "B", base_price=D("50.00"))
    add_stock(tenant_a, a, "20")
    return {"t": tenant_a, "owner": owner, "shop": shop, "a": a, "b": b}


def _invoice(world, *lines):
    """Place, accept, pack in full and dispatch: the invoice (ON_DISPATCH)."""
    order = place(world["t"], world["shop"], *lines)
    with tenant_context(world["t"].pk):
        transitions.accept_order(order.pk, by=world["owner"])
        shipment = Fulfilment.objects.get(order=order)
        fulfilment.pack(shipment.pk, {}, by=world["owner"])
        fulfilment.dispatch(shipment.pk, NO_TRANSPORT, by=world["owner"])
        return Invoice.objects.get(fulfilment=shipment)


def _return(world, invoice, qty, disposition="RETURN_TO_STOCK", reason="DAMAGED", note=""):
    with tenant_context(world["t"].pk):
        line = invoice.lines.get()
        return credit_notes.issue_return(
            invoice.pk,
            [ReturnLine(line.pk, D(qty), disposition)],
            reason=reason,
            note=note,
            by=world["owner"],
        )


def _on_hand(world, product):
    with tenant_context(world["t"].pk):
        return StockLevel.objects.get(product=product).quantity_on_hand


def test_return_three_then_seven_reverses_the_invoice_exactly(world):
    invoice = _invoice(world, (world["a"], "10"))
    # 10 x 123.45 at 5%: taxable 1,234.50, CGST = SGST = 30.86, total 1,296.22 → ₹1,296.00
    assert invoice.grand_total == D("1296.00")
    first = _return(world, invoice, "3")
    assert first.number.startswith("CN/")
    assert (first.taxable_total, first.cgst_total, first.sgst_total) == (
        D("370.35"),
        D("9.26"),
        D("9.26"),
    )
    assert (first.grand_total, first.round_off) == (D("389.00"), D("0.13"))
    second = _return(world, invoice, "7")
    assert second.taxable_total == D("864.15")
    assert second.grand_total == invoice.grand_total - first.grand_total == D("907.00")
    with tenant_context(world["t"].pk):
        invoice.refresh_from_db()
        assert (invoice.amount_credited, invoice.balance_due, invoice.payment_status) == (
            D("1296.00"),
            D("0.00"),
            "PAID",
        )
        assert RetailerAccount.objects.get(retailer=world["shop"]).balance == D("0.00")
        with pytest.raises(InvalidFields):
            credit_notes.issue_return(
                invoice.pk,
                [ReturnLine(invoice.lines.get().pk, D("1"))],
                reason="DAMAGED",
                by=world["owner"],
            )
        assert AuditLog.objects.filter(action="billing.credit_note_issued").count() == 2
        event = OutboxEvent.objects.filter(event_type="credit_note.issued").first()
        assert event is not None and event.payload["issued_automatically"] is False
    assert _on_hand(world, world["a"]) == 20  # all ten came back to stock
    check_ledger(world["t"])


def test_what_happened_to_the_goods(world):
    invoice = _invoice(world, (world["a"], "6"))
    assert _on_hand(world, world["a"]) == 14
    damaged = _return(world, invoice, "2", "DAMAGED")
    assert _on_hand(world, world["a"]) == 14  # came back and was written off
    with tenant_context(world["t"].pk):
        kinds = list(
            StockMovement.objects.filter(reference_id=damaged.pk)
            .order_by("created_at")
            .values_list("movement_type", flat=True)
        )
    assert kinds == ["RETURN", "DAMAGE"]
    kept = _return(world, invoice, "1", "NOT_RETURNED", reason="OTHER", note="Shop kept it")
    with tenant_context(world["t"].pk):
        assert not StockMovement.objects.filter(reference_id=kept.pk).exists()
    assert _on_hand(world, world["a"]) == 14
    check_ledger(world["t"])


def test_returned_goods_serve_a_waiting_backorder(world, django_capture_on_commit_callbacks):
    add_stock(world["t"], world["b"], "4")
    invoice = _invoice(world, (world["b"], "4"))
    waiting = place(world["t"], make_shop(world["t"], "9876500099"), (world["b"], "2"))
    with tenant_context(world["t"].pk):
        transitions.accept_order(waiting.pk, by=world["owner"])
    with django_capture_on_commit_callbacks(execute=True):
        _return(world, invoice, "3", reason="EXCESS_SUPPLY")
    with tenant_context(world["t"].pk):
        [proposal] = OrderLine.objects.get(order=waiting).allocations.all()
    assert (proposal.trigger, proposal.quantity) == ("RETURN", 2)
    check_order_invariants(world["t"])


def test_returns_need_a_reason_and_a_real_quantity(world):
    invoice = _invoice(world, (world["a"], "2"))
    with tenant_context(world["t"].pk):
        line = invoice.lines.get()
        bad = [
            ({"reason": "BORED"}, [ReturnLine(line.pk, D("1"))]),
            ({"reason": "OTHER"}, [ReturnLine(line.pk, D("1"))]),  # other needs a note
            ({"reason": "DAMAGED"}, [ReturnLine(line.pk, D("3"))]),  # more than invoiced
            ({"reason": "DAMAGED"}, [ReturnLine(line.pk, D("0"))]),
            ({"reason": "DAMAGED"}, [ReturnLine(line.pk, D("1"), "LOST")]),
            ({"reason": "DAMAGED"}, [ReturnLine(line.pk, D("1")), ReturnLine(line.pk, D("1"))]),
            ({"reason": "DAMAGED"}, []),
        ]
        for kwargs, lines in bad:
            with pytest.raises(InvalidFields):
                credit_notes.issue_return(invoice.pk, lines, by=world["owner"], **kwargs)
        assert not CreditNote.objects.exists()


def test_a_price_adjustment_beyond_what_is_owed_becomes_credit(world):
    first = _invoice(world, (world["a"], "2"))  # ₹259.00
    with tenant_context(world["t"].pk):
        line = first.lines.get()
        with pytest.raises(InvalidFields):
            credit_notes.issue_price_adjustment(
                first.pk, {line.pk: D("10.00")}, note=" ", by=world["owner"]
            )
        note = credit_notes.issue_price_adjustment(
            first.pk, {line.pk: D("200.00")}, note="Rate agreed lower", by=world["owner"]
        )
    assert (note.kind, note.taxable_total, note.grand_total) == (
        "PRICE_ADJUSTMENT",
        D("200.00"),
        D("210.00"),
    )
    assert note.applied_to_invoice == D("210.00")
    check_ledger(world["t"])


def test_credit_beyond_the_invoice_is_used_for_the_next_one(world):
    first = _invoice(world, (world["a"], "2"))  # ₹259.00
    with tenant_context(world["t"].pk):
        ledger.post_adjustment(  # the shop paid most of it already (as a credit, for the test)
            world["shop"].pk,
            "CREDIT",
            D("250.00"),
            on=today_ist(),
            narration="Paid",
            by=world["owner"],
        )
        first.refresh_from_db()
        assert first.balance_due == D("9.00")
    note = _return(world, first, "2")  # ₹259.00 back: 9 against the invoice, 250 credit
    assert (note.applied_to_invoice, note.unapplied_amount) == (D("9.00"), D("250.00"))
    second = _invoice(world, (world["a"], "1"))  # ₹130.00
    with tenant_context(world["t"].pk):
        second.refresh_from_db()
        note.refresh_from_db()
    assert (second.balance_due, note.unapplied_amount) == (D("0.00"), D("120.00"))
    check_ledger(world["t"])


class TestAutomaticCorrectionsAtAcceptance:
    @pytest.fixture
    def accepted(self, world):
        settings(world["t"], invoicing__timing="ON_ACCEPTANCE")
        order = place(world["t"], world["shop"], (world["a"], "10"))
        with tenant_context(world["t"].pk):
            transitions.accept_order(order.pk, by=world["owner"])
            shipment = Fulfilment.objects.get(order=order)
            invoice = Invoice.objects.get(fulfilment=shipment)
        return {**world, "order": order, "shipment": shipment, "invoice": invoice}

    def test_a_short_pack_is_credited_and_waits_to_be_invoiced_again(self, accepted):
        with tenant_context(accepted["t"].pk):
            fl = FulfilmentLine.objects.get(fulfilment=accepted["shipment"])
            fulfilment.pack(accepted["shipment"].pk, {fl.pk: D("8")}, by=accepted["owner"])
            [note] = CreditNote.objects.all()
            credited = note.lines.get().quantity
            line = OrderLine.objects.get(order=accepted["order"])
        assert (note.kind, note.issued_automatically, credited) == ("SHORT_SUPPLY", True, 2)
        assert (line.qty_invoiced, line.qty_backordered) == (8, 2)
        with tenant_context(accepted["t"].pk):
            receipts.create_and_post(
                receipts.ReceiptInput(lines=[receipts.LineInput(accepted["a"].pk, D("2"))]),
                by=accepted["owner"],
            )
            [proposal] = line.allocations.all()
            [again] = backorders.confirm([proposal.pk], by=accepted["owner"])
            later = Invoice.objects.get(fulfilment=again)
            line.refresh_from_db()
        assert (later.issued_trigger, line.qty_invoiced) == ("ON_ALLOCATION", 10)
        check_ledger(accepted["t"])
        check_order_invariants(accepted["t"])

    def test_short_pack_with_backorders_off_is_cancelled_and_credited(self, accepted):
        snapshot = {**accepted["order"].settings_snapshot, "backorders.enabled": False}
        with tenant_context(accepted["t"].pk):
            Order.objects.filter(pk=accepted["order"].pk).update(settings_snapshot=snapshot)
            fl = FulfilmentLine.objects.get(fulfilment=accepted["shipment"])
            fulfilment.pack(accepted["shipment"].pk, {fl.pk: D("7")}, by=accepted["owner"])
            line = OrderLine.objects.get(order=accepted["order"])
        assert (line.qty_invoiced, line.qty_cancelled) == (7, 3)
        check_ledger(accepted["t"])
        check_order_invariants(accepted["t"])

    def test_cancelling_the_shipment_or_the_order_is_credited(self, accepted):
        with tenant_context(accepted["t"].pk):
            fulfilment.cancel_accepted(
                accepted["order"].pk, reason="Shop closed", by=accepted["owner"]
            )
            [note] = CreditNote.objects.all()
            invoice = Invoice.objects.get(pk=accepted["invoice"].pk)
            balance = RetailerAccount.objects.get(retailer=accepted["shop"]).balance
        assert (note.kind, note.grand_total) == ("CANCELLATION", invoice.grand_total)
        assert (invoice.balance_due, balance) == (0, 0)
        check_ledger(accepted["t"])
        check_order_invariants(accepted["t"])

    def test_at_dispatch_a_short_pack_needs_no_credit_note(self, world):
        order = place(world["t"], world["shop"], (world["a"], "5"))
        with tenant_context(world["t"].pk):
            transitions.accept_order(order.pk, by=world["owner"])
            shipment = Fulfilment.objects.get(order=order)
            fl = FulfilmentLine.objects.get(fulfilment=shipment)
            fulfilment.pack(shipment.pk, {fl.pk: D("3")}, by=world["owner"])
            assert not CreditNote.objects.exists()

    def test_a_shipment_sent_back_to_backorder_is_credited(self, accepted):
        with tenant_context(accepted["t"].pk):
            fulfilment.cancel_shipment(
                accepted["shipment"].pk, to_backorder=True, reason="Van broke", by=accepted["owner"]
            )
            [note] = CreditNote.objects.all()
            line = OrderLine.objects.get(order=accepted["order"])
        assert (note.kind, note.issued_automatically) == ("CANCELLATION", True)
        assert (line.qty_invoiced, line.qty_backordered) == (0, 10)
        check_ledger(accepted["t"])
        check_order_invariants(accepted["t"])


def test_a_declined_repriced_backorder_is_credited(world):
    settings(world["t"], invoicing__timing="ON_ACCEPTANCE", backorders__billing_price="CURRENT")
    order = place(world["t"], world["shop"], (world["b"], "4"))
    with tenant_context(world["t"].pk):
        transitions.accept_order(order.pk, by=world["owner"])
        world["b"].base_price = D("60.00")
        world["b"].save(update_fields=["base_price"])
        receipts.create_and_post(
            receipts.ReceiptInput(lines=[receipts.LineInput(world["b"].pk, D("4"))]),
            by=world["owner"],
        )
        [proposal] = OrderLine.objects.get(order=order).allocations.all()
        [shipment] = backorders.confirm([proposal.pk], by=world["owner"])
        invoice = Invoice.objects.get(fulfilment=shipment)
        fl = FulfilmentLine.objects.get(fulfilment=shipment)
        backorders.cancel_repriced(fl.pk, by=world["owner"], retailer_id=world["shop"].pk)
        [note] = CreditNote.objects.all()
        line = OrderLine.objects.get(order=order)
    assert (note.kind, note.grand_total) == ("CANCELLATION", invoice.grand_total)
    assert (line.qty_invoiced, line.qty_cancelled) == (0, 4)
    check_ledger(world["t"])
    check_order_invariants(world["t"])
