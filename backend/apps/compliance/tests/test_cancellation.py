"""Cancelling an IRN (ADR-049 item 7): within the window only, with a reason; re-issuing a
corrected invoice with a new number for the same shipment (the default) or taking the goods back
(to backorder, or cancelled); the ledger reversed and freed money moved on, the books still
balancing; the portal asked first (retried when down, a refusal leaving the invoice as it was, an
earlier lost answer counted as done); the shop told; and the API's rules."""

from datetime import datetime, timedelta
from decimal import Decimal as D
from typing import Any

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.billing import credit_notes, documents
from apps.billing.credit_notes import ReturnLine
from apps.billing.models import Invoice
from apps.compliance.adapters.mock import MockGspClient, _key
from apps.compliance.models import EInvoiceRecord
from apps.compliance.tests.helpers import record_of, sell, sweep
from apps.inventory.models import StockLevel, StockMovement
from apps.ledger.models import LedgerEntry
from apps.ledger.tests.helpers import check_ledger
from apps.notifications.models import Notification
from apps.orders.models import Fulfilment, Order, OrderLine
from apps.orders.tests.helpers import settings
from apps.payments import services as payments
from apps.payments.services import PaymentInput
from common.dates import today_ist
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
S = EInvoiceRecord.Status
API = "/api/v1"


def cancel(world: dict[str, Any], invoice: Invoice, **body: Any) -> Any:
    rec = record_of(world, invoice)
    with world["run"]():
        return world["staff"].post(
            f"{API}/einvoices/{rec.pk}/cancel/",
            {"reason_code": "DATA_ENTRY_MISTAKE", **body},
            format="json",
        )


def fresh(world: dict[str, Any], invoice: Invoice) -> Invoice:
    with tenant_context(world["t"].pk):
        found: Invoice = Invoice.objects.get(pk=invoice.pk)
        return found


def on_hand(world: dict[str, Any]) -> D:
    with tenant_context(world["t"].pk):
        return D(StockLevel.objects.get(product=world["product"]).quantity_on_hand)


def shop_told(world: dict[str, Any]) -> list[Notification]:
    with tenant_context(world["t"].pk):
        return list(Notification.objects.filter(event_code="invoice.cancelled", channel="IN_APP"))


@covers("einvoice-cancel")
def test_reissuing_replaces_the_invoice_with_a_new_number(world):
    invoice = sell(world, qty="2")
    with world["run"](), tenant_context(world["t"].pk):
        payments.record_payment(
            PaymentInput(world["b2b"].pk, D("10000.00"), "CASH", today_ist()), by=world["owner"]
        )
    answer = cancel(world, invoice, remarks="Wrong GSTIN")
    assert answer.status_code == 200
    assert answer.json()["status"] == "CANCELLING"  # the portal is asked after this commits
    rec = record_of(world, invoice)
    assert (rec.status, rec.cancel_outcome, rec.cancel_reason_code) == (
        S.CANCELLED,
        "REISSUE",
        "DATA_ENTRY_MISTAKE",
    )
    old = fresh(world, invoice)
    assert (old.status, old.einvoice_status, old.balance_due) == ("CANCELLED", "CANCELLED", 0)
    new = rec.reissued_invoice
    assert new is not None and new.number != invoice.number
    with tenant_context(world["t"].pk):
        new = Invoice.objects.get(pk=new.pk)
        assert new.fulfilment_id == invoice.fulfilment_id and new.status == "ISSUED"
        assert (new.grand_total, new.amount_paid) == (invoice.grand_total, D("10000.00"))
        assert EInvoiceRecord.objects.get(invoice=new).status == S.GENERATED  # its own IRN
        reversal = LedgerEntry.objects.get(entry_type="INVOICE_CANCELLED")
        assert (reversal.credit, reversal.reference_number) == (invoice.grand_total, invoice.number)
        line = OrderLine.objects.get(order_id=invoice.order_id)
        assert line.qty_invoiced == 2  # un-invoiced, then invoiced again
        printed = documents.invoice_context(old, documents.COPIES[:1])
    assert printed["reissued"] == new.number
    check_ledger(world["t"])
    [told] = shop_told(world)
    assert told.body == f"Your bill {invoice.number} was cancelled. Bill {new.number} replaces it."
    assert told.data["path"] == f"/shop/invoices/{new.pk}"  # opens the new bill
    with tenant_context(world["t"].pk):
        emailed = Notification.objects.get(event_code="invoice.cancelled", channel="EMAIL")
    assert f"Bill {new.number} replaces it." in emailed.body
    assert f"/shop/invoices/{new.pk}" in emailed.body
    actions = set(AuditLog.objects.values_list("action", flat=True))
    assert {"einvoice.cancel_requested", "einvoice.cancelled"} <= actions


