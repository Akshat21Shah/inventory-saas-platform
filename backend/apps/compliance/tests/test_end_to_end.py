"""Phase 7 end to end with the mocks (ADR-049): e-invoicing, e-way bills and online payments on
together, for a registered shop in another state.

1. An order is dispatched: the bill gets its IRN and signed QR, the consignment its e-way bill,
   the PDF shows both, and the shop's WhatsApp bill goes out once.
2. The shop pays the bill online; only the gateway's signed webhook records it; the receipt and
   the payment message follow.
3. A return: the credit note gets its own IRN.
4. A second bill is corrected: its e-way bill is cancelled, then its IRN, and a corrected bill is
   re-issued with a new number and IRN.
Throughout, the books balance; another distributor with the modules off sees none of it.
"""

from decimal import Decimal as D
from uuid import uuid4

import pytest
from django.core import mail

from apps.billing import credit_notes
from apps.billing.credit_notes import ReturnLine
from apps.billing.models import Invoice
from apps.compliance.models import EInvoiceRecord, EWayBill
from apps.compliance.tests.conftest import switch_on
from apps.compliance.tests.helpers import record_of
from apps.ledger.tests.helpers import check_ledger
from apps.notifications.adapters.whatsapp import MockWhatsAppClient
from apps.orders import fulfilment, transitions
from apps.orders.models import Fulfilment
from apps.orders.tests.helpers import add_stock, place, shop_client
from apps.payments.gateway.mock import MockGateway
from apps.payments.models import Payment
from apps.payments.tests.conftest import KEYS, connect
from apps.retailers.models import RetailerAddress
from common.storage import get_storage
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
API = "/api/v1"


def dispatch(world, qty: str) -> Invoice:
    with world["run"]():
        order = place(world["t"], world["b2b"], (world["product"], qty))
    with world["run"](), tenant_context(world["t"].pk):
        transitions.accept_order(order.pk, by=world["owner"])
        shipment = Fulfilment.objects.get(order=order)
        fulfilment.pack(shipment.pk, {}, by=world["owner"])
        fulfilment.dispatch(
            shipment.pk, fulfilment.Transport("MH12AB1234", "Speedy", "LR-9"), by=world["owner"]
        )
    with tenant_context(world["t"].pk):
        found: Invoice = Invoice.objects.get(fulfilment=shipment, status="ISSUED")
        return found


def sent(template: str) -> int:
    return sum(m.message.template == template for m in MockWhatsAppClient.outbox)


def test_a_registered_shop_in_another_state_end_to_end(world):
    t = world["t"]
    switch_on(t, "ewaybill")
    connect(t)
    add_stock(t, world["product"], "20")
    with tenant_context(t.pk):
        RetailerAddress.objects.filter(retailer=world["b2b"]).update(distance_km=850)

    # 1. Dispatch: IRN, QR, e-way bill, the PDF, one WhatsApp bill.
    bill = dispatch(world, "2")  # ₹63,000 with IGST
    irn = record_of(world, bill)
    with tenant_context(t.pk):
        ewb = EWayBill.objects.get(invoice=bill)
        bill = Invoice.objects.get(pk=bill.pk)
        printed = get_storage().get(bill.pdf_key).decode()
    assert (irn.status, bill.einvoice_status, bill.irn) == ("GENERATED", "GENERATED", irn.irn)
    assert ewb.status == "GENERATED" and ewb.distance_km == 850
    assert irn.irn in printed and ewb.ewb_number in printed and "e-invoice QR code" in printed
    assert sent("b2b_invoice_issued") == 1
    assert any(bill.number in m.subject for m in mail.outbox)

    # 2. The shop pays online: counted only when the signed webhook arrives.
    shop = shop_client(t, world["b2b"])
    started = shop.post(
        f"{API}/shop/payments/checkout/",
        {"purpose": "INVOICE", "invoice_id": str(bill.pk)},
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"k{uuid4().hex}",
    ).json()
    assert started["amount"] == "63000.00"
    payload, headers = MockGateway.simulate(KEYS, started["checkout"]["order_id"])
    from rest_framework.test import APIClient

    with world["run"]():
        answer = APIClient().post(
            f"{API}/webhooks/payments/mock/{t.webhook_token}/",
            data=payload,
            content_type="application/json",
            HTTP_X_MOCK_SIGNATURE=headers["X-Mock-Signature"],
            HTTP_X_MOCK_EVENT_ID=headers["X-Mock-Event-Id"],
        )
    assert answer.content == b"captured"
    with tenant_context(t.pk):
        payment = Payment.objects.get(mode="ONLINE")
        assert Invoice.objects.get(pk=bill.pk).payment_status == "PAID"
    assert payment.amount == D("63000.00") and sent("b2b_payment_received") == 1

    # 3. A return: the credit note's own IRN.
    with world["run"](), tenant_context(t.pk):
        note = credit_notes.issue_return(
            bill.pk,
            [ReturnLine(bill.lines.get().pk, D("1"))],
            reason="DAMAGED",
            note="",
            by=world["owner"],
        )
    with tenant_context(t.pk):
        note_irn = EInvoiceRecord.objects.get(credit_note=note)
    assert note_irn.status == "GENERATED" and note_irn.irn != irn.irn

    # 4. A second bill corrected: the e-way bill first, then the IRN; a new bill re-issued.
    second = dispatch(world, "2")
    staff = world["staff"]
    with tenant_context(t.pk):
        second_ewb = EWayBill.objects.get(invoice=second)
    with world["run"]():
        staff.post(
            f"{API}/ewaybills/{second_ewb.pk}/cancel/",
            {"reason_code": "DATA_ENTRY_MISTAKE"},
            format="json",
        )
    with tenant_context(t.pk):
        assert EWayBill.objects.get(pk=second_ewb.pk).status == "CANCELLED"
    with world["run"]():
        staff.post(
            f"{API}/einvoices/{record_of(world, second).pk}/cancel/",
            {"reason_code": "DATA_ENTRY_MISTAKE", "remarks": "Wrong rate"},
            format="json",
        )
    cancelled = record_of(world, second)
    assert cancelled.status == "CANCELLED" and cancelled.reissued_invoice is not None
    with tenant_context(t.pk):
        again = Invoice.objects.get(pk=cancelled.reissued_invoice.pk)
        assert Invoice.objects.get(pk=second.pk).status == "CANCELLED"
        assert EInvoiceRecord.objects.get(invoice=again).status == "GENERATED"
    assert again.number != second.number and again.fulfilment_id == second.fulfilment_id
    check_ledger(t)

    # Another distributor, modules off, sees none of it.
    other = world["other"]
    assert other.get(f"{API}/einvoices/").json()["results"] == []
    assert other.get(f"{API}/ewaybills/").json()["results"] == []
    assert other.get(f"{API}/payment-intents/").json()["results"] == []
