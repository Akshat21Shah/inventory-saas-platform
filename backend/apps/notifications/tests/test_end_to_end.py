"""Every key event end to end with the mock providers (ADR-048): a shop's life from welcome to
refund, each step's outbox event turned into messages and "sent" by the mocks (WhatsApp, email,
SMS), every WhatsApp and SMS naming the distributor first, the document links opening the
current PDF, and nothing reaching the shop that it didn't agree to or doesn't concern it."""

from collections import Counter
from decimal import Decimal as D

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.accounts.adapters.sms import MockSmsSender
from apps.accounts.tests.factories import make_staff_in
from apps.billing import credit_notes
from apps.billing.credit_notes import ReturnLine
from apps.billing.tests.helpers import NO_TRANSPORT
from apps.inventory.tests.helpers import make_product
from apps.notifications import consent, quiet
from apps.notifications.adapters.whatsapp import MockWhatsAppClient
from apps.notifications.models import Notification
from apps.orders import fulfilment, transitions
from apps.orders.models import Fulfilment
from apps.orders.tests.helpers import add_stock, place, shop_user
from apps.payments import services as payments
from apps.payments.services import PaymentInput, RefundInput
from apps.platform import selectors
from apps.platform.models import FeatureFlag, TenantFeature
from apps.retailers.services import AddressInput, create_retailer
from common.dates import today_ist
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _mocks(monkeypatch):
    MockWhatsAppClient.outbox.clear()
    MockSmsSender.outbox.clear()
    monkeypatch.setattr(quiet, "current_hold", lambda now: None)


def test_a_shops_life_reaches_it_through_the_mocks(tenant_a, django_capture_on_commit_callbacks):
    t = tenant_a
    run = django_capture_on_commit_callbacks
    owner = make_staff_in(t, "OWNER")
    with tenant_context(t.pk):
        TenantFeature.objects.create(flag=FeatureFlag.objects.get(code="whatsapp"), enabled=True)
    selectors.invalidate_tenant_features(t.pk)
    product = make_product(t, "P-1", base_price=D("100"))
    add_stock(t, product, "100")

    # 1. Welcome (SMS), then the shop agrees to WhatsApp in the app.
    with run(execute=True), tenant_context(t.pk):
        shop = create_retailer(
            shop_name="Ganesh Kirana",
            phone="9876500051",
            email="ganesh@example.com",
            billing=AddressInput("12 Market Road", "Pune", "411001", "27"),
        )
    login = shop_user(shop)
    with tenant_context(t.pk):
        consent.set_whatsapp_consent(shop.pk, True, source=consent.Source.SHOP_APP, by=login)

    # 2. Orders: placed by the shop, accepted, packed, dispatched (bill), delivered.
    with run(execute=True):
        order = place(t, shop, (product, "5"))
    with run(execute=True), tenant_context(t.pk):
        transitions.accept_order(order.pk, by=owner)
    with run(execute=True), tenant_context(t.pk):
        shipment = Fulfilment.objects.get(order=order)
        fulfilment.pack(shipment.pk, {}, by=owner)
        fulfilment.dispatch(shipment.pk, NO_TRANSPORT, by=owner)
    # 3. A rejected order and a staff-cancelled one.
    with run(execute=True):
        second, third = place(t, shop, (product, "1")), place(t, shop, (product, "1"))
    with run(execute=True), tenant_context(t.pk):
        transitions.reject_order(second.pk, reason="Out of delivery area today", by=owner)
        transitions.cancel_order(third.pk, by=owner, reason="Duplicate")
    # 4. Money: a return (credit note), a cheque that bounces, cash, a refund.
    with tenant_context(t.pk):
        from apps.billing.models import Invoice

        bill = Invoice.objects.get(order=order)
    with run(execute=True), tenant_context(t.pk):
        credit_notes.issue_return(
            bill.pk,
            [ReturnLine(bill.lines.get().pk, D("1"))],
            reason="DAMAGED",
            note="",
            by=owner,
        )
    with run(execute=True), tenant_context(t.pk):
        cheque = payments.record_payment(
            PaymentInput(shop.pk, D("200.00"), "CHEQUE", today_ist(), cheque_number="004512"),
            by=owner,
        )
    with run(execute=True), tenant_context(t.pk):
        payments.bounce_cheque(cheque.pk, reason="Insufficient funds", by=owner)
    with run(execute=True), tenant_context(t.pk):
        payments.record_payment(
            PaymentInput(shop.pk, bill.grand_total + D("50.00"), "CASH", today_ist()), by=owner
        )
    with run(execute=True), tenant_context(t.pk):
        payments.record_refund(RefundInput(shop.pk, D("50.00"), "UPI", today_ist()), by=owner)

    # WhatsApp: one message per shop-facing event that uses it, the distributor named first.
    sent = Counter(m.message.template for m in MockWhatsAppClient.outbox)
    assert sent == {
        "b2b_order_accepted": 1,
        "b2b_invoice_issued": 1,
        "b2b_order_rejected": 1,
        "b2b_order_cancelled": 1,
        "b2b_credit_note_issued": 1,
        "b2b_payment_received": 2,
        "b2b_payment_bounced": 1,
        "b2b_refund_recorded": 1,
    }
    for message in MockWhatsAppClient.outbox:
        assert message.message.to == shop.mobile
        assert message.message.text.startswith(f"{t.name}:"), message.message.text
        assert message.message.parameters[0] == t.name
        assert "{{" not in message.message.text
    [bounce] = [m for m in MockWhatsAppClient.outbox if m.message.template == "b2b_payment_bounced"]
    assert "cheque 004512 dated " in bounce.message.text and "₹200.00" in bounce.message.text
    assert bounce.message.text.endswith(" to pay.")  # the bills are owed again
    # Email: the bill, the credit note and receipts, to the shop's address.
    to_shop = sorted(m.subject.split(" ")[0] for m in mail.outbox if m.to == ["ganesh@example.com"])
    assert to_shop == ["Credit", "Receipt", "Receipt", "Tax"]
    # SMS: only the welcome.
    assert [s.template for s in MockSmsSender.outbox] == ["retailer_welcome"]
    # In-app: the shop's bell holds its whole story; the owner's holds the office's.
    with tenant_context(t.pk):
        shop_bell = set(
            Notification.objects.filter(recipient=login, channel="IN_APP").values_list(
                "event_code", flat=True
            )
        )
        office_bell = set(
            Notification.objects.filter(recipient=owner, channel="IN_APP").values_list(
                "event_code", flat=True
            )
        )
        failed = Notification.objects.filter(status__in=["FAILED", "PENDING", "SENDING"])
        assert not failed.exists()
    assert shop_bell >= {
        "order.placed",
        "order.accepted",
        "order.dispatched",
        "invoice.issued",
        "order.rejected",
        "order.cancelled",
        "credit_note.issued",
        "payment.received",
        "payment.bounced",
        "refund.recorded",
    }
    assert office_bell >= {"order.placed", "payment.bounced"}
    assert "invoice.issued" not in office_bell

    # Every document link in a WhatsApp message opens its PDF without signing in.
    links = [
        word
        for m in MockWhatsAppClient.outbox
        for word in m.message.text.split()
        if "/api/v1/public/documents/" in word
    ]
    assert len(links) == 6  # confirmation, bill, credit note, two receipts, refund voucher
    for link in links:
        path = link[link.index("/api/v1/") :]
        opened = APIClient().get(path, HTTP_X_FORWARDED_HOST=f"{t.slug}.localhost")
        assert opened.status_code == 302, (link, opened.status_code)