def test_taking_the_goods_back_to_wait_on_backorder(world):
    invoice = sell(world, qty="2")
    before = on_hand(world)
    cancel(world, invoice, reason_code="ORDER_CANCELLED", outcome="TAKE_BACK", to_backorder=True)
    rec = record_of(world, invoice)
    assert (rec.status, rec.reissued_invoice) == (S.CANCELLED, None)
    assert on_hand(world) == before + 2
    with tenant_context(world["t"].pk):
        shipment = Fulfilment.objects.get(pk=invoice.fulfilment_id)
        line = OrderLine.objects.get(order_id=invoice.order_id)
        returned = StockMovement.objects.filter(movement_type="RETURN", reference_id=shipment.pk)
        assert returned.count() == 1
    assert shipment.status == "CANCELLED"
    # Waiting again; the returned stock is at once held for it (a backorder proposal).
    assert (line.qty_backordered + line.qty_reserved, line.qty_cancelled) == (2, 0)
    assert (line.qty_allocated, line.qty_dispatched, line.qty_invoiced) == (0, 0, 0)
    assert fresh(world, invoice).status == "CANCELLED"
    check_ledger(world["t"])
    [told] = shop_told(world)
    assert told.body.endswith("The goods were taken back.")


def test_taking_the_goods_back_and_cancelling_the_quantities(world):
    invoice = sell(world, qty="2")
    with tenant_context(world["t"].pk):
        Fulfilment.objects.filter(pk=invoice.fulfilment_id).update(status="DELIVERED")
        OrderLine.objects.filter(order_id=invoice.order_id).update(qty_delivered=2)
    cancel(world, invoice, reason_code="OTHER", remarks="Refused", outcome="TAKE_BACK")
    with tenant_context(world["t"].pk):
        line = OrderLine.objects.get(order_id=invoice.order_id)
        order = Order.objects.get(pk=invoice.order_id)
    assert (line.qty_cancelled, line.qty_delivered, line.qty_allocated) == (2, 0, 0)
    assert order.status == "CANCELLED"
    check_ledger(world["t"])


def test_only_within_the_window_and_without_credit_notes(world):
    invoice = sell(world, qty="2")
    with tenant_context(world["t"].pk):
        EInvoiceRecord.objects.filter(invoice=invoice).update(
            ack_date=timezone.now() - timedelta(hours=25)
        )
    late = cancel(world, invoice)
    assert late.status_code == 400
    assert "credit note" in late.json()["error"]["details"]["fields"]["document"][0]
    shown = world["staff"].get(f"{API}/invoices/{invoice.pk}/").json()["einvoice"]
    assert shown["can_cancel"] is False

    second = sell(world, qty="2")
    with world["run"](), tenant_context(world["t"].pk):
        credit_notes.issue_return(
            second.pk,
            [ReturnLine(second.lines.get().pk, D("1"))],
            reason="DAMAGED",
            note="",
            by=world["owner"],
        )
    noted = cancel(world, second)
    with tenant_context(world["t"].pk):
        number = second.credit_notes.get().number
    message = (
        f"This invoice's IRN can't be cancelled because credit note {number} was issued "
        "against it. Correct the invoice with another credit note instead."
    )
    assert noted.json()["error"]["details"]["fields"]["document"] == [message]
    shown = world["staff"].get(f"{API}/invoices/{second.pk}/").json()["einvoice"]
    assert (shown["can_cancel"], shown["cancel_blocked"]["reason"]) == (False, "CREDIT_NOTES")
    assert shown["cancel_blocked"]["message"] == message
    with tenant_context(world["t"].pk):
        note_record = EInvoiceRecord.objects.get(document_type="CREDIT_NOTE")
    with world["run"]():
        refused = world["staff"].post(
            f"{API}/einvoices/{note_record.pk}/cancel/",
            {"reason_code": "DUPLICATE"},
            format="json",
        )
    assert refused.status_code == 400
    assert record_of(world, second).status == S.GENERATED


def test_the_request_is_checked(world):
    settings(world["t"], backorders__enabled=False)
    invoice = sell(world)
    other = cancel(world, invoice, reason_code="OTHER")
    assert other.json()["error"]["details"]["fields"] == {"remarks": ["Say why."]}
    wait = cancel(world, invoice, outcome="TAKE_BACK", to_backorder=True)
    assert wait.json()["error"]["details"]["fields"] == {
        "to_backorder": ["This order doesn't take backorders: cancel the quantities."]
    }
    assert record_of(world, invoice).status == S.GENERATED


def test_the_portal_down_is_tried_again(world):
    invoice = sell(world)
    MockGspClient.script("PORTAL_DOWN")
    cancel(world, invoice)
    rec = record_of(world, invoice)
    assert (rec.status, rec.cancel_error) == (
        S.CANCELLING,
        "The e-invoice portal is not available.",
    )
    assert fresh(world, invoice).status == "ISSUED"  # nothing changes until the portal agrees
    again = cancel(world, invoice)  # a second tap: still the same request
    assert again.json()["status"] == "CANCELLING"
    sweep(world)
    assert record_of(world, invoice).status == S.CANCELLED


