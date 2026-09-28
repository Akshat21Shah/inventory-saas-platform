"""Secure document links (ADR-048 item 8): one link per event carried by the shop's WhatsApp and
email, only the token's hash stored, opened on the tenant's address without signing in to the
current PDF, counted, expiring after the setting's days, revocable by staff who manage the
document (audited), and never opened from another tenant's address."""

import hashlib
import re
from datetime import timedelta
from decimal import Decimal as D
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.accounts.tests.factories import make_staff_in
from apps.audit.models import AuditLog
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.notifications import links
from apps.notifications.models import DocumentLink, Notification
from apps.orders.tests.helpers import add_stock, make_shop, settings
from apps.payments import services as payments
from apps.payments.models import Payment
from apps.payments.services import PaymentInput
from apps.platform import selectors
from apps.platform.models import FeatureFlag, TenantFeature
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.storage import get_storage
from common.tenancy import tenant_context
from common.testing.isolation import covers

pytestmark = pytest.mark.django_db
LINK = re.compile(r"https?://alpha\.localhost/api/v1/public/documents/([A-Za-z0-9_-]+)/")


@pytest.fixture
def world(tenant_a, django_capture_on_commit_callbacks):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a, email="shop@example.com")
    with tenant_context(tenant_a.pk):
        Retailer.objects.filter(pk=shop.pk).update(whatsapp_opt_in=True)
        TenantFeature.objects.create(flag=FeatureFlag.objects.get(code="whatsapp"), enabled=True)
    selectors.invalidate_tenant_features(tenant_a.pk)
    product = make_product(tenant_a, "P-1")
    add_stock(tenant_a, product, "100")
    return {
        "t": tenant_a,
        "owner": owner,
        "shop": shop,
        "product": product,
        "run": lambda: django_capture_on_commit_callbacks(execute=True),
    }


def invoice(world: dict[str, Any]) -> Any:
    with world["run"]():
        return ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "2"))


def bodies(world: dict[str, Any], code: str) -> dict[str, str]:
    with tenant_context(world["t"].pk):
        return dict(Notification.objects.filter(event_code=code).values_list("channel", "body"))


def token_in(text: str) -> str:
    found = LINK.search(text)
    assert found, text
    return found.group(1)


def visit(token: str, slug: str = "alpha") -> Any:
    return APIClient().get(
        f"/api/v1/public/documents/{token}/", HTTP_X_FORWARDED_HOST=f"{slug}.localhost"
    )


def test_the_invoice_messages_carry_one_link_that_opens_the_pdf(world):
    bill = invoice(world)
    texts = bodies(world, "invoice.issued")
    token = token_in(texts["WHATSAPP"])
    assert token_in(texts["EMAIL"]) == token  # one link per event
    assert "documents" not in texts["IN_APP"]  # signed-in people use the app
    with tenant_context(world["t"].pk):
        [link] = DocumentLink.objects.filter(kind="INVOICE")
        bill.refresh_from_db()
    assert link.object_id == bill.pk
    assert link.token_hash == hashlib.sha256(token.encode()).hexdigest() != token
    assert timedelta(days=29, hours=23) < link.expires_at - timezone.now() <= timedelta(days=30)
    response = visit(token)
    assert response.status_code == 302
    assert response["Location"] == f"https://storage.test/{bill.pdf_key}?expires_in=300"
    assert response["Cache-Control"] == "no-store"
    visit(token)
    with tenant_context(world["t"].pk):
        link.refresh_from_db()
    assert link.open_count == 2 and link.last_opened_at is not None


def test_links_follow_the_setting_and_are_not_made_twice(world):
    settings(world["t"], notifications__document_link_days=7)
    invoice(world)
    with tenant_context(world["t"].pk):
        link = DocumentLink.objects.get(kind="INVOICE")
        event_id = Notification.objects.filter(event_code="invoice.issued")[0].event_id
    assert link.expires_at - timezone.now() <= timedelta(days=7)
    from apps.notifications.tasks import dispatch_event

    with world["run"]():
        dispatch_event(event_id=str(event_id), tenant_id=str(world["t"].pk))
    with tenant_context(world["t"].pk):
        assert DocumentLink.objects.filter(kind="INVOICE").count() == 1


def test_no_link_when_no_shop_message_carries_it(world):
    with tenant_context(world["t"].pk):
        Retailer.objects.filter(pk=world["shop"].pk).update(email="", whatsapp_opt_in=False)
    invoice(world)
    with tenant_context(world["t"].pk):
        assert not DocumentLink.objects.exists()


@covers("public-document")
def test_expired_revoked_unknown_and_other_tenant_links(world, tenant_b):
    bill = invoice(world)
    token = token_in(bodies(world, "invoice.issued")["WHATSAPP"])
    assert visit(token, "bravo").status_code == 404  # another tenant's address
    assert visit("made-up").status_code == 404
    assert visit("x" * 150).status_code == 404
    sales = make_staff_in(world["t"], "SALES")
    with tenant_context(world["t"].pk), pytest.raises(PermissionDenied):
        links.revoke("INVOICE", bill.pk, by=sales)  # can't manage invoices
    with tenant_context(world["t"].pk):
        assert links.revoke("INVOICE", bill.pk, by=world["owner"]) == 1
        assert AuditLog.objects.filter(action="notifications.document_links_revoked").exists()
        assert links.revoke("INVOICE", bill.pk, by=world["owner"]) == 0
    gone = visit(token)
    assert gone.status_code == 410 and b"no longer works" in gone.content
    assert world["t"].name.encode() in gone.content
    with world["run"]():
        second = ship_invoice(world["t"], world["shop"], world["owner"], (world["product"], "1"))
    with tenant_context(world["t"].pk):
        link = DocumentLink.objects.get(object_id=second.pk)
        DocumentLink.objects.filter(pk=link.pk).update(expires_at=timezone.now())
        texts = list(
            Notification.objects.filter(
                event_code="invoice.issued", channel="WHATSAPP", body__contains=second.number
            ).values_list("body", flat=True)
        )
    expired = visit(token_in(texts[0]))
    assert expired.status_code == 410 and b"expired" in expired.content


def test_the_receipt_link_opens_the_receipt_printed_again_after_a_bounce(world):
    with world["run"](), tenant_context(world["t"].pk):
        cheque = payments.record_payment(
            PaymentInput(world["shop"].pk, D("80.00"), "CHEQUE", today_ist(), cheque_number="7"),
            by=world["owner"],
        )
    token = token_in(bodies(world, "payment.received")["WHATSAPP"])
    with world["run"](), tenant_context(world["t"].pk):
        payments.bounce_cheque(cheque.pk, reason="Insufficient funds", by=world["owner"])
    with tenant_context(world["t"].pk):  # as while the worker prints it again
        Payment.objects.filter(pk=cheque.pk).update(receipt_pdf_status="PENDING")
    waiting = visit(token)
    assert waiting.status_code == 200 and b"being prepared" in waiting.content
    with tenant_context(world["t"].pk):
        Payment.objects.filter(pk=cheque.pk).update(receipt_pdf_status="READY")
        cheque.refresh_from_db()
    opened = visit(token)
    assert opened.status_code == 302 and cheque.receipt_pdf_key in opened["Location"]
    assert "Cheque bounced" in get_storage().get(cheque.receipt_pdf_key).decode()
