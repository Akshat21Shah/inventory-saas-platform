"""Free goods on invoices, credit notes, documents and reports (ADR-056 items 10-11): a ₹0 line
with its HSN and quantity, marked free; a shipment of free goods alone owes nothing; free units
come back at ₹0; the sales report shows the free quantity and the margin counts their cost."""

from decimal import Decimal as D

import pytest
from django.core.cache import cache
from django.template.loader import render_to_string

from apps.accounts.tests.factories import make_staff_in
from apps.billing import credit_notes, documents
from apps.billing.credit_notes import ReturnLine
from apps.billing.models import CreditNote, Invoice
from apps.catalog.models import Product
from apps.compliance.document import invoice_document
from apps.inventory import receipts
from apps.inventory.models import StockLevel
from apps.inventory.tests.helpers import make_product
from apps.ledger.models import LedgerEntry
from apps.ledger.tests.helpers import check_ledger
from apps.orders import backorders, fulfilment, transitions
from apps.orders.fulfilment import Transport
from apps.orders.models import Fulfilment, OrderLine
from apps.orders.tests.helpers import (
    add_stock,
    check_order_invariants,
    make_shop,
    place,
    settings,
    staff_client,
)
from apps.platform.models import FeatureFlag, TenantFeature
from apps.platform.selectors import invalidate_tenant_features
from apps.pricing.models import FreeGoodsScheme
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
NO_TRANSPORT = Transport("", "", "")


@pytest.fixture
def world(tenant_a):
    cache.clear()
    with tenant_context(tenant_a.pk):
        TenantFeature.objects.update_or_create(
            flag=FeatureFlag.objects.get(code="free_goods"), defaults={"enabled": True}
        )
    invalidate_tenant_features(tenant_a.pk)
    soap = make_product(tenant_a, "SOAP", base_price=D("40"), cost_price=D("30"))
    towel = make_product(tenant_a, "TOWEL", base_price=D("90"), cost_price=D("25"))
    add_stock(tenant_a, soap, "100")
    with tenant_context(tenant_a.pk):
        FreeGoodsScheme.objects.create(
            name="Towel offer",
            buy_product=soap,
            buy_qty=D("10"),
            free_product=towel,
            free_qty=D("1"),
            audience_type="ALL",
        )
    yield {
        "t": tenant_a,
        "owner": make_staff_in(tenant_a, "OWNER"),
        "shop": make_shop(tenant_a, "9876500095", shop_name="Sai Kirana"),
        "soap": soap,
        "towel": towel,
    }
    cache.clear()


def ship(world, order):
    with tenant_context(world["t"].pk):
        transitions.accept_order(order.pk, by=world["owner"])
        shipment = Fulfilment.objects.filter(order=order).order_by("created_at")[0]
        fulfilment.pack(shipment.pk, {}, by=world["owner"])
        fulfilment.dispatch(shipment.pk, NO_TRANSPORT, by=world["owner"])
        return Invoice.objects.get(fulfilment=shipment)


def test_the_invoice_shows_free_goods_at_zero_with_their_cost(world):
    add_stock(world["t"], world["towel"], "10")
    order = place(world["t"], world["shop"], (world["soap"], "20"))
    invoice = ship(world, order)
    with tenant_context(world["t"].pk):
        paid, free = invoice.lines.order_by("line_no")
        html = render_to_string(
            "billing/invoice.html", documents.invoice_context(invoice, documents.COPIES)
        )
        document = invoice_document(invoice)
    assert (free.is_free, free.scheme_name, free.quantity) == (True, "Towel offer", D("2"))
    assert (free.taxable_value, free.line_total, free.cgst_amount) == (0, 0, 0)
    assert (free.hsn_code, free.gst_rate, free.unit_cost) == ("1905", D("5"), D("25"))
    assert paid.is_free is False and invoice.grand_total == D("840.00")  # 20 x 40 + 5%
    assert "Free (Towel offer)" in html
    assert [line["is_free"] for line in document["lines"]] == [False, True]
    detail = staff_client(world["t"]).get(f"/api/v1/invoices/{invoice.pk}/").json()
    assert [(x["is_free"], x["scheme_name"]) for x in detail["lines"]] == [
        (False, ""),
        (True, "Towel offer"),
    ]
    check_ledger(world["t"])