def test_a_refusal_leaves_the_invoice_as_it_was(world):
    invoice = sell(world)
    rec = record_of(world, invoice)
    stored = cache.get(_key(rec.irn))
    old = datetime.fromisoformat(stored["ack_date"]) - timedelta(hours=30)
    cache.set(_key(rec.irn), {**stored, "ack_date": old.isoformat()}, None)  # the portal's clock
    cancel(world, invoice)
    rec = record_of(world, invoice)
    assert (rec.status, rec.cancel_error) == (
        S.GENERATED,
        "The time allowed for cancelling has passed.",
    )
    assert fresh(world, invoice).status == "ISSUED"
    assert AuditLog.objects.filter(action="einvoice.cancel_refused").count() == 1
    check_ledger(world["t"])


def test_an_answer_lost_earlier_counts_as_cancelled(world):
    invoice = sell(world)
    rec = record_of(world, invoice)
    MockGspClient().cancel_irn(rec.irn, "2", "", _creds(world))  # cancelled, but we never heard
    cancel(world, invoice)
    assert record_of(world, invoice).status == S.CANCELLED
    assert fresh(world, invoice).status == "CANCELLED"


def _creds(world: dict[str, Any]) -> Any:
    from apps.compliance import credentials

    with tenant_context(world["t"].pk):
        return credentials.for_use(credentials.ready())


def test_who_may_cancel(world):
    invoice = sell(world)
    rec = record_of(world, invoice)
    url = f"{API}/einvoices/{rec.pk}/cancel/"
    body = {"reason_code": "DUPLICATE"}
    assert world["sales"].post(url, body, format="json").status_code == 403
    no_module = world["other"].post(url, body, format="json")
    assert no_module.json()["error"]["code"] == "MODULE_NOT_ENABLED"
    from apps.compliance.tests.conftest import switch_on

    switch_on(world["tb"], "einvoice")
    assert world["other"].post(url, body, format="json").status_code == 404
    assert record_of(world, invoice).status == S.GENERATED


def test_the_bill_cancelled_whatsapp_template_is_optional():
    from apps.notifications.catalog import in_first_submission

    assert not in_first_submission("invoice.cancelled", "SHOP")  # an optional module's event
    assert in_first_submission("invoice.issued", "SHOP")


@covers("einvoice-reissue-preview")
def test_a_reissue_uses_the_shop_now_but_the_original_prices_and_rates(world, monkeypatch):
    from datetime import timedelta as days

    from apps.catalog.models import Product, ProductTaxRate
    from apps.platform.tests.factories import make_gstin
    from apps.retailers.models import Retailer
    from common.dates import today_ist

    with tenant_context(world["t"].pk):
        Product.objects.filter(pk=world["product"].pk).update(cost_price=D("21000"))
    invoice = sell(world, qty="2")  # ₹30,000 at 5%, to Karnataka (IGST); cost ₹21,000
    corrected = make_gstin(8102, "29")
    with tenant_context(world["t"].pk):
        Retailer.objects.filter(pk=world["b2b"].pk).update(
            shop_name="Kaveri Traders & Sons", gstin=corrected, pan=corrected[2:12]
        )
        Product.objects.filter(pk=world["product"].pk).update(cost_price=D("25000"))  # since
        tomorrow = today_ist() + days(days=1)
        ProductTaxRate.objects.create(  # a rate change from tomorrow; the preview looks then
            product=world["product"], gst_rate=D("18"), effective_from=tomorrow
        )
    monkeypatch.setattr("apps.compliance.cancellation.today_ist", lambda: tomorrow)
    rec = record_of(world, invoice)
    preview = world["staff"].get(f"{API}/einvoices/{rec.pk}/reissue-preview/").json()
    assert preview["buyer"] == {
        "name": "Kaveri Traders & Sons",
        "gstin": corrected,
        "state_code": "29",
    }
    assert preview["buyer_changed"] is True
    assert (preview["supply_type"], preview["supply_type_before"]) == ("INTER", "INTER")
    assert preview["rate_changes"] == [
        {
            "line_no": 1,
            "description": world["product"].name,
            "hsn_code": "8471",
            "original_rate": "5.000",
            "today_rate": "18.000",
        }
    ]
    unconfirmed = cancel(world, invoice)
    assert "confirm_rate_changes" in unconfirmed.json()["error"]["details"]["fields"]
    cancel(world, invoice, confirm_rate_changes=True)
    new = record_of(world, invoice).reissued_invoice
    assert new is not None
    with tenant_context(world["t"].pk):
        new = Invoice.objects.get(pk=new.pk)
        [line] = new.lines.all()
    assert (new.buyer["name"], new.buyer["gstin"]) == ("Kaveri Traders & Sons", corrected)
    assert (line.gst_rate, line.unit_price, new.grand_total, line.unit_cost) == (
        D("5.000"),
        D("30000.00"),
        invoice.grand_total,
        D("21000"),  # the same supply keeps its cost (ADR-050), not today's
    )
    other = world["other"].get(f"{API}/einvoices/{rec.pk}/reissue-preview/")
    assert other.status_code in (403, 404)
