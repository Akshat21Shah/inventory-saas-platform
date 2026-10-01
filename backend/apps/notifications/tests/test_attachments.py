"""Documents' PDFs attached to the shop's and the supplier's emails (ADR-054): besides the secure
link, never for staff; held while the PDF is being printed (not a try), then the link alone when
it isn't ready, failed or is too big; and SES gets the attachment as raw MIME."""

from datetime import timedelta
from decimal import Decimal as D
from typing import Any

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts.tests.factories import make_staff_in
from apps.billing.models import Invoice
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.notifications import delivery
from apps.notifications.adapters.email import Attachment, Email, SesEmailSender
from apps.notifications.models import DeliveryAttempt, Notification
from apps.orders.tests.helpers import add_stock, make_shop
from apps.payments import services as payments
from apps.payments.services import PaymentInput
from common.dates import today_ist
from common.storage import get_storage
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(tenant_a, django_capture_on_commit_callbacks):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a, email="shop@example.com")
    product = make_product(tenant_a, "P-1")
    add_stock(tenant_a, product, "100")
    with django_capture_on_commit_callbacks(execute=True):
        bill = ship_invoice(tenant_a, shop, owner, (product, "2"))
    with tenant_context(tenant_a.pk):
        bill.refresh_from_db()
    return {
        "t": tenant_a,
        "bill": bill,
        "owner": owner,
        "shop": shop,
        "run": lambda: django_capture_on_commit_callbacks(execute=True),
    }


def shop_email(world: dict[str, Any]) -> Notification:
    with tenant_context(world["t"].pk):
        row: Notification = Notification.objects.get(event_code="invoice.issued", channel="EMAIL")
        return row


def again(world: dict[str, Any], **data: Any) -> str:
    """Send the shop's invoice email again from scratch."""
    row = shop_email(world)
    with tenant_context(world["t"].pk):
        Notification.objects.filter(pk=row.pk).update(
            status="PENDING", attempts=0, send_after=None, data={**row.data, **data}
        )
        return delivery.deliver(row.pk)


def test_the_shops_invoice_email_carries_the_pdf_and_still_the_link(world):
    bill = world["bill"]
    [email] = [m for m in mail.outbox if m.to == ["shop@example.com"]]
    filename = bill.number.replace("/", "-") + ".pdf"  # INV-26-27-000001.pdf
    assert email.attachments == [(filename, get_storage().get(bill.pdf_key), "application/pdf")]
    assert "/public/documents/" in email.body
    row = shop_email(world)
    assert row.data["attachment"] == {"file": filename}
    with tenant_context(world["t"].pk):
        attempt = DeliveryAttempt.objects.get(notification=row)
        # Only the shop's (or a supplier's) email: never in-app or for staff.
        flagged = set(
            Notification.objects.filter(data__attach=True).values_list("channel", "retailer_id")
        )
    assert attempt.response["attachment"] == {"file": filename}
    assert flagged == {("EMAIL", bill.retailer_id)}


def test_the_payment_receipt_email_carries_the_receipt(world):
    with world["run"](), tenant_context(world["t"].pk):
        paid = payments.record_payment(
            PaymentInput(world["shop"].pk, D("80.00"), "CASH", today_ist()), by=world["owner"]
        )
    with tenant_context(world["t"].pk):
        paid.refresh_from_db()
    [email] = [m for m in mail.outbox if m.subject.startswith("Receipt")]
    assert email.attachments == [
        (
            paid.number.replace("/", "-") + ".pdf",
            get_storage().get(paid.receipt_pdf_key),
            "application/pdf",
        )
    ]


def test_held_while_the_pdf_is_printed_then_the_link_alone(world):
    with tenant_context(world["t"].pk):
        Invoice.objects.filter(pk=world["bill"].pk).update(pdf_status="PENDING")
    mail.outbox.clear()
    assert again(world) == ""  # held, not a try
    row = shop_email(world)
    assert (row.status, row.attempts, mail.outbox) == ("PENDING", 0, [])
    assert row.send_after is not None and row.send_after > timezone.now()
    # Still not printed after the wait: the email goes with the link alone.
    waited = (timezone.now() - delivery.PDF_WAIT - timedelta(seconds=1)).isoformat()
    assert again(world, pdf_wait_since=waited) == "SENT"
    [email] = mail.outbox
    assert email.attachments == [] and "/public/documents/" in email.body
    assert shop_email(world).data["attachment"] == {"skipped": "NOT_READY"}


def test_a_failed_or_too_big_pdf_leaves_the_link_alone(world, monkeypatch):
    mail.outbox.clear()
    monkeypatch.setattr(delivery, "MAX_ATTACHMENT_BYTES", 10)
    assert again(world) == "SENT"
    assert mail.outbox[-1].attachments == []
    assert shop_email(world).data["attachment"] == {"skipped": "TOO_LARGE"}
    monkeypatch.undo()
    with tenant_context(world["t"].pk):
        Invoice.objects.filter(pk=world["bill"].pk).update(pdf_status="FAILED")
    assert again(world) == "SENT"  # no waiting for a PDF that failed
    assert mail.outbox[-1].attachments == []
    assert shop_email(world).data["attachment"] == {"skipped": "PDF_FAILED"}


def test_ses_sends_an_attachment_as_raw_mime(monkeypatch):
    sent: list[dict[str, Any]] = []

    class Client:
        def send_email(self, **request: Any) -> dict[str, str]:
            sent.append(request)
            return {"MessageId": "m-1"}

    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: Client())
    sender = SesEmailSender()
    plain = Email("shop@example.com", "Your bill", "Link: …", "Sharma", "office@example.com")
    sender.send(plain)
    sender.send(Email(**{**plain.__dict__, "attachments": (Attachment("INV-1.pdf", b"%PDF"),)}))
    assert set(sent[0]["Content"]) == {"Simple"}
    assert sent[0]["ReplyToAddresses"] == ["office@example.com"]
    raw = sent[1]["Content"]["Raw"]["Data"].decode()
    assert 'filename="INV-1.pdf"' in raw and "Reply-To: office@example.com" in raw
    assert "ReplyToAddresses" not in sent[1]
