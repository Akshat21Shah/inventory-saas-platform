"""Printed documents (ADR-046 items 2, 7, 12): rendered after saving through the outbox, stored
privately, downloaded by signed link. The fake renderer carries the HTML, so these tests read
what would be printed; one test prints a real PDF where WeasyPrint's libraries are installed."""

from decimal import Decimal as D

import pytest
from celery.exceptions import Retry
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from apps.accounts.tests.factories import make_staff_in
from apps.billing import credit_notes, documents, pdf
from apps.billing.credit_notes import ReturnLine
from apps.billing.models import CreditNote, Invoice, OrderConfirmation
from apps.billing.tasks import render_document
from apps.billing.templatetags.documents import amount, qty, rate, rupees
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.orders import transitions
from apps.orders.tests.helpers import add_address, add_stock, make_shop, place, settings
from apps.payments import services as payments
from apps.payments.models import Payment
from apps.payments.services import PaymentInput
from common.dates import today_ist
from common.storage import get_storage
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(tenant_a):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a)
    a = make_product(tenant_a, "A", base_price=D("123.45"))  # 5% GST
    add_stock(tenant_a, a, "100")
    return {"t": tenant_a, "owner": owner, "shop": shop, "a": a}


def _printed(key):
    return get_storage().get(key).decode()


def _invoice(world, commits, qty="10"):
    with commits(execute=True):
        invoice = ship_invoice(world["t"], world["shop"], world["owner"], (world["a"], qty))
    with tenant_context(world["t"].pk):
        return Invoice.objects.get(pk=invoice.pk)


def test_numbers_are_printed_the_indian_way():
    assert amount(D("1234567.5")) == "12,34,567.50"
    assert amount(D("999")) == "999.00"
    assert rupees(D("-0.45")) == "-₹0.45"
    assert rupees(D("100000")) == "₹1,00,000.00"
    assert (qty(D("8.000")), qty(D("12.500")), rate(D("2.500"))) == ("8", "12.5", "2.5%")


def test_an_invoice_is_printed_once_for_the_shop_and_in_three_copies_for_staff(
    world, django_capture_on_commit_callbacks
):
    invoice = _invoice(world, django_capture_on_commit_callbacks)
    assert invoice.pdf_status == "READY"
    assert invoice.pdf_key.endswith(f"/documents/invoices/{invoice.number.replace('/', '-')}.pdf")
    original, copies = _printed(invoice.pdf_key), _printed(invoice.copies_pdf_key)
    assert original.startswith("%PDF")
    for text in (
        invoice.number,
        "Tax invoice",
        "Original for recipient",
        world["shop"].shop_name,
        "₹1,296.00",
        "Rupees One Thousand Two Hundred Ninety Six Only",
        "CGST",
        world["t"].gstin,
    ):
        assert text in original, text
    assert "Duplicate for transporter" not in original
    assert [copies.count(label) for label in documents.COPIES] == [1, 1, 1]
    assert "IGST (₹)" not in original and "IRN" not in original
    assert str(documents.download_url(invoice.pdf_key)).startswith("https://storage.test/tenants/")
    assert documents.download_url("") is None


def test_between_states_it_shows_igst(world, django_capture_on_commit_callbacks):
    add_address(world["t"], world["shop"], "24")
    invoice = _invoice(world, django_capture_on_commit_callbacks, "1")
    printed = _printed(invoice.pdf_key)
    assert "Between states (IGST)" in printed and "Gujarat (24)" in printed
    assert "CGST (₹)" not in printed


def test_credit_notes_and_receipts_are_printed(world, django_capture_on_commit_callbacks):
    invoice = _invoice(world, django_capture_on_commit_callbacks)
    with tenant_context(world["t"].pk), django_capture_on_commit_callbacks(execute=True):
        credit_notes.issue_return(
            invoice.pk,
            [ReturnLine(invoice.lines.get().pk, D("3"), "DAMAGED")],
            reason="DAMAGED",
            note="Crushed cartons",
            by=world["owner"],
        )
        payments.record_payment(
            PaymentInput(
                world["shop"].pk, D("500.00"), "CHEQUE", today_ist(), cheque_number="004512"
            ),
            by=world["owner"],
        )
    with tenant_context(world["t"].pk):
        note = CreditNote.objects.get()
        payment = Payment.objects.get()
    printed = _printed(note.pdf_key)
    for text in ("Credit note", note.number, invoice.number, "Crushed cartons", "Received damaged"):
        assert text in printed, text
    receipt = _printed(payment.receipt_pdf_key)
    for text in (
        "Payment receipt",
        payment.number,
        "₹500.00",
        "Rupees Five Hundred Only",
        "No. 004512",
        invoice.number,
        "Subject to the cheque being cleared",
    ):
        assert text in receipt, text
    assert payment.receipt_pdf_status == "READY"


