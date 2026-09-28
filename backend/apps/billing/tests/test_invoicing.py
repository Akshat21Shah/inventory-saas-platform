"""Issuing tax invoices (PLAN §4.4, ADR-007/009/010/011/022/046): at dispatch for the packed
quantity (default) or at acceptance and backorder allocation; the invoice-date rate with a
warning; the order's price basis; rounding in force now, saved; ledger debit; advances applied."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.accounts.tests.factories import make_staff_in
from apps.billing import invoicing
from apps.billing.models import Invoice
from apps.inventory import receipts
from apps.inventory.tests.helpers import make_product
from apps.ledger import services as ledger
from apps.ledger.models import Allocation, LedgerEntry, RetailerAccount
from apps.ledger.tests.helpers import check_ledger
from apps.orders import backorders, fulfilment, transitions
from apps.orders.fulfilment import Transport
from apps.orders.models import Fulfilment, FulfilmentLine, OrderLine
from apps.orders.tests.helpers import (
    add_address,
    add_stock,
    check_order_invariants,
    make_shop,
    place,
    settings,
)
from common.dates import today_ist
from common.models import OutboxEvent
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
NO_TRANSPORT = Transport("", "", "")


@pytest.fixture
def world(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    a = make_product(tenant_a, "A", base_price=D("123.45"))
    b = make_product(tenant_a, "B", base_price=D("50.00"))
    add_stock(tenant_a, a, "20")
    return {"t": tenant_a, "owner": owner, "shop": shop, "a": a, "b": b}


def _accept(world, order):
    with tenant_context(world["t"].pk):
        transitions.accept_order(order.pk, by=world["owner"])
        return Fulfilment.objects.filter(order=order).order_by("created_at").first()


def _ship(world, shipment, packed=None):
    with tenant_context(world["t"].pk):
        lines = (
            {}
            if packed is None
            else {FulfilmentLine.objects.get(fulfilment=shipment).pk: D(packed)}
        )
        fulfilment.pack(shipment.pk, lines, by=world["owner"])
        fulfilment.dispatch(shipment.pk, NO_TRANSPORT, by=world["owner"])
        return Invoice.objects.filter(fulfilment=shipment).first()


def _account(world):
    with tenant_context(world["t"].pk):
        return RetailerAccount.objects.get(retailer=world["shop"])


def test_at_dispatch_for_the_packed_quantity(world):
    order = place(world["t"], world["shop"], (world["a"], "10"))
    shipment = _accept(world, order)
    with tenant_context(world["t"].pk):
        assert not Invoice.objects.exists()  # nothing at acceptance by default
    invoice = _ship(world, shipment, packed="8")
    assert invoice is not None
    year = today_ist().year if today_ist().month >= 4 else today_ist().year - 1
    assert invoice.number == f"INV/{str(year)[-2:]}-{str(year + 1)[-2:]}/000001"
    assert (invoice.issued_trigger, invoice.invoice_date) == ("ON_DISPATCH", today_ist())
    assert invoice.due_date == date.fromordinal(today_ist().toordinal() + 30)
    with tenant_context(world["t"].pk):
        [line] = invoice.lines.all()
        assert (line.quantity, line.taxable_value) == (D("8.000"), D("987.60"))
        # 8 x 123.45 = 987.60; 5% intra: CGST = SGST = 24.69; total 1,036.98 → ₹1,037.00
        assert (line.cgst_amount, line.sgst_amount, line.line_total) == (
            D("24.69"),
            D("24.69"),
            D("1036.98"),
        )
        assert (invoice.grand_total, invoice.round_off) == (D("1037.00"), D("0.02"))
        assert invoice.amount_in_words == "Rupees One Thousand Thirty Seven Only"
        assert OrderLine.objects.get(order=order).qty_invoiced == 8
        entry = LedgerEntry.objects.get(entry_type="INVOICE")
        assert (entry.debit, entry.reference_number) == (D("1037.00"), invoice.number)
        assert OutboxEvent.objects.filter(event_type="invoice.issued").count() == 1
        assert invoice.seller["gstin"] == world["t"].gstin
        assert invoice.buyer["name"] == world["shop"].shop_name
        assert invoice.settings_snapshot == {
            "tax.component_rounding": "HALF_UP",
            "invoicing.round_to_rupee": True,
            "invoicing.round_off_method": "NEAREST",
        }
        again = invoicing.issue_invoice_for_fulfilment(shipment, trigger="ON_DISPATCH", by=None)
    assert again == invoice  # one invoice per shipment
    assert _account(world).balance == D("1037.00")
    check_ledger(world["t"])
    check_order_invariants(world["t"])


def test_at_acceptance_and_at_backorder_allocation(world):
    settings(world["t"], invoicing__timing="ON_ACCEPTANCE")
    order = place(world["t"], world["shop"], (world["a"], "2"), (world["b"], "3"))
    first = _accept(world, order)
    with tenant_context(world["t"].pk):
        [invoice] = Invoice.objects.all()
        assert (invoice.issued_trigger, invoice.fulfilment_id) == ("ON_ACCEPTANCE", first.pk)
        assert [line.product_code for line in invoice.lines.all()] == ["A"]
        receipts.create_and_post(
            receipts.ReceiptInput(lines=[receipts.LineInput(world["b"].pk, D("3"))]),
            by=world["owner"],
        )
        [proposal] = OrderLine.objects.get(order=order, product=world["b"]).allocations.all()
        [second] = backorders.confirm([proposal.pk], by=world["owner"])
        later = Invoice.objects.get(fulfilment=second)
    assert later.issued_trigger == "ON_ALLOCATION"
    # Dispatch doesn't invoice again in this mode.
    _ship(world, first)
    with tenant_context(world["t"].pk):
        assert Invoice.objects.count() == 2
    check_ledger(world["t"])
    check_order_invariants(world["t"])


def test_the_rate_on_the_invoice_date_with_a_warning(world):
    order = place(world["t"], world["shop"], (world["a"], "10"))
    with tenant_context(world["t"].pk):
        OrderLine.objects.filter(order=order).update(gst_rate=D("12"))  # ordered at 12% (Ex 11)
    invoice = _ship(world, _accept(world, order))
    with tenant_context(world["t"].pk):
        [line] = invoice.lines.all()
    assert (line.gst_rate, line.order_rate, line.rate_differs_from_order) == (
        D("5.000"),
        D("12.000"),
        True,
    )
    assert invoice.rate_differs_from_order is True


def test_prices_follow_the_orders_basis_and_rounding_the_current_settings(world):
    settings(world["t"], tax__prices_include_gst=True)
    order = place(world["t"], world["shop"], (world["a"], "1"))
    settings(world["t"], tax__prices_include_gst=False, invoicing__round_off_method="DOWN")
    invoice = _ship(world, _accept(world, order))
    with tenant_context(world["t"].pk):
        [line] = invoice.lines.all()
    # ₹123.45 including 5%: taxable 117.57, CGST = SGST = 2.94, total 123.45 → down to ₹123
    assert invoice.prices_include_tax is True
    assert (line.taxable_value, line.cgst_amount, line.line_total) == (
        D("117.57"),
        D("2.94"),
        D("123.45"),
    )
    assert (invoice.grand_total, invoice.round_off) == (D("123.00"), D("-0.45"))
    assert invoice.settings_snapshot["invoicing.round_off_method"] == "DOWN"


def test_an_advance_is_applied_to_the_new_invoice(world):
    with tenant_context(world["t"].pk):
        ledger.post_adjustment(
            world["shop"].pk,
            "CREDIT",
            D("500.00"),
            on=today_ist(),
            narration="Advance",
            by=world["owner"],
        )
    order = place(world["t"], world["shop"], (world["a"], "10"))
    invoice = _ship(world, _accept(world, order))
    with tenant_context(world["t"].pk):
        invoice.refresh_from_db()
        allocation = Allocation.objects.get()
    assert (invoice.amount_credited, invoice.balance_due, invoice.payment_status) == (
        D("500.00"),
        invoice.grand_total - D("500.00"),
        "PARTIAL",
    )
    assert allocation.automatic is True
    assert _account(world).balance == invoice.grand_total - D("500.00")
    check_ledger(world["t"])


def test_another_state_is_charged_igst(world):
    add_address(world["t"], world["shop"], "24")  # Gujarat, the default shipping address
    order = place(world["t"], world["shop"], (world["a"], "10"))
    invoice = _ship(world, _accept(world, order))
    with tenant_context(world["t"].pk):
        [line] = invoice.lines.all()
    assert (invoice.supply_type, invoice.place_of_supply_id) == ("INTER", "24")
    assert (line.igst_amount, line.cgst_amount) == (D("61.73"), D("0.00"))


def test_a_repriced_backorder_is_invoiced_at_todays_price_and_discount(world):
    settings(world["t"], backorders__billing_price="CURRENT")
    order = place(world["t"], world["shop"], (world["b"], "4"))
    _accept(world, order)
    with tenant_context(world["t"].pk):
        world["b"].base_price = D("60.00")
        world["b"].save(update_fields=["base_price"])
        receipts.create_and_post(
            receipts.ReceiptInput(lines=[receipts.LineInput(world["b"].pk, D("4"))]),
            by=world["owner"],
        )
        [proposal] = OrderLine.objects.get(order=order).allocations.all()
        [shipment] = backorders.confirm([proposal.pk], by=world["owner"])
    invoice = _ship(world, shipment)
    with tenant_context(world["t"].pk):
        [line] = invoice.lines.all()
    assert (line.unit_price, line.taxable_value) == (D("60.00"), D("240.00"))


def test_nothing_packed_means_no_invoice(world):
    order = place(world["t"], world["shop"], (world["a"], "2"))
    shipment = _accept(world, order)
    with tenant_context(world["t"].pk):
        line = FulfilmentLine.objects.get(fulfilment=shipment)
        fulfilment.pack(shipment.pk, {line.pk: D("0")}, by=world["owner"])
        shipment.refresh_from_db()
        assert shipment.status == "CANCELLED"
        assert not Invoice.objects.exists() and not LedgerEntry.objects.exists()


def test_phase4_shipments_are_invoiced_later_by_the_dev_command(world, monkeypatch, settings):
    from django.core.management import CommandError, call_command

    order = place(world["t"], world["shop"], (world["a"], "2"))
    shipment = _accept(world, order)
    monkeypatch.setattr(invoicing, "timing", lambda order: "PHASE_4")  # no invoices yet
    assert _ship(world, shipment) is None
    monkeypatch.undo()
    settings.DEBUG = True
    call_command("invoice_phase4_shipments")
    call_command("invoice_phase4_shipments")  # a second run finds nothing more
    with tenant_context(world["t"].pk):
        [invoice] = Invoice.objects.all()
    assert (invoice.issued_trigger, invoice.invoice_date) == ("AFTER_DISPATCH", today_ist())
    check_ledger(world["t"])
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("invoice_phase4_shipments")
