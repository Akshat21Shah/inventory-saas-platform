"""Shop documents in the shop's language (ADR-060 item 6): labels in English and then the shop's
language ("Tax invoice / कर बीजक"), names and amounts as entered; English only when the shop's
language is English or the distributor chose English only; the language is fixed at issue, so a
reprint is identical; every label the templates print is in the catalogs; Hindi PDFs embed a
Devanagari font."""

import re
from decimal import Decimal as D
from pathlib import Path

import pytest
from django.template.loader import render_to_string

from apps.accounts.tests.factories import make_staff_in
from apps.billing import documents, labels, pdf
from apps.billing.models import Invoice
from apps.billing.tests.helpers import ship_invoice
from apps.inventory.tests.helpers import make_product
from apps.orders.tests.helpers import add_stock, make_shop, settings
from apps.payments import services as payments
from apps.payments.models import Payment
from apps.payments.services import PaymentInput
from apps.retailers.models import Retailer
from common.dates import today_ist
from common.storage import get_storage
from common.tenancy import tenant_context

pytestmark = pytest.mark.django_db
TEMPLATES = Path(documents.__file__).with_name("templates") / "billing"


@pytest.fixture
def world(tenant_a, every_language):
    owner = make_staff_in(tenant_a, "OWNER")
    shop = make_shop(tenant_a, "9876500195")
    with tenant_context(tenant_a.pk):
        Retailer.objects.filter(pk=shop.pk).update(preferred_language="hi")
    product = make_product(tenant_a, "A", base_price=D("100.00"))
    add_stock(tenant_a, product, "100")
    return {"t": tenant_a, "owner": owner, "shop": shop, "a": product}


def _invoice(world, commits) -> Invoice:
    with commits(execute=True):
        invoice = ship_invoice(world["t"], world["shop"], world["owner"], (world["a"], "2"))
    with tenant_context(world["t"].pk):
        found: Invoice = Invoice.objects.select_related("order", "place_of_supply").get(
            pk=invoice.pk
        )
    return found


def _html(invoice: Invoice) -> str:
    with tenant_context(invoice.tenant_id):
        return render_to_string(
            "billing/invoice.html", documents.invoice_context(invoice, documents.COPIES)
        )


def test_a_hindi_shops_bill_has_hindi_labels_after_the_english(
    world, django_capture_on_commit_callbacks
):
    invoice = _invoice(world, django_capture_on_commit_callbacks)
    assert invoice.document_language == "hi"
    html = _html(invoice)
    assert 'lang="hi"' in html
    assert 'Tax invoice <span class="tr">/ कर बीजक</span>' in html
    assert 'Original for recipient <span class="tr">/ प्राप्तकर्ता के लिए मूल</span>' in html
    assert 'Place of supply <span class="tr">/ आपूर्ति का स्थान</span>' in html
    assert "CGST" in html and "rupees" in html.lower()  # codes and the amount in words: English
    # What the shop downloads is the same document.
    printed = get_storage().get(invoice.pdf_key).decode()
    assert "कर बीजक" in printed


def test_english_only_when_the_distributor_chooses_it(world, django_capture_on_commit_callbacks):
    settings(world["t"], documents__language="ENGLISH")
    invoice = _invoice(world, django_capture_on_commit_callbacks)
    assert invoice.document_language == "en"
    html = _html(invoice)
    assert 'class="tr"' not in html and "कर बीजक" not in html
    assert ">Tax invoice<" in html


def test_the_language_is_fixed_at_issue(world, django_capture_on_commit_callbacks):
    invoice = _invoice(world, django_capture_on_commit_callbacks)
    before = _html(invoice)
    with tenant_context(world["t"].pk):  # the shop changes its language later
        Retailer.objects.filter(pk=world["shop"].pk).update(preferred_language="mr")
    invoice.refresh_from_db()
    assert _html(invoice) == before  # a reprint is identical


def test_a_receipt_shows_the_mode_in_both_languages(world, django_capture_on_commit_callbacks):
    settings(world["t"], payments__hold_advances=True)
    with django_capture_on_commit_callbacks(execute=True), tenant_context(world["t"].pk):
        payment = payments.record_payment(
            PaymentInput(world["shop"].pk, D("150.00"), "CASH", today_ist()), by=world["owner"]
        )
    with tenant_context(world["t"].pk):
        payment = Payment.objects.select_related("retailer").get(pk=payment.pk)
        html = render_to_string("billing/receipt.html", documents.receipt_context(payment))
    assert payment.document_language == "hi"
    assert 'Cash <span class="tr">/ नकद</span>' in html
    assert 'Payment receipt <span class="tr">/ भुगतान रसीद</span>' in html


def test_an_english_shops_documents_are_english_only(world, django_capture_on_commit_callbacks):
    with tenant_context(world["t"].pk):
        Retailer.objects.filter(pk=world["shop"].pk).update(preferred_language="")
    invoice = _invoice(world, django_capture_on_commit_callbacks)
    assert invoice.document_language == "en"
    assert 'class="tr"' not in _html(invoice)


def test_every_label_the_templates_print_is_in_the_catalogs():
    printed: set[str] = set()
    for template in TEMPLATES.glob("*.html"):
        printed |= set(re.findall(r'{%\s*t\s+"([^"]+)"', template.read_text(encoding="utf-8")))
    listed = set(labels.LABELS)
    assert printed - listed == set()  # add new labels to apps/billing/labels.py
    assert listed - printed == set(documents.COPIES)  # the copies are printed from a variable


@pytest.mark.skipif(not pdf.weasyprint_available(), reason="WeasyPrint's system libraries missing")
def test_a_hindi_pdf_embeds_a_devanagari_font(world, django_capture_on_commit_callbacks):
    from weasyprint import HTML

    printed = HTML(string=_html(_invoice(world, django_capture_on_commit_callbacks))).write_pdf(
        uncompressed_pdf=True
    )
    assert printed is not None
    fonts = set(re.findall(rb"/BaseFont\s*/([A-Z]{6}\+)?([\w-]+)", printed))
    assert any(b"Devanagari" in name for _, name in fonts), fonts