def test_free_goods_sent_on_their_own_owe_nothing(world):
    order = place(world["t"], world["shop"], (world["soap"], "10"))  # no towels yet: 1 waits
    ship(world, order)
    with tenant_context(world["t"].pk):
        receipts.create_and_post(
            receipts.ReceiptInput(lines=[receipts.LineInput(world["towel"].pk, D("5"))]),
            by=world["owner"],
        )
        free = OrderLine.objects.get(order=order, free_of_line__isnull=False)
        [proposal] = free.allocations.all()
        [shipment] = backorders.confirm([proposal.pk], by=world["owner"])
        fulfilment.pack(shipment.pk, {}, by=world["owner"])
        fulfilment.dispatch(shipment.pk, NO_TRANSPORT, by=world["owner"])
        invoice = Invoice.objects.get(fulfilment=shipment)
        entries = LedgerEntry.objects.filter(reference_id=invoice.pk).count()
    assert (invoice.grand_total, invoice.balance_due, entries) == (0, 0, 0)
    check_ledger(world["t"])
    check_order_invariants(world["t"])


def test_free_goods_come_back_at_zero(world):
    add_stock(world["t"], world["towel"], "10")
    order = place(world["t"], world["shop"], (world["soap"], "20"))
    invoice = ship(world, order)
    with tenant_context(world["t"].pk):
        paid, free = invoice.lines.order_by("line_no")
        both = credit_notes.issue_return(
            invoice.pk,
            [ReturnLine(paid.pk, D("10")), ReturnLine(free.pk, D("1"))],
            reason="DAMAGED",
            by=world["owner"],
        )
        alone = credit_notes.issue_return(
            invoice.pk, [ReturnLine(free.pk, D("1"))], reason="DAMAGED", by=world["owner"]
        )
        towels = StockLevel.objects.get(product=world["towel"]).quantity_on_hand
        alone_entries = LedgerEntry.objects.filter(reference_id=alone.pk).count()
        html = render_to_string("billing/credit_note.html", documents.credit_note_context(both))
        lines = [(x.invoice_line.is_free, x.line_total) for x in both.lines.order_by("line_no")]
    assert both.grand_total == D("420.00")  # the soap only
    assert lines == [(False, D("420.00")), (True, D("0.00"))]
    assert (alone.grand_total, alone_entries) == (0, 0)
    assert towels == D("10")  # both free towels back in stock
    assert "Free (Towel offer)" in html
    check_ledger(world["t"])


def test_short_packed_free_goods_on_an_invoiced_shipment(world):
    settings(world["t"], invoicing__timing="ON_ACCEPTANCE", backorders__enabled=False)
    add_stock(world["t"], world["towel"], "10")
    order = place(world["t"], world["shop"], (world["soap"], "20"))
    with tenant_context(world["t"].pk):
        transitions.accept_order(order.pk, by=world["owner"])
        shipment = Fulfilment.objects.get(order=order)
        free_fl = shipment.lines.get(order_line__free_of_line__isnull=False)
        fulfilment.pack(shipment.pk, {free_fl.pk: D("1")}, by=world["owner"])
        [note] = CreditNote.objects.all()
    assert (note.kind, note.grand_total) == ("SHORT_SUPPLY", 0)
    check_ledger(world["t"])
    check_order_invariants(world["t"])


def test_sales_by_product_shows_the_free_quantity_and_the_margin_counts_its_cost(world):
    add_stock(world["t"], world["towel"], "10")
    ship(world, place(world["t"], world["shop"], (world["soap"], "20")))
    owner = staff_client(world["t"])
    report = owner.get("/api/v1/reports/sales_by_product/").json()
    rows = {r["code"]: r for r in report["rows"]}
    assert (rows["TOWEL"]["qty"], rows["TOWEL"]["free_qty"], rows["TOWEL"]["total"]) == (
        "2.000",
        "2.000",
        "0.00",
    )
    assert rows["SOAP"]["free_qty"] == "0.000"
    assert rows["TOWEL"]["margin"] == "-50.00"  # two towels at 25 each, sold for nothing
    margin = owner.get("/api/v1/reports/margin_own_vs_traded/").json()["totals"]
    assert margin["cost"] == "650.00"  # 20 soaps at 30 + 2 towels at 25
    with tenant_context(world["t"].pk):
        assert Product.objects.filter(code="TOWEL").exists()