def test_an_automatic_credit_note_says_so(world, django_capture_on_commit_callbacks):
    settings(world["t"], invoicing__timing="ON_ACCEPTANCE")
    order = place(world["t"], world["shop"], (world["a"], "2"))
    with tenant_context(world["t"].pk), django_capture_on_commit_callbacks(execute=True):
        transitions.accept_order(order.pk, by=world["owner"])
        from apps.orders import fulfilment

        fulfilment.cancel_accepted(order.pk, reason="Shop closed", by=world["owner"])
    with tenant_context(world["t"].pk):
        note = CreditNote.objects.get()
    assert "Issued automatically" in _printed(note.pdf_key)


def test_the_order_confirmation_at_acceptance(world, django_capture_on_commit_callbacks):
    order = place(world["t"], world["shop"], (world["a"], "2"))
    with tenant_context(world["t"].pk), django_capture_on_commit_callbacks(execute=True):
        transitions.accept_order(order.pk, by=world["owner"])
    with tenant_context(world["t"].pk):
        confirmation = OrderConfirmation.objects.get(order=order)
    printed = _printed(confirmation.pdf_key)
    for text in ("Order confirmation", "This is not a tax invoice.", order.number, "Product A"):
        assert text in printed, text
    assert confirmation.content["totals"]["grand_total"] == str(order.grand_total)

    settings(world["t"], orders__send_confirmation_on_accept=False)
    later = place(world["t"], world["shop"], (world["a"], "1"))
    with tenant_context(world["t"].pk):
        transitions.accept_order(later.pk, by=world["owner"])
        assert not OrderConfirmation.objects.filter(order=later).exists()


def test_a_failing_render_is_retried_then_marked_failed(
    world, django_capture_on_commit_callbacks, monkeypatch
):
    invoice = _invoice(world, django_capture_on_commit_callbacks)

    class Broken:
        calls = 0

        def render(self, html):
            Broken.calls += 1
            raise OSError("renderer down")

    monkeypatch.setattr("apps.billing.documents.get_renderer", lambda: Broken())
    kwargs = {"kind": "invoice", "object_id": str(invoice.pk), "tenant_id": str(world["t"].pk)}
    with pytest.raises(Retry):  # the first failure is retried, with backoff
        render_document.apply(kwargs=kwargs, throw=True)
    with tenant_context(world["t"].pk):
        invoice.refresh_from_db()
        assert invoice.pdf_status == "READY"  # the earlier PDF is still there
    with pytest.raises(OSError):  # the last try gives up
        render_document.apply(kwargs=kwargs, retries=5, throw=True)
    with tenant_context(world["t"].pk):
        invoice.refresh_from_db()
    assert (invoice.pdf_status, Broken.calls) == ("FAILED", 2)


def test_the_fake_renderer_is_refused_outside_development():
    pdf.get_renderer.cache_clear()
    try:
        with override_settings(ALLOW_MOCK_INTEGRATIONS=False), pytest.raises(ImproperlyConfigured):
            pdf.get_renderer()
    finally:
        pdf.get_renderer.cache_clear()


@pytest.mark.skipif(not pdf.weasyprint_available(), reason="WeasyPrint's system libraries missing")
def test_weasyprint_prints_a_real_invoice(world, django_capture_on_commit_callbacks):
    invoice = _invoice(world, django_capture_on_commit_callbacks)
    with tenant_context(world["t"].pk):
        invoice = Invoice.objects.select_related("order", "place_of_supply").get(pk=invoice.pk)
        from django.template.loader import render_to_string

        html = render_to_string(
            "billing/invoice.html", documents.invoice_context(invoice, documents.COPIES)
        )
    printed = pdf.WeasyPrintRenderer().render(html)
    assert printed.startswith(b"%PDF") and len(printed) > 5000
    from weasyprint import HTML

    assert len(HTML(string=html).render().pages) == 3  # one page per copy


def test_the_ca_samples_match_the_review_document(tmp_path, monkeypatch):
    """docs/ca/*.pdf come from this command (CA_REVIEW Example 5 and CN 1); no database."""
    from django.core.management import call_command

    monkeypatch.setattr(
        "apps.billing.management.commands.render_ca_samples.WeasyPrintRenderer", pdf.FakeRenderer
    )
    call_command("render_ca_samples", out=str(tmp_path))
    invoice = (tmp_path / "sample-invoice.pdf").read_text()
    copies = (tmp_path / "sample-invoice-copies.pdf").read_text()
    note = (tmp_path / "sample-credit-note.pdf").read_text()
    for text in ("₹8,005.95", "₹443.02", "₹0.01", "₹8,892.00", "1,340.32", "5,599.95"):
        assert text in invoice, text
    assert "Bank details" in invoice and copies.count("Triplicate for supplier") == 1
    for text in ("₹370.35", "₹33.33", "-₹0.01", "₹437.00", "INV/26-27/000123", "Received damaged"):
        assert text in note, text
    assert "Bank details" not in note
